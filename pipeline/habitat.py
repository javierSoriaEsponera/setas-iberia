"""Capa de hábitat.

- Mapa Forestal de España (pipeline/mfe.py): superficie real de cada grupo forestal. Fuente principal.
- GBIF: respaldo para Portugal y provincias sin MFE (géneros arbóreos por celda de 0,25º),
  y citas georreferenciadas de cada seta.

  python -m pipeline.habitat      # descarga lo de GBIF (una vez, 15-30 min)
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests

from .config import BBOX, DATA_DIR, GRID_STEP, HOST_GENERA, HOST_GROUPS, SPECIES, WEATHER_STEP
from .grid import build_grid, neighbours, smooth

GBIF = "https://api.gbif.org/v1"
SESSION = requests.Session()
GBIF_FILE = DATA_DIR / "habitat_gbif.json"
POINTS_FILE = DATA_DIR / "gbif_points.json"
MFE_FULL_FRACTION = 0.30  # 30 % de la celda cubierta por un grupo = hábitat óptimo


# ---------- GBIF ----------
def _get(url, params, tries=8, max_wait=900):
    fails, waited = 0, 0.0
    while True:
        try:
            r = SESSION.get(url, params=params, timeout=60)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                # límite de tasa: siempre se recupera, así que no cuenta como intento fallido
                wait = float(r.headers.get("Retry-After", 5)) + 1
                if waited + wait > max_wait:
                    raise RuntimeError(f"GBIF no responde (límite de tasa persistente): {url} {params}")
                time.sleep(wait); waited += wait
                continue
        except requests.RequestException:
            pass
        fails += 1
        if fails >= tries:
            raise RuntimeError(f"GBIF no responde: {url} {params}")
        time.sleep(min(30, 2 ** fails))


def taxon_key(name: str, **params) -> int | None:
    js = _get(f"{GBIF}/species/match", {"name": name, **params})
    return js.get("usageKey") if js.get("matchType") != "NONE" else None


def count_in_cell(key: int, lat: float, lon: float, half: float) -> int:
    try:
        js = _get(f"{GBIF}/occurrence/search", {
            "taxonKey": key, "hasCoordinate": "true", "hasGeospatialIssue": "false",
            "decimalLatitude": f"{lat - half},{lat + half}",
            "decimalLongitude": f"{lon - half},{lon + half}", "limit": 0,
        })
    except RuntimeError as e:
        print(f"  ! {e}")  # celda fallida tras reintentos: se cuenta como 0 en vez de abortar el proceso
        return 0
    return js.get("count", 0)


def species_points(key: int, cap: int = 6000) -> list[list[float]]:
    pts, offset = [], 0
    while offset < cap:
        js = _get(f"{GBIF}/occurrence/search", {
            "taxonKey": key, "country": ["ES", "PT", "AD"], "hasCoordinate": "true",
            "hasGeospatialIssue": "false", "limit": 300, "offset": offset,
        })
        for o in js["results"]:
            unc = o.get("coordinateUncertaintyInMeters")
            if unc is None or unc <= 5000:
                pts.append([round(o["decimalLatitude"], 4), round(o["decimalLongitude"], 4)])
        if js.get("endOfRecords"):
            break
        offset += 300
    return pts


def _normalise(counts: np.ndarray) -> np.ndarray:
    v = np.log1p(counts)
    p = np.percentile(v[v > 0], 95) if (v > 0).any() else 1
    return np.clip(v / p, 0, 1)


def build_gbif():
    cells = build_grid(WEATHER_STEP)
    nbrs = neighbours(cells, 1)
    out = {"step": WEATHER_STEP, "hosts": {}}
    for genus in HOST_GENERA:
        key = taxon_key(genus, kingdom="Plantae", rank="GENUS")  # sin esto, géneros ambiguos (p.ej. Pinus) no resuelven
        if key is None:
            raise RuntimeError(f"GBIF no reconoce el género {genus!r}")
        print(f"· {genus}: contando en {len(cells)} celdas…")
        with ThreadPoolExecutor(3) as ex:  # GBIF bloquea con 429 si se piden demasiadas celdas a la vez
            counts = list(ex.map(lambda c: count_in_cell(key, c["lat"], c["lon"], WEATHER_STEP / 2), cells))
        out["hosts"][genus] = np.round(smooth(_normalise(np.array(counts, float)), nbrs), 3).tolist()
    GBIF_FILE.write_text(json.dumps(out))

    points = {}
    for sp_key, sp in SPECIES.items():
        points[sp_key] = []
        for name in sp["gbif"]:
            key = taxon_key(name)
            if key:
                points[sp_key] += species_points(key)
        print(f"· {sp['name']}: {len(points[sp_key])} citas")
    POINTS_FILE.write_text(json.dumps(points))


# ---------- Combinación en la malla fina ----------
def occurrence_layer(points: list[list[float]], cells: list[dict], step: float, nbrs) -> np.ndarray:
    idx = {(c["i"], c["j"]): k for k, c in enumerate(cells)}
    counts = np.zeros(len(cells))
    for lat, lon in points:
        k = idx.get((int((lat - BBOX[1]) // step), int((lon - BBOX[0]) // step)))
        if k is not None:
            counts[k] += 1
    return smooth(_normalise(counts), nbrs, 0.4)


def fine_habitat(cells: list[dict], link: np.ndarray, step: float = GRID_STEP) -> dict:
    """Índice de hospedador (0-1) por grupo, bosque dominante y capa de citas en la malla fina."""
    mfe_file = DATA_DIR / f"mfe_{step}.json"
    mfe = json.loads(mfe_file.read_text()) if mfe_file.exists() else None
    gbif = json.loads(GBIF_FILE.read_text()) if GBIF_FILE.exists() else None
    if mfe is None and gbif is None:
        raise SystemExit("No hay capa de hábitat. Ejecuta python -m pipeline.habitat "
                         "(GBIF) y, si puedes, python -m pipeline.mfe (Mapa Forestal).")

    n = len(cells)
    cov = np.array(mfe["coverage"]) if mfe else np.zeros(n)
    hosts, dens = {}, {}
    for g, info in HOST_GROUPS.items():
        if mfe:
            dens[g] = np.array(mfe["frac"][g]) / np.maximum(cov, 1e-6)   # fracción dentro de la parte cubierta
            idx_mfe = np.clip(dens[g] / MFE_FULL_FRACTION, 0, 1) ** 0.7
        else:
            dens[g] = np.zeros(n); idx_mfe = np.zeros(n)
        genus, factor = info["gbif"]
        idx_gbif = np.array(gbif["hosts"][genus])[link] * factor if gbif else np.zeros(n)
        w = np.clip(cov, 0, 1)
        hosts[g] = w * idx_mfe + (1 - w) * idx_gbif

    groups = list(HOST_GROUPS)
    H = np.stack([hosts[g] for g in groups], 1)
    D = np.stack([dens[g] for g in groups], 1)
    dom = H.argmax(1)
    forest = [[int(dom[k]), int(round(100 * D[k, dom[k]])) if cov[k] > 0.5 else -1]
              if H[k, dom[k]] > 0.05 else [-1, -1] for k in range(n)]

    occ = {}
    if POINTS_FILE.exists():
        points = json.loads(POINTS_FILE.read_text())
        nbrs = neighbours(cells, 3)
        occ = {k: occurrence_layer(p, cells, step, nbrs) for k, p in points.items()}
    return {"hosts": hosts, "occ": occ, "forest": forest,
            "mfe_cells": int((cov > 0.5).sum()), "sources": mfe["sources"] if mfe else []}


def habitat_prior(hab: dict, sp: dict) -> np.ndarray:
    """Probabilidad a priori de hábitat (0-1) para una especie en cada celda."""
    host = np.max([w * hab["hosts"][g] for g, w in sp["hosts"].items()], axis=0)
    occ = hab["occ"].get(sp["_key"], np.zeros_like(host))
    return sp["floor"] + (1 - sp["floor"]) * np.clip(0.8 * host + 0.35 * occ, 0, 1)


if __name__ == "__main__":
    build_gbif()
