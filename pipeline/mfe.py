"""Hábitat forestal a partir del Mapa Forestal de España (MITECO, CC BY 4.0).

1. Descarga los .zip provinciales del MFE (MFE25 o MFE50) desde
   https://www.miteco.gob.es/es/cartografia-y-sig/ide/descargas/biodiversidad/mfe.html
   y déjalos, sin descomprimir, en data/mfe/
2. Comprueba que se leen bien los campos:   python -m pipeline.mfe --inspect data/mfe/León.zip
3. Procésalos todos:                         python -m pipeline.mfe

Resultado: data/mfe_<paso>.json con, para cada celda de la malla, la fracción de
superficie ocupada por cada grupo forestal (teniendo en cuenta la cabida cubierta
y la ocupación de cada especie en la tesela) y la cobertura del MFE en la celda.
Solo hace falta repetirlo si añades provincias o sale una versión nueva del MFE.
"""
import argparse
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import box

from .config import DATA_DIR, GRID_STEP, HOST_GROUPS, MFE_DIR
from .grid import build_grid

EQUAL_AREA = "EPSG:3035"  # ETRS89-LAEA, para medir superficies
GROUPS = list(HOST_GROUPS)
SPECIES_FIELDS = [("SP1", "O1"), ("SP2", "O2"), ("SP3", "O3")]
FCC_FIELDS = ["FCCARB", "FCCARB50", "FCC_ARB", "FCCARBOR", "FCCTOT", "FCC"]
TEXT_FIELDS = ["FORARB", "NOM_FORARB", "FORM_ARB", "FORMARB", "ESPECIE", "FORMACION",
               "TIPO_BOSQUE", "NOMBRE", "DEFINICION", "DEFINICIÓN"]
CODE_TO_GROUP = {code: g for g, info in HOST_GROUPS.items() for code in info["codes"]}
LATIN_RE = {g: re.compile("|".join(re.escape(n) for n in info["latin"]), re.I) for g, info in HOST_GROUPS.items()}
CACHE_DIR = MFE_DIR / "_cache"


def _col(df: pd.DataFrame, names: list[str]) -> str | None:
    upper = {c.upper(): c for c in df.columns}
    for n in names:
        if n.upper() in upper:
            return upper[n.upper()]
    return None


def _to_code(series: pd.Series) -> np.ndarray:
    return pd.to_numeric(series, errors="coerce").fillna(-1).astype(int).to_numpy()


def read_zip(path: Path) -> gpd.GeoDataFrame:
    """Lee la capa principal (la más grande) de un zip del MFE, con zips anidados incluidos."""
    tmp = Path(tempfile.mkdtemp(prefix="mfe_"))
    try:
        with zipfile.ZipFile(path) as z:
            z.extractall(tmp)
        for inner in list(tmp.rglob("*.zip")):
            with zipfile.ZipFile(inner) as z:
                z.extractall(inner.with_suffix(""))
        layers = list(tmp.rglob("*.shp")) + list(tmp.rglob("*.gpkg"))
        if not layers:
            raise SystemExit(f"{path.name}: no contiene ningún .shp ni .gpkg")
        main = max(layers, key=lambda f: f.stat().st_size + (f.with_suffix(".dbf").stat().st_size
                                                              if f.with_suffix(".dbf").exists() else 0))
        gdf = gpd.read_file(main, engine="pyogrio")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if gdf.crs is None:
        raise SystemExit(f"{path.name}: la capa no tiene sistema de referencia (.prj). No se puede procesar.")
    return gdf


def polygon_weights(gdf: gpd.GeoDataFrame) -> tuple[np.ndarray, str]:
    """Fracción de cada tesela ocupada por cada grupo forestal (n_teselas × n_grupos)."""
    n = len(gdf)
    W = np.zeros((n, len(GROUPS)))
    fcc_col = _col(gdf, FCC_FIELDS)
    fcc = (pd.to_numeric(gdf[fcc_col], errors="coerce").fillna(0).to_numpy() / 100
           if fcc_col else None)

    if _col(gdf, ["SP1"]):
        method = "códigos IFN (SP1-SP3 / O1-O3)"
        for sp_name, o_name in SPECIES_FIELDS:
            sp_col, o_col = _col(gdf, [sp_name]), _col(gdf, [o_name])
            if not sp_col:
                continue
            codes = _to_code(gdf[sp_col])
            if o_col:
                occ = pd.to_numeric(gdf[o_col], errors="coerce").fillna(0).to_numpy()
                occ = occ / (100 if occ.max() > 10 else 10)   # décimas (1-10) o porcentaje
            else:
                occ = np.where(codes > 0, 1.0 if sp_name == "SP1" else 0.0, 0.0)
            for gi, g in enumerate(GROUPS):
                W[:, gi] += occ * np.isin(codes, HOST_GROUPS[g]["codes"])
        if fcc is None:
            fcc = np.where(_to_code(gdf[_col(gdf, ["SP1"])]) > 0, 0.7, 0.0)
    else:
        text_col = _col(gdf, TEXT_FIELDS)
        if not text_col:
            raise SystemExit("No encuentro campos de especie (SP1…) ni de formación arbolada. "
                             f"Columnas disponibles: {list(gdf.columns)}")
        method = f"texto de la formación arbolada ({text_col})"
        text = gdf[text_col].fillna("").astype(str)
        for gi, g in enumerate(GROUPS):
            W[:, gi] = text.str.contains(LATIN_RE[g]).to_numpy()
        W = W / np.maximum(W.sum(1, keepdims=True), 1)
        if fcc is None:
            fcc = np.where(W.sum(1) > 0, 0.7, 0.0)

    W *= np.clip(fcc, 0, 1)[:, None]
    W /= np.maximum(W.sum(1, keepdims=True), 1)   # nunca más del 100 % de la tesela
    return W, method


def grid_polygons(cells: list[dict], step: float) -> np.ndarray:
    h = step / 2
    geoms = gpd.GeoSeries([box(c["lon"] - h, c["lat"] - h, c["lon"] + h, c["lat"] + h) for c in cells],
                          crs="EPSG:4326").to_crs(EQUAL_AREA)
    return geoms.values


def rasterise(gdf: gpd.GeoDataFrame, W: np.ndarray, grid: np.ndarray, chunk: int = 40000):
    """Suma superficie de cada grupo (m²) y superficie cubierta por el MFE en cada celda."""
    geoms = shapely.make_valid(gdf.to_crs(EQUAL_AREA).geometry.values)
    tree = shapely.STRtree(grid)
    area_g = np.zeros((len(grid), W.shape[1]))
    covered = np.zeros(len(grid))
    for a in range(0, len(geoms), chunk):
        part = geoms[a:a + chunk]
        src, dst = tree.query(part, predicate="intersects")
        if len(src) == 0:
            continue
        inter = shapely.area(shapely.intersection(part[src], grid[dst]))
        np.add.at(covered, dst, inter)
        np.add.at(area_g, dst, W[a + src] * inter[:, None])
    return area_g, covered


def inspect(path: Path):
    gdf = read_zip(path)
    print(f"{path.name}: {len(gdf)} teselas · CRS {gdf.crs.to_string()}")
    print("Columnas:", ", ".join(gdf.columns))
    for c in [_col(gdf, ["SP1"]), _col(gdf, TEXT_FIELDS), _col(gdf, FCC_FIELDS)]:
        if c:
            print(f"\nValores más frecuentes de {c}:")
            print(gdf[c].value_counts().head(15).to_string())
    W, method = polygon_weights(gdf)
    area = gdf.to_crs(EQUAL_AREA).area.to_numpy() / 1e6
    print(f"\nAsignación por {method}. Superficie arbolada por grupo (km²):")
    for gi, g in enumerate(GROUPS):
        print(f"  {HOST_GROUPS[g]['name']:<38} {np.sum(W[:, gi] * area):>9.0f}")
    print("Si un grupo sale a 0 y la provincia lo tiene, revisa los códigos en config.HOST_GROUPS.")


def build(step: float = GRID_STEP):
    zips = sorted(MFE_DIR.glob("*.zip"))
    if not zips:
        raise SystemExit(f"No hay ficheros .zip en {MFE_DIR}. Descárgalos del MITECO (ver cabecera).")
    cells = build_grid(step)
    grid = grid_polygons(cells, step)
    cell_area = shapely.area(grid)
    total_g = np.zeros((len(cells), len(GROUPS)))
    total_cov = np.zeros(len(cells))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for z in zips:
        cache = CACHE_DIR / f"{z.stem}_{step}_{int(z.stat().st_mtime)}.npz"
        if cache.exists():
            d = np.load(cache)
            area_g, covered = d["area_g"], d["covered"]
            print(f"· {z.name}: desde caché")
        else:
            gdf = read_zip(z)
            W, method = polygon_weights(gdf)
            area_g, covered = rasterise(gdf, W, grid)
            np.savez_compressed(cache, area_g=area_g, covered=covered)
            print(f"· {z.name}: {len(gdf)} teselas, {method}")
        total_g += area_g
        total_cov += covered

    out = {
        "step": step, "groups": GROUPS, "sources": [z.name for z in zips],
        "coverage": np.round(np.clip(total_cov / cell_area, 0, 1), 3).tolist(),
        "frac": {g: np.round(total_g[:, gi] / cell_area, 4).tolist() for gi, g in enumerate(GROUPS)},
    }
    target = DATA_DIR / f"mfe_{step}.json"
    target.write_text(json.dumps(out))
    n_cov = sum(c > 0.5 for c in out["coverage"])
    print(f"OK -> {target.relative_to(DATA_DIR.parent)}  ({n_cov} de {len(cells)} celdas cubiertas por el MFE)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inspect", type=Path, help="muestra campos y asignación de un zip sin procesar")
    ap.add_argument("--step", type=float, default=GRID_STEP)
    args = ap.parse_args()
    inspect(args.inspect) if args.inspect else build(args.step)
