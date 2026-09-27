"""Meteorología diaria (últimos 35 días + previsión 7 días) de Open-Meteo.

Open-Meteo combina modelos de AEMET (HARMONIE-AROME), ECMWF, DWD, Météo-France…
y devuelve también la altitud de cada punto (MDT de 90 m).
Plan gratuito: uso no comercial y ~10.000 llamadas/día. Si comercializas la app,
contrata el plan de pago o usa directamente AEMET OpenData.
"""
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import requests

from .config import FORECAST_DAYS, PAST_DAYS

URL = "https://api.open-meteo.com/v1/forecast"
DAILY = "precipitation_sum,temperature_2m_max,temperature_2m_min,et0_fao_evapotranspiration,wind_gusts_10m_max"


def _wait_for(reason: str) -> float:
    """Segundos a esperar según el mensaje de límite de Open-Meteo (minuto/hora/día)."""
    reason = (reason or "").lower()
    if "hour" in reason:
        now = datetime.now(timezone.utc)
        return (60 - now.minute) * 60 - now.second + 30  # hasta la siguiente hora + margen
    if "day" in reason:
        raise RuntimeError(f"Open-Meteo: {reason}. Prueba mañana o usa un plan de pago.")
    return 65  # límite por minuto


def _get_retry(url, params, tries=4, timeout=120):
    for attempt in range(tries):
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r
        try:
            reason = r.json().get("reason", "")
        except ValueError:
            reason = ""
        wait = _wait_for(reason)
        print(f"  · Open-Meteo: {reason or r.status_code} -> espero {int(wait)} s")
        time.sleep(wait)
    r.raise_for_status()
    return r


def fetch_weather(cells: list[dict], batch: int = 100, pause: float = 45.0) -> dict:
    rows = []
    for b in range(0, len(cells), batch):
        chunk = cells[b:b + batch]
        params = {
            "latitude": ",".join(str(c["lat"]) for c in chunk),
            "longitude": ",".join(str(c["lon"]) for c in chunk),
            "daily": DAILY, "past_days": PAST_DAYS, "forecast_days": FORECAST_DAYS,
            "timezone": "Europe/Madrid",
        }
        r = _get_retry(URL, params)
        js = r.json()
        rows += js if isinstance(js, list) else [js]
        print(f"  meteo {min(b + batch, len(cells))}/{len(cells)}")
        if b + batch < len(cells):
            time.sleep(pause)  # repartir la carga para no pasar de 600 llamadas/min

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
    }


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
        params = {"latitude": ",".join(str(c["lat"]) for c in chunk),
                  "longitude": ",".join(str(c["lon"]) for c in chunk)}
        r = _get_retry(ELEV_URL, params, timeout=60)
        out += r.json()["elevation"]
        print(f"  elevación {min(b + 100, len(cells))}/{len(cells)}")
        time.sleep(3)
    cache.write_text(json.dumps(out))
    return np.array(out, float)
