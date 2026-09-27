"""Ejecución diaria: meteo + hábitat -> docs/data/latest.json (lo lee el mapa).

  python -m pipeline.run_daily          # datos reales
  python -m pipeline.run_daily --demo   # datos sintéticos para probar la web sin red
"""
import argparse
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np

from .config import (FORECAST_DAYS, GRID_STEP, HOST_GROUPS, LAPSE_RATE, PAST_DAYS,
                     PUBLIC_DATA_DIR, SPECIES, WEATHER_STEP)
from .grid import build_grid, nearest_index
from .habitat import fine_habitat, habitat_prior
from .model import score_day

GROUPS = list(HOST_GROUPS)


# ---------- datos sintéticos (modo demo) ----------
def _blobs(cells, spec):
    lat = np.array([c["lat"] for c in cells]); lon = np.array([c["lon"] for c in cells])
    g = lambda la, lo, s: np.exp(-((lat - la) ** 2 + (lon - lo) ** 2) / (2 * s ** 2))
    return {k: np.clip(sum(g(*b) for b in blobs), 0, 1) for k, blobs in spec.items()}


def demo_habitat(cells):
    hosts = _blobs(cells, {
        "pino_montano": [(41.9, -3.1, .7), (40.8, -4.0, .4), (42.5, 1.2, .5), (40.3, -1.8, .5)],
        "pino_negral": [(42.3, -8.2, .7), (41.4, -4.4, .5), (39.5, -8.2, .6)],
        "pino_medit": [(40.0, -0.5, .8), (37.8, -2.7, .6), (41.6, 1.3, .5), (39.6, 2.9, .3)],
        "abeto": [(42.7, 0.8, .3), (36.7, -5.1, .15)],
        "haya": [(43.0, -3.6, .6), (42.9, -1.3, .45), (42.1, 2.4, .2)],
        "castano": [(42.6, -7.3, .6), (40.3, -6.3, .3), (36.6, -5.2, .25)],
        "roble": [(42.5, -6.0, .9), (41.0, -5.9, .6), (40.8, -3.8, .4), (41.6, -8.2, .5)],
        "encina_alc": [(39.1, -6.2, 1.2), (38.3, -4.6, .8), (41.8, 2.6, .35)],
    })
    occ = {k: np.clip(np.max([w * hosts[g] for g, w in sp["hosts"].items()], 0) * .8, 0, 1)
           for k, sp in SPECIES.items()}
    H = np.stack([hosts[g] for g in GROUPS], 1); dom = H.argmax(1)
    forest = [[int(dom[k]), int(40 * H[k, dom[k]])] if H[k, dom[k]] > .05 else [-1, -1] for k in range(len(cells))]
    return {"hosts": hosts, "occ": occ, "forest": forest, "mfe_cells": len(cells), "sources": ["demo"]}


def demo_weather(cells, today: date):
    rng = np.random.default_rng(today.toordinal())
    lat = np.array([c["lat"] for c in cells]); lon = np.array([c["lon"] for c in cells])
    n, days = len(cells), PAST_DAYS + FORECAST_DAYS
    wet = np.clip((lat - 36) / 8 + (-lon) / 20, 0.1, 1.4)
    storms = rng.random((n, days)) < 0.12 * wet[:, None]
    P = np.where(storms, rng.gamma(2, 9, (n, days)), 0) * wet[:, None]
    elev = demo_elev(cells)
    base = 24 - 0.55 * (lat - 36) - elev / 180
    trend = np.linspace(2, -2, days)
    TMAX = base[:, None] + 5 + trend + rng.normal(0, 1.5, (n, days))
    TMIN = base[:, None] - 5 + trend + rng.normal(0, 1.5, (n, days))
    dates = [(today - timedelta(days=PAST_DAYS) + timedelta(days=k)).isoformat() for k in range(days)]
    GUST = rng.gamma(2.5, 10, (n, days)) * (1 + 0.3 * (lat[:, None] > 42))
    return {"dates": dates, "elev": elev, "P": P, "TMAX": TMAX, "TMIN": TMIN,
            "ET0": np.clip((TMAX - 5) / 6, .5, 5), "GUST": GUST}


def demo_elev(cells):
    lat = np.array([c["lat"] for c in cells]); lon = np.array([c["lon"] for c in cells])
    return np.clip(700 + 500 * np.sin(lat * 1.3) * np.cos(lon * .9) + 250 * np.sin(lat * 7) * np.cos(lon * 6), 0, 2400)


# ---------- meteo de la malla gruesa a la fina ----------
def downscale(wx: dict, link: np.ndarray, elev_fine: np.ndarray) -> dict:
    """Copia la meteo de la celda de 0,25º más cercana y corrige la temperatura por altitud."""
    dz = (LAPSE_RATE * (elev_fine - wx["elev"][link]))[:, None]
    return {"dates": wx["dates"], "elev": elev_fine, "P": wx["P"][link], "ET0": wx["ET0"][link],
            "GUST": wx["GUST"][link], "TMAX": wx["TMAX"][link] + dz, "TMIN": wx["TMIN"][link] + dz}


def climate_windows(wx: dict, t0: int, windows=(7, 14, 21, 30)) -> dict:
    """Agregados de los últimos N días para las pestañas Exploración y Clima."""
    out = {"windows": list(windows), "rain": {}, "tmin": {}, "tmax": {}, "balance": {}, "gust": {}}
    for w in windows:
        sl = slice(t0 - w + 1, t0 + 1)
        out["rain"][w] = np.round(wx["P"][:, sl].sum(1)).astype(int).tolist()
        out["tmin"][w] = np.round(np.nanmean(wx["TMIN"][:, sl], 1), 1).tolist()
        out["tmax"][w] = np.round(np.nanmean(wx["TMAX"][:, sl], 1), 1).tolist()
        out["balance"][w] = np.round((wx["P"] - wx["ET0"])[:, sl].sum(1)).astype(int).tolist()
        out["gust"][w] = (wx["GUST"][:, sl] > 50).sum(1).astype(int).tolist()
    return out


def species_catalog() -> dict:
    """Fichas de la pestaña Setas, generadas desde los mismos parámetros del modelo."""
    from .species_info import INFO
    cat = {}
    for k, sp in SPECIES.items():
        hosts = sorted(sp["hosts"].items(), key=lambda kv: -kv[1])
        cat[k] = {
            "name": sp["name"], "common": sp["common"], "photo": sp["gbif"][0],
            "season": sp["season"], "elev": sp["elev"], "temp": sp["temp"],
            "rain_mm": sp["rain_mm"], "lag": sp["lag"],
            "hosts": [[HOST_GROUPS[g]["name"], w] for g, w in hosts],
            **INFO.get(k, {"desc": "", "confusion": ""}),
        }
    return cat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()

    fine, coarse = build_grid(GRID_STEP), build_grid(WEATHER_STEP)
    link = nearest_index(coarse, fine)
    today = date.today()
    print(f"{len(fine)} celdas de mapa ({GRID_STEP}º) · {len(coarse)} puntos meteo ({WEATHER_STEP}º)")

    if args.demo:
        hab, wx_c, elev_f = demo_habitat(fine), demo_weather(coarse, today), demo_elev(fine)
    else:
        from .weather import fetch_weather, fine_elevation
        hab = fine_habitat(fine, link)
        elev_f = fine_elevation(fine, GRID_STEP)
        wx_c = fetch_weather(coarse)
    print(f"Hábitat: {hab['mfe_cells']} celdas con Mapa Forestal, resto con GBIF")
    wx = downscale(wx_c, link, elev_f)

    t0 = PAST_DAYS  # índice de hoy en las series
    out_days = list(range(t0, t0 + FORECAST_DAYS))
    result = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "demo": args.demo, "step": GRID_STEP,
        "dates": [wx["dates"][d] for d in out_days],
        "cells": [[c["lat"], c["lon"], int(e)] for c, e in zip(fine, elev_f)],
        "groups": [HOST_GROUPS[g]["name"] for g in GROUPS],
        "forest": hab["forest"],
        "habitat_sources": hab["sources"],
        "species": {}, "meteo": {"rain15": [], "t7": []},
        "group_keys": GROUPS,
        "flora": {g: np.round(100 * np.asarray(hab["hosts"][g])).astype(int).tolist() for g in GROUPS},
        "climate": climate_windows(wx, t0),
    }

    first = True
    for k, sp in SPECIES.items():
        sp["_key"] = k
        prior = habitat_prior(hab, sp)
        days = []
        for d in out_days:
            s, extra = score_day(sp, prior, wx, d)
            days.append(np.round(s).astype(int).tolist())
            if first:
                result["meteo"]["rain15"].append(np.round(extra["rain15"]).astype(int).tolist())
                result["meteo"]["t7"].append(np.round(extra["t7"], 1).tolist())
        first = False
        result["species"][k] = {"name": sp["name"], "common": sp["common"], "days": days}
        print(f"  {sp['name']:<36} máx hoy {max(days[0]):>3}  celdas >50: {sum(v > 50 for v in days[0])}")

    PUBLIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DATA_DIR / "latest.json").write_text(json.dumps(result, separators=(",", ":")))
    (PUBLIC_DATA_DIR / "species.json").write_text(json.dumps(species_catalog(), ensure_ascii=False, indent=1))
    print("OK -> docs/data/latest.json")


if __name__ == "__main__":
    main()
