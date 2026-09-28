"""Meteorología diaria (últimos 35 días + previsión 7 días) de Open-Meteo.

Open-Meteo combina modelos de AEMET (HARMONIE-AROME), ECMWF, DWD, Météo-France…
y devuelve también la altitud de cada punto (MDT de 90 m).
Plan gratuito: uso no comercial y ~10.000 llamadas/día. Si comercializas la app,
contrata el plan de pago o usa directamente AEMET OpenData.
"""
import time

import numpy as np
import requests

from .config import FORECAST_DAYS, PAST_DAYS

URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
# Humedad del suelo del modelo por capas; se combina en 0-7 cm para que sea
# comparable con ERA5-Land (histórico, usado en la calibración) y con SMAP (0-5 cm).
SM_LAYERS = {"soil_moisture_0_to_1cm": 1, "soil_moisture_1_to_3cm": 2, "soil_moisture_3_to_9cm": 4}
DAILY = "precipitation_sum,temperature_2m_max,temperature_2m_min,et0_fao_evapotranspiration,wind_gusts_10m_max"


class OpenMeteoError(RuntimeError):
    pass


def _get_retry(url: str, params: dict, tries: int = 6, timeout=(20, 180)) -> dict | list:
    """GET con reintentos ante cortes de red, tiempos de espera agotados, 429 y errores 5xx.
    Espera 15 s, 30 s, 60 s, 2 min y 4 min entre intentos."""
    last = None
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", 60 * (attempt + 1)))
            elif r.status_code >= 500:
                wait = 15 * 2 ** attempt
            else:
                raise OpenMeteoError(last)          # 4xx: petición incorrecta, no tiene sentido repetir
        except requests.RequestException as e:      # timeout, conexión cortada, fallo SSL…
            last = f"{e.__class__.__name__}: {e}"
            wait = 15 * 2 ** attempt
        if attempt < tries - 1:
            print(f"    Open-Meteo no responde ({last[:90]}); reintento en {wait:.0f} s")
            time.sleep(wait)
    raise OpenMeteoError(f"Open-Meteo sigue sin responder tras {tries} intentos: {last}")


def _fetch_chunk(chunk: list[dict]) -> list[dict]:
    """Descarga un grupo de puntos; si falla, lo parte en dos y lo intenta por mitades."""
    params = {
        "latitude": ",".join(str(c["lat"]) for c in chunk),
        "longitude": ",".join(str(c["lon"]) for c in chunk),
        "daily": DAILY, "hourly": ",".join(SM_LAYERS), "past_days": PAST_DAYS, "forecast_days": FORECAST_DAYS,
        "timezone": "Europe/Madrid",
    }
    try:
        js = _get_retry(URL, params, tries=4 if len(chunk) > 12 else 6)
        return js if isinstance(js, list) else [js]
    except OpenMeteoError:
        if len(chunk) <= 12:
            raise
        half = len(chunk) // 2
        print(f"    Parto el lote de {len(chunk)} puntos en dos para aligerar la petición")
        return _fetch_chunk(chunk[:half]) + _fetch_chunk(chunk[half:])


def fetch_weather(cells: list[dict], batch: int = 50, pause: float = 20.0) -> dict:
    """Meteo de todos los puntos por lotes. Cada lote descargado se guarda en
    data/meteo_cache/<fecha>/, así un reintento el mismo día continúa donde se cortó."""
    import json
    from datetime import date
    from .config import DATA_DIR
    cache_root = DATA_DIR / "meteo_cache"
    cache = cache_root / date.today().isoformat()
    cache.mkdir(parents=True, exist_ok=True)
    for old in cache_root.iterdir():                 # borra cachés de días anteriores
        if old.is_dir() and old != cache:
            for f in old.glob("*.json"):
                f.unlink()
            old.rmdir()

    rows = []
    for b in range(0, len(cells), batch):
        chunk = cells[b:b + batch]
        f = cache / f"lote_{b:05d}_{len(chunk)}.json"
        if f.exists():
            rows += json.loads(f.read_text())
            print(f"  meteo {b + len(chunk)}/{len(cells)} (ya descargado)")
            continue
        part = _fetch_chunk(chunk)
        if len(part) != len(chunk):
            raise OpenMeteoError(f"Open-Meteo devolvió {len(part)} puntos de {len(chunk)}")
        f.write_text(json.dumps(part))
        rows += part
        print(f"  meteo {b + len(chunk)}/{len(cells)}")
        if b + batch < len(cells):
            time.sleep(pause)  # repartir la carga para no pasar del límite por minuto

    def arr(var):
        return np.array([[np.nan if v is None else v for v in r["daily"][var]] for r in rows], float)

    return {
        "dates": rows[0]["daily"]["time"],
        "elev": np.array([r.get("elevation", 0) for r in rows], float),
        "P": np.nan_to_num(arr("precipitation_sum")),
        "TMAX": arr("temperature_2m_max"),
        "TMIN": arr("temperature_2m_min"),
        "ET0": np.nan_to_num(arr("et0_fao_evapotranspiration")),
        "GUST": np.nan_to_num(arr("wind_gusts_10m_max")),
        "SM": np.array([_daily_sm(r) for r in rows], float),
    }


def _daily_sm(row: dict) -> list[float]:
    """Media diaria de la humedad 0-7 cm a partir de las capas horarias del modelo."""
    h = row.get("hourly") or {}
    n_days = len(row["daily"]["time"])
    if not all(k in h for k in SM_LAYERS):
        return [np.nan] * n_days
    layers = [np.array([np.nan if v is None else v for v in h[k]], float) * w for k, w in SM_LAYERS.items()]
    hourly = np.sum(layers, 0) / sum(SM_LAYERS.values())
    hourly = hourly[: n_days * 24].reshape(n_days, 24)
    with np.errstate(all="ignore"):
        return np.nanmean(hourly, 1).tolist()


def fetch_archive(lat: float, lon: float, start: str, end: str) -> dict:
    """Serie diaria histórica (ERA5 / ERA5-Land) para calibrar con hallazgos pasados."""
    params = {"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
              "daily": DAILY + ",soil_moisture_0_to_7cm_mean", "timezone": "Europe/Madrid"}
    js = _get_retry(ARCHIVE_URL, params)
    d = js["daily"]
    f = lambda k: np.array([np.nan if v is None else v for v in d.get(k, [None] * len(d["time"]))], float)
    return {"dates": d["time"], "elev": js.get("elevation", 0.0),
            "P": np.nan_to_num(f("precipitation_sum")), "TMAX": f("temperature_2m_max"), "TMIN": f("temperature_2m_min"),
            "ET0": np.nan_to_num(f("et0_fao_evapotranspiration")), "GUST": np.nan_to_num(f("wind_gusts_10m_max")),
            "SM": f("soil_moisture_0_to_7cm_mean")}


ELEV_URL = "https://api.open-meteo.com/v1/elevation"


def fine_elevation(cells: list[dict], step: float) -> np.ndarray:
    """Altitud del centro de cada celda de la malla fina (MDT 90 m). Se descarga una vez."""
    import json
    from .config import DATA_DIR
    cache = DATA_DIR / f"elev_{step}.json"
    if cache.exists():
        return np.array(json.loads(cache.read_text()), float)
    out = []
    for b in range(0, len(cells), 100):
        chunk = cells[b:b + 100]
        js = _get_retry(ELEV_URL, {
            "latitude": ",".join(str(c["lat"]) for c in chunk),
            "longitude": ",".join(str(c["lon"]) for c in chunk)})
        out += js["elevation"]
        time.sleep(1)
    cache.write_text(json.dumps(out))
    return np.array(out, float)
