"""Modelo heurístico de probabilidad de fructificación (0-100).

  índice = hábitat^0.6 · altitud · estación · lluvia · temperatura · humedad del suelo · helada · calor

Cada factor va de 0 a 1. Es un modelo interpretable pensado para calibrarse;
cuando tengas suficientes hallazgos propios (presencias/ausencias con fecha)
puedes sustituirlo por un modelo entrenado (GBM, MaxEnt) usando estos mismos factores.
"""
from datetime import date

import numpy as np


def trapezoid(x, a, b, c, d):
    x = np.asarray(x, float)
    up = np.clip((x - a) / max(b - a, 1e-6), 0, 1)
    down = np.clip((d - x) / max(d - c, 1e-6), 0, 1)
    return np.minimum(up, down)


def season_factor(season: list[float], day: date) -> float:
    """Interpola entre meses para que el calendario no dé saltos el día 1."""
    m = day.month - 1
    frac = (day.day - 15) / 30
    other = (m + (1 if frac > 0 else -1)) % 12
    return float((1 - abs(frac)) * season[m] + abs(frac) * season[other])


def score_day(sp: dict, prior: np.ndarray, wx: dict, d: int) -> tuple[np.ndarray, dict]:
    """Índice para el día con índice d dentro de las series meteorológicas."""
    P, TMAX, TMIN, ET0 = wx["P"], wx["TMAX"], wx["TMIN"], wx["ET0"]
    tmean = (TMAX + TMIN) / 2

    lag0, lag1 = sp["lag"]
    rain = P[:, d - lag1:d - lag0 + 1].sum(1)
    f_rain = np.clip(rain / sp["rain_mm"], 0, 1) ** 0.8

    t7 = np.nanmean(tmean[:, d - 6:d + 1], 1)
    lo, hi = sp["temp"]
    f_temp = trapezoid(t7, lo - 6, lo, hi, hi + 6)

    balance = (P - ET0)[:, d - 30:d + 1].sum(1)   # balance hídrico 30 días
    f_soil = np.clip(1 + balance / 120, 0.35, 1)

    f_frost = np.where(np.nanmin(TMIN[:, d - 4:d + 1], 1) < -1, sp["frost_tol"], 1.0)
    f_heat = np.where(np.nanmax(TMAX[:, d - 4:d + 1], 1) > 30, 0.5, 1.0)

    f_elev = trapezoid(wx["elev"], *sp["elev"])
    f_season = season_factor(sp["season"], date.fromisoformat(wx["dates"][d]))

    idx = 100 * prior ** 0.6 * f_elev * f_season * f_rain * f_temp * f_soil * f_frost * f_heat
    idx = np.nan_to_num(idx)
    extra = {"rain15": P[:, d - 14:d + 1].sum(1), "t7": t7}
    return np.clip(idx, 0, 100), extra
