"""Malla regular de celdas sobre tierra firme (España peninsular, Portugal, Andorra, Baleares)."""
import json

import numpy as np
import requests
from shapely.geometry import Point, shape
from shapely.ops import unary_union
from shapely.prepared import prep

from .config import BBOX, DATA_DIR, GRID_STEP

NE_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
          "master/geojson/ne_50m_admin_0_countries.geojson")
COUNTRIES = {"Spain", "Portugal", "Andorra"}


def build_grid(step: float = GRID_STEP) -> list[dict]:
    cache = DATA_DIR / f"grid_{step}.json"
    if cache.exists():
        return json.loads(cache.read_text())

    gj = requests.get(NE_URL, timeout=120).json()
    polys = [shape(f["geometry"]) for f in gj["features"]
             if f["properties"].get("ADMIN") in COUNTRIES]
    land = prep(unary_union(polys))

    lon0, lat0, lon1, lat1 = BBOX
    cells = []
    for i, lat in enumerate(np.arange(lat0 + step / 2, lat1, step)):
        for j, lon in enumerate(np.arange(lon0 + step / 2, lon1, step)):
            if land.contains(Point(lon, lat)):
                cells.append({"i": i, "j": j, "lat": round(float(lat), 4), "lon": round(float(lon), 4)})

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(cells))
    return cells


def neighbours(cells: list[dict], radius: int = 1) -> list[list[int]]:
    """Índices de las celdas vecinas (incluida la propia) dentro de un radio en celdas."""
    idx = {(c["i"], c["j"]): k for k, c in enumerate(cells)}
    out = []
    for c in cells:
        n = [idx[(c["i"] + di, c["j"] + dj)]
             for di in range(-radius, radius + 1)
             for dj in range(-radius, radius + 1)
             if (c["i"] + di, c["j"] + dj) in idx]
        out.append(n)
    return out


def smooth(values: np.ndarray, nbrs: list[list[int]], self_weight: float = 0.6) -> np.ndarray:
    mean_n = np.array([values[n].mean() for n in nbrs])
    return self_weight * values + (1 - self_weight) * mean_n


def nearest_index(src: list[dict], dst: list[dict]) -> np.ndarray:
    """Para cada celda de dst, índice de la celda de src más cercana (en km aproximados)."""
    s_lat = np.array([c["lat"] for c in src]); s_lon = np.array([c["lon"] for c in src])
    out = np.empty(len(dst), int)
    for k, c in enumerate(dst):
        d = (s_lat - c["lat"]) ** 2 + ((s_lon - c["lon"]) * np.cos(np.radians(c["lat"]))) ** 2
        out[k] = int(np.argmin(d))
    return out
