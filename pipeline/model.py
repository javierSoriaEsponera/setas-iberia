"""Modelo heurístico de probabilidad de fructificación (0-100).

  índice = hábitat^0.6 · altitud · estación · pH · lluvia · temperatura · agua del suelo · helada · calor · viento

  agua del suelo = media geométrica del balance hídrico (lluvia − evaporación, 30 días)
                   y la humedad medida o modelizada de 0-7 cm (media 7 días), si la hay.

Cada factor va de 0 a 1. Es un modelo interpretable pensado para calibrarse;
cuando tengas suficientes hallazgos propios (presencias/ausencias con fecha)
puedes sustituirlo por un modelo entrenado (GBM, MaxEnt) usando estos mismos factores.
"""
from datetime import date

import numpy as np

from .config import WIND_GUST_KMH, WIND_PENALTY_PER_DAY


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


def ph_factor(ph: np.ndarray | None, rng: tuple[float, float], n: int) -> np.ndarray:
    """1 dentro del rango preferido; baja hasta 0,15 a 1,5 unidades fuera. Sin dato: neutro."""
    if ph is None:
        return np.ones(n)
    lo, hi = rng
    f = np.maximum(trapezoid(ph, lo - 1.5, lo, hi, hi + 1.5), 0.15)
    return np.where(np.isfinite(ph), f, 1.0)


def moisture_factor(sm7: np.ndarray) -> np.ndarray:
    """Humedad volumétrica 0-7 cm: seco < 0,10 m³/m³; óptimo desde ~0,24."""
    f = np.clip((sm7 - 0.10) / 0.14, 0.25, 1.0)
    return np.where(np.isfinite(sm7), f, np.nan)


def score_day(sp: dict, prior: np.ndarray, wx: dict, d: int, ph: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
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
    sm7 = np.full(len(P), np.nan)
    if "SM" in wx:
        with np.errstate(all="ignore"):
            sm7 = np.nanmean(wx["SM"][:, d - 6:d + 1], 1)
        f_sm = moisture_factor(sm7)
        f_soil = np.where(np.isfinite(f_sm), np.sqrt(f_soil * np.nan_to_num(f_sm, nan=1.0)), f_soil)

    f_frost = np.where(np.nanmin(TMIN[:, d - 4:d + 1], 1) < -1, sp["frost_tol"], 1.0)
    # Calor: por encima del umbral de la especie baja de forma gradual hasta 0,4 (6 ºC más)
    tmax5 = np.nanmax(TMAX[:, d - 4:d + 1], 1)
    lim = sp.get("tmax_limit", 30)
    f_heat = np.clip(1 - 0.6 * (tmax5 - lim) / 6, 0.4, 1.0)
    # Viento: cada día con rachas fuertes en la última semana reseca el suelo
    if "GUST" in wx:
        windy = (wx["GUST"][:, d - 6:d + 1] > WIND_GUST_KMH).sum(1)
        f_wind = np.clip(1 - WIND_PENALTY_PER_DAY * windy, 0.6, 1.0)
    else:
        f_wind = np.ones(len(P))

    f_elev = trapezoid(wx["elev"], *sp["elev"])
    f_season = season_factor(sp["season"], date.fromisoformat(wx["dates"][d]))

    f_ph = ph_factor(ph, sp.get("ph", (0, 14)), len(P))

    idx = 100 * prior ** 0.6 * f_elev * f_season * f_ph * f_rain * f_temp * f_soil * f_frost * f_heat * f_wind
    idx = np.nan_to_num(idx)
    extra = {"rain15": P[:, d - 14:d + 1].sum(1), "t7": t7, "sm7": sm7}
    return np.clip(idx, 0, 100), extra
