"""Variables (features) del modelo calibrado.

Se calculan con la MISMA función al entrenar (meteo histórica ERA5-Land del día de
cada hallazgo) y al predecir (previsión diaria), para que el modelo vea siempre lo mismo.
"""
from datetime import date

import numpy as np

from .config import HOST_GROUPS

GROUPS = list(HOST_GROUPS)
WEATHER = ["rain_0_7", "rain_7_14", "rain_14_21", "rain_21_35", "tmean_7", "tmin_5", "tmax_5",
           "balance_30", "sm_7", "gust_14", "doy_sin", "doy_cos"]
STATIC = ["elev", "ph"] + [f"host_{g}" for g in GROUPS]
FEATURES = WEATHER + STATIC + ["heur"]
MIN_HISTORY = 35   # días de serie necesarios antes del día a predecir


def weather_features(wx: dict, d: int) -> np.ndarray:
    P, TMAX, TMIN, ET0 = wx["P"], wx["TMAX"], wx["TMIN"], wx["ET0"]
    n = len(P)
    with np.errstate(all="ignore"):
        sm7 = np.nanmean(wx["SM"][:, d - 6:d + 1], 1) if "SM" in wx else np.full(n, np.nan)
        cols = [
            P[:, d - 6:d + 1].sum(1), P[:, d - 13:d - 6].sum(1), P[:, d - 20:d - 13].sum(1), P[:, d - 34:d - 20].sum(1),
            np.nanmean(((TMAX + TMIN) / 2)[:, d - 6:d + 1], 1),
            np.nanmin(TMIN[:, d - 4:d + 1], 1), np.nanmax(TMAX[:, d - 4:d + 1], 1),
            (P - ET0)[:, d - 30:d + 1].sum(1), sm7,
            (wx.get("GUST", np.zeros_like(P))[:, d - 13:d + 1] > 50).sum(1),
        ]
    doy = date.fromisoformat(wx["dates"][d]).timetuple().tm_yday
    cols += [np.full(n, np.sin(2 * np.pi * doy / 365.25)), np.full(n, np.cos(2 * np.pi * doy / 365.25))]
    return np.column_stack(cols)


def static_features(elev: np.ndarray, ph: np.ndarray | None, hosts: dict) -> np.ndarray:
    n = len(elev)
    ph = np.full(n, np.nan) if ph is None else ph
    return np.column_stack([elev, ph] + [np.asarray(hosts[g], float) for g in GROUPS])


def feature_matrix(wx: dict, d: int, elev, ph, hosts: dict, heur: np.ndarray) -> np.ndarray:
    return np.column_stack([weather_features(wx, d), static_features(elev, ph, hosts), heur])
