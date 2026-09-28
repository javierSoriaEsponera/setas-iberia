"""Humedad del suelo por satélite: NASA SMAP L3 mejorado (SPL3SMP_E, 9 km, diario).

Es opcional. Necesita una cuenta gratuita de NASA Earthdata
(https://urs.earthdata.nasa.gov) y dos variables de entorno:
  EARTHDATA_USERNAME y EARTHDATA_PASSWORD
(en GitHub: Settings -> Secrets and variables -> Actions).

SMAP mide los 5 cm superiores del suelo en m³/m³, con 1-2 días de retraso y
huecos entre pasadas; por eso se combina la media de los últimos días con la
humedad del modelo (Open-Meteo) en lugar de usarla sola.
"""
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from .config import BBOX

SHORT_NAME = "SPL3SMP_E"
DAYS_BACK = 4


def _read_granule(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Devuelve lat, lon y humedad válidas dentro de la península (pasadas AM y PM)."""
    import h5py
    lats, lons, vals = [], [], []
    with h5py.File(path, "r") as h:
        for grp, suf in (("Soil_Moisture_Retrieval_Data_AM", ""), ("Soil_Moisture_Retrieval_Data_PM", "_pm")):
            if grp not in h:
                continue
            g = h[grp]
            sm = g[f"soil_moisture{suf}"][:] if f"soil_moisture{suf}" in g else g["soil_moisture"][:]
            la = g[f"latitude{suf}"][:] if f"latitude{suf}" in g else g["latitude"][:]
            lo = g[f"longitude{suf}"][:] if f"longitude{suf}" in g else g["longitude"][:]
            ok = (sm > 0) & (sm < 0.7) & (la >= BBOX[1]) & (la <= BBOX[3]) & (lo >= BBOX[0]) & (lo <= BBOX[2])
            lats.append(la[ok]); lons.append(lo[ok]); vals.append(sm[ok])
    if not vals:
        return np.array([]), np.array([]), np.array([])
    return np.concatenate(lats), np.concatenate(lons), np.concatenate(vals)


def to_cells(lat, lon, sm, cells: list[dict], step: float) -> np.ndarray:
    """Media de los píxeles SMAP que caen en cada celda (NaN si ninguno)."""
    lk = {(c["i"], c["j"]): k for k, c in enumerate(cells)}
    sums, cnt = np.zeros(len(cells)), np.zeros(len(cells))
    for a, b, v in zip(((lat - BBOX[1]) // step).astype(int), ((lon - BBOX[0]) // step).astype(int), sm):
        k = lk.get((a, b))
        if k is not None:
            sums[k] += v; cnt[k] += 1
    return np.where(cnt > 0, sums / np.maximum(cnt, 1), np.nan)


def fetch_smap(cells: list[dict], step: float, today: date | None = None) -> np.ndarray | None:
    """Humedad media de los últimos días por celda, o None si no hay credenciales o datos."""
    if not (os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD")):
        print("SMAP: sin credenciales de Earthdata, se usa solo la humedad del modelo")
        return None
    try:
        import earthaccess
        earthaccess.login(strategy="environment")
        today = today or date.today()
        results = earthaccess.search_data(short_name=SHORT_NAME,
                                          temporal=((today - timedelta(days=DAYS_BACK)).isoformat(), today.isoformat()),
                                          bounding_box=(BBOX[0], BBOX[1], BBOX[2], BBOX[3]))
        if not results:
            print("SMAP: no hay pasadas recientes")
            return None
        tmp = Path(tempfile.mkdtemp(prefix="smap_"))
        files = earthaccess.download(results, str(tmp))
        parts = [_read_granule(Path(f)) for f in files]
        lat = np.concatenate([p[0] for p in parts]); lon = np.concatenate([p[1] for p in parts])
        sm = np.concatenate([p[2] for p in parts])
        for f in files:
            Path(f).unlink(missing_ok=True)
        out = to_cells(lat, lon, sm, cells, step)
        print(f"SMAP: {len(files)} ficheros, {int(np.isfinite(out).sum())} celdas con dato de satélite")
        return out
    except Exception as e:  # el satélite nunca debe tumbar la previsión diaria
        print(f"SMAP: no disponible hoy ({e.__class__.__name__}: {e})")
        return None


def blend(sm_model: np.ndarray, smap: np.ndarray | None, t0: int, weight: float = 0.5) -> tuple[np.ndarray, str]:
    """Corrige el sesgo del modelo con el satélite: desplaza toda la serie de cada celda
    la mitad de la diferencia entre SMAP y el modelo en los últimos días."""
    if smap is None or not np.isfinite(smap).any():
        return sm_model, "modelo (Open-Meteo)"
    recent = np.nanmean(sm_model[:, max(0, t0 - DAYS_BACK):t0 + 1], 1)
    offset = np.where(np.isfinite(smap) & np.isfinite(recent), smap - recent, 0.0)
    return np.clip(sm_model + weight * offset[:, None], 0.01, 0.6), "satélite SMAP + modelo"
