"""pH del suelo por celda.

Fuente principal: SoilGrids 2.0 (ISRIC, CC BY 4.0), 250 m, pH en agua ×10.
Se descarga una vez por recortes de 2º × 2º y se promedia en cada celda
(media de 0-5 y 5-15 cm, donde vive el micelio).

Ajuste opcional con LUCAS Topsoil (JRC/ESDAC): son muestras de campo reales.
Se piden gratis en https://esdac.jrc.ec.europa.eu/ (formulario). Deja el CSV en
data/lucas/ y cada celda con muestras se corrige hacia la mediana medida.

  python -m pipeline.soil
"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .config import BBOX, DATA_DIR, GRID_STEP
from .grid import build_grid

WCS = "https://maps.isric.org/mapserv?map=/map/phh2o.map"
DEPTHS = ["0-5cm", "5-15cm"]
TILE = 2.0
TILE_DIR = DATA_DIR / "soilgrids"
LUCAS_DIR = DATA_DIR / "lucas"
PH_FILE = DATA_DIR / f"ph_{GRID_STEP}.json"
LUCAS_WEIGHT = 2.0   # cuántas muestras LUCAS «valen» lo mismo que SoilGrids en una celda


def _tiles():
    lon0, lat0, lon1, lat1 = BBOX
    for lo in np.arange(lon0, lon1, TILE):
        for la in np.arange(lat0, lat1, TILE):
            yield round(lo, 2), round(la, 2), round(min(lo + TILE, lon1), 2), round(min(la + TILE, lat1), 2)


def download_tile(depth: str, box: tuple) -> Path:
    lo0, la0, lo1, la1 = box
    f = TILE_DIR / f"ph_{depth}_{lo0}_{la0}.tif"
    if f.exists():
        return f
    params = [("SERVICE", "WCS"), ("VERSION", "2.0.1"), ("REQUEST", "GetCoverage"),
              ("COVERAGEID", f"phh2o_{depth}_mean"), ("FORMAT", "image/tiff"),
              ("SUBSET", f"long({lo0},{lo1})"), ("SUBSET", f"lat({la0},{la1})"),
              ("SUBSETTINGCRS", "http://www.opengis.net/def/crs/EPSG/0/4326"),
              ("OUTPUTCRS", "http://www.opengis.net/def/crs/EPSG/0/4326")]
    for attempt in range(5):
        r = requests.get(WCS, params=params, timeout=300)
        if r.status_code == 200 and r.content[:2] in (b"II", b"MM"):
            TILE_DIR.mkdir(parents=True, exist_ok=True)
            f.write_bytes(r.content)
            return f
        time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"SoilGrids no devuelve el recorte {box} ({r.status_code})")


def cell_lookup(cells: list[dict]) -> np.ndarray:
    """Matriz (i, j) -> índice de celda, -1 si la celda no es tierra."""
    lk = -np.ones((max(c["i"] for c in cells) + 1, max(c["j"] for c in cells) + 1), int)
    for k, c in enumerate(cells):
        lk[c["i"], c["j"]] = k
    return lk


def aggregate_tile(path: Path, lookup: np.ndarray, step: float, sums: np.ndarray, counts: np.ndarray):
    """Suma los píxeles válidos del recorte en la celda de la malla a la que pertenecen."""
    import rasterio
    with rasterio.open(path) as src:
        a = src.read(1).astype(float)
        t, nodata = src.transform, src.nodata
    rows, cols = np.indices(a.shape)
    xs = t.c + (cols + 0.5) * t.a
    ys = t.f + (rows + 0.5) * t.e
    ok = (a > 0) & (a < 140)
    if nodata is not None:
        ok &= a != nodata
    ii = ((ys[ok] - BBOX[1]) // step).astype(int)
    jj = ((xs[ok] - BBOX[0]) // step).astype(int)
    inside = (ii >= 0) & (jj >= 0) & (ii < lookup.shape[0]) & (jj < lookup.shape[1])
    k = np.full(ii.shape, -1)
    k[inside] = lookup[ii[inside], jj[inside]]
    m = k >= 0
    np.add.at(sums, k[m], a[ok][m] / 10)
    np.add.at(counts, k[m], 1)


def lucas_adjust(ph: np.ndarray, cells: list[dict], step: float) -> tuple[np.ndarray, int]:
    files = list(LUCAS_DIR.glob("*.csv")) if LUCAS_DIR.exists() else []
    if not files:
        return ph, 0
    df = pd.concat([pd.read_csv(f, low_memory=False) for f in files], ignore_index=True)
    col = lambda names: next((c for c in df.columns if c.strip().lower() in names), None)
    lat = col({"th_lat", "gps_lat", "lat", "latitude"})
    lon = col({"th_long", "th_lon", "gps_long", "lon", "longitude"})
    phc = col({"ph_h2o", "ph(h2o)", "ph_in_h2o", "phh2o", "ph"})
    if not (lat and lon and phc):
        print(f"LUCAS: no reconozco las columnas ({list(df.columns)[:12]}…); se ignora")
        return ph, 0
    df = df[[lat, lon, phc]].apply(pd.to_numeric, errors="coerce").dropna()
    idx = {(c["i"], c["j"]): k for k, c in enumerate(cells)}
    df["k"] = [idx.get((int((a - BBOX[1]) // step), int((b - BBOX[0]) // step))) for a, b in zip(df[lat], df[lon])]
    df = df.dropna(subset=["k"])
    out = ph.copy()
    for k, g in df.groupby("k"):
        k, n, med = int(k), len(g), float(g[phc].median())
        out[k] = med if np.isnan(out[k]) else (LUCAS_WEIGHT * out[k] + n * med) / (LUCAS_WEIGHT + n)
    return out, len(df)


def build_ph(step: float = GRID_STEP) -> np.ndarray:
    cells = build_grid(step)
    lookup = cell_lookup(cells)
    per_depth = []
    for depth in DEPTHS:
        sums, counts = np.zeros(len(cells)), np.zeros(len(cells))
        for box in _tiles():
            aggregate_tile(download_tile(depth, box), lookup, step, sums, counts)
        per_depth.append(np.where(counts > 0, sums / np.maximum(counts, 1), np.nan))
        print(f"· pH {depth}: {int((counts > 0).sum())} celdas con dato")
    ph = np.nanmean(np.stack(per_depth), 0)
    ph, n_lucas = lucas_adjust(ph, cells, step)
    if n_lucas:
        print(f"· LUCAS: {n_lucas} muestras de campo aplicadas")
    PH_FILE.write_text(json.dumps([None if np.isnan(v) else round(float(v), 2) for v in ph]))
    print(f"OK -> {PH_FILE.relative_to(DATA_DIR.parent)}")
    return ph


def load_ph(n: int) -> np.ndarray | None:
    if not PH_FILE.exists():
        return None
    v = np.array([np.nan if x is None else x for x in json.loads(PH_FILE.read_text())], float)
    return v if len(v) == n else None


if __name__ == "__main__":
    build_ph()
