"""Hábitat forestal a partir del Mapa Forestal de España (MITECO, CC BY 4.0).

1. Descarga los .zip provinciales del MFE (MFE25 o MFE50) desde
   https://www.miteco.gob.es/es/cartografia-y-sig/ide/descargas/biodiversidad/mfe.html
   y déjalos, sin descomprimir, en data/mfe/
2. Comprueba que se leen bien los campos:   python -m pipeline.mfe --inspect data/mfe/León.zip
3. Procésalos todos:                         python -m pipeline.mfe

En el MFE25 el campo FORARB suele ser un CÓDIGO numérico de formación arbolada. Su
significado está en el diccionario de datos oficial (mfe25_dd.xlsx), que el programa
descarga solo de MITECO la primera vez y guarda en data/mfe/. Si no puede descargarlo,
bájalo tú desde la página de descargas del MFE («Diccionario de datos») y déjalo en data/mfe/.
También puedes crear data/mfe/forarb.csv con dos columnas: codigo,nombre.
Para ver qué códigos ha entendido:            python -m pipeline.mfe --codes

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
SPECIES_FIELDS = [([f"SP{i}", f"ESP{i}", f"ESPE{i}", f"ESPECIE{i}", f"ESPECIE_{i}", f"SPP{i}"],
                   [f"O{i}", f"OCU{i}", f"OCUP{i}", f"OCUPA{i}", f"OCUPACION{i}"]) for i in (1, 2, 3)]
FCC_FIELDS = ["FCCARB", "FCCARB50", "FCC_ARB", "FCCARBOR", "FCCTOT", "FCC"]
TEXT_FIELDS = ["FORARB", "NOM_FORARB", "FORM_ARB", "FORMARB", "FORMARBOL", "FORM_ARBOL", "ESPECIE", "FORMACION",
               "FORMACIÓN", "TIPO_BOSQUE", "NOMBRE", "DEFINICION", "DEFINICIÓN", "NOM_FORM", "DESC_FORM"]
CODE_TO_GROUP = {code: g for g, info in HOST_GROUPS.items() for code in info["codes"]}
# Además del nombre científico completo, el MFE escribe a menudo abreviaturas («P. pinaster»,
# «Q. faginea») o nombres comunes («pino rodeno», «melojar»). Se reconocen todas las formas.
TEXT_PATTERNS = {
    "pino_montano": r"sylvestris|uncinata|\bnigra\b|laricio|salgare|pino (albar|silvestre|royo|negro\b)",
    "pino_negral":  r"pinaster|radiata|pino (negral|rodeno|resinero|gallego|mar[ií]timo|insigne|de monterrey)",
    "pino_medit":   r"halepensis|\bpinea\b|pino (carrasco|pi[ñn]onero|de alepo)",
    "abeto":        r"\babies\b|picea|abet(o|os|al|ales)\b|pinsap",
    "haya":         r"fagus|\bhay(a|as|edo|edos)\b",
    "castano":      r"castanea|casta[ñn](o|os|ar|ares)\b",
    "roble":        r"robur|petraea|pyrenaica|faginea|canariensis|humilis|pubescens|\brobl(e|es|edal|edales)\b|"
                    r"rebol|melo(jo|jos|jar|jares)\b|quejig|carball",
    "encina_alc":   r"\bilex\b|rotundifolia|\bsuber\b|encin(a|as|ar|ares)\b|alcornoc|\bcarrasca(s|l|les)?\b|dehesa",
}
TEXT_RE = {g: re.compile(TEXT_PATTERNS[g] + "|" + "|".join(re.escape(n) for n in HOST_GROUPS[g]["latin"]), re.I)
           for g in GROUPS}
CACHE_VERSION = 4   # súbelo si cambia la forma de asignar especies, para rehacer la caché
DICT_URL = "https://www.miteco.gob.es/content/dam/miteco/es/cartografia-y-sig/ide/descargas/mfe25_dd.xlsx"
# Cómo empiezan los nombres de las formaciones arboladas (sirve para localizar su tabla en el diccionario)
FORMATION_RE = re.compile(r"^\s*(pinar|hayed|encinar|robled|alcornocal|casta[ñn]ar|melojar|quejigar|abetal|pinsapar|"
                          r"bosque|mezcla|dehesa|chopera|eucaliptal|abedular|fresned|sabinar|acebuchal|olmed|avellan|"
                          r"tejed|repoblaci|plantaci|otras|arbolado|monte)", re.I)
_FORARB = None
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


def _is_code(v) -> bool:
    try:
        f = float(v)
        return f == int(f) and 0 <= f < 1000
    except (TypeError, ValueError):
        return False


def _parse_dictionary(path: Path) -> dict[int, str]:
    """Busca en el Excel del diccionario la tabla de formaciones arboladas (código -> nombre).
    El diccionario tiene varias tablas (especies, usos del suelo…); se elige la que tiene la
    cabecera FORARB / «formación arbolada» o, si no, la que más nombres de formaciones contiene."""
    sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=object)
    best, best_score = {}, 0.0
    for sheet, df in sheets.items():
        rows = df.values.tolist()
        blocks, cur = [], []
        for r, row in enumerate(rows):
            pair = None
            for c, v in enumerate(row):
                if _is_code(v):
                    txt = next((str(t).strip() for t in row[c + 1:] if isinstance(t, str) and len(t.strip()) > 3), None)
                    if txt:
                        pair = (int(float(v)), txt)
                    break
            if pair:
                cur.append((r, pair))
            elif cur:
                blocks.append(cur); cur = []
        if cur:
            blocks.append(cur)
        for b in blocks:
            if len(b) < 5:
                continue
            top = b[0][0]
            ctx = " ".join([str(sheet)] + [str(v) for row in rows[max(0, top - 6):top] for v in row if isinstance(v, str)]).lower()
            marker = "forarb" in ctx or ("formaci" in ctx and "arbol" in ctx)
            share = sum(bool(FORMATION_RE.match(t)) for _, (_, t) in b) / len(b)
            score = (10 if marker else 0) + share
            if score > best_score and (marker or share >= 0.3):
                best, best_score = {code: txt for _, (code, txt) in b}, score
    return best


FORARB_SHEET = "Formación arbolada"
FORARB_CODE_COL, FORARB_NAME_COL = 6, 4  # columnas "id_ForArb" y su nombre en esa hoja del diccionario MFE25


def _parse_forarb_sheet(path: Path) -> dict[int, str]:
    """Lee directamente la hoja «Formación arbolada» del diccionario del MFE25 (columna id_ForArb,
    que es el código que usan los shapefiles en el campo FORARB, y su nombre de formación)."""
    try:
        df = pd.read_excel(path, sheet_name=FORARB_SHEET, header=None, dtype=object)
    except ValueError:
        return {}
    codes = pd.to_numeric(df[FORARB_CODE_COL], errors="coerce")
    names = df[FORARB_NAME_COL].astype(str).str.strip()
    mask = codes.notna() & (names != "") & (names.str.lower() != "nan")
    return {int(c): n for c, n in zip(codes[mask], names[mask])}


def forarb_dictionary(download: bool = True) -> dict[int, str]:
    """Código de formación arbolada -> nombre (vacío si no hay diccionario disponible)."""
    global _FORARB
    if _FORARB is not None:
        return _FORARB
    MFE_DIR.mkdir(parents=True, exist_ok=True)
    csv = MFE_DIR / "forarb.csv"
    if csv.exists():
        df = pd.read_csv(csv, header=None, dtype=str)
        _FORARB = {int(float(a)): str(b) for a, b in zip(df[0], df[1]) if _is_code(a)}
        return _FORARB
    books = sorted(MFE_DIR.glob("*.xls*"))
    if not books and download:
        try:
            import requests
            r = requests.get(DICT_URL, timeout=120)
            r.raise_for_status()
            (MFE_DIR / "mfe25_dd.xlsx").write_bytes(r.content)
            books = [MFE_DIR / "mfe25_dd.xlsx"]
            print("· Diccionario de datos del MFE25 descargado de MITECO")
        except Exception as e:
            print(f"· No he podido descargar el diccionario del MFE25 ({e}).\n"
                  f"  Descárgalo de {DICT_URL} y déjalo en data/mfe/")
    _FORARB = {}
    for b in books:
        try:
            _FORARB = _parse_forarb_sheet(b) or _parse_dictionary(b)
        except Exception as e:
            print(f"· No he podido leer {b.name}: {e}")
        if _FORARB:
            print(f"· Diccionario de formaciones: {len(_FORARB)} códigos ({b.name})")
            break
    return _FORARB


def _decode(series: pd.Series) -> tuple[pd.Series, bool]:
    """Si la columna trae códigos numéricos de formación, los traduce a su nombre."""
    vals = series.dropna().astype(str).str.strip()
    vals = vals[vals != ""]
    if len(vals) == 0 or vals.map(_is_code).mean() < 0.5:
        return series.fillna("").astype(str), False
    d = forarb_dictionary()
    codes = _to_code(series)
    return pd.Series([d.get(c, "") for c in codes], index=series.index), True


GENERIC = [  # formaciones sin especie concreta: se reparten entre los grupos autóctonos que suelen formarlas
    (re.compile(r"con[ií]feras", re.I), ["pino_montano", "pino_negral", "pino_medit"]),
    (re.compile(r"frondosas", re.I), ["roble", "castano", "haya", "encina_alc"]),
]
EXOTIC = re.compile(r"al[oó]ctonas|exóticas|exoticas", re.I)


def _text_weights(text: pd.Series) -> np.ndarray:
    """Reparte a partes iguales entre los grupos cuyo nombre aparece en el texto."""
    t = text.fillna("").astype(str)
    W = np.array([[bool(TEXT_RE[g].search(x)) for g in GROUPS] for x in t], float).reshape(len(t), len(GROUPS))
    for k, x in enumerate(t):
        if W[k].sum() == 0 and x and not EXOTIC.search(x):
            for rx, groups in GENERIC:
                if rx.search(x):
                    for g in groups:
                        W[k, GROUPS.index(g)] = 1
    return W / np.maximum(W.sum(1, keepdims=True), 1)


def polygon_weights(gdf: gpd.GeoDataFrame) -> tuple[np.ndarray, np.ndarray, str]:
    """Fracción de cada tesela ocupada por cada grupo forestal (n × grupos) y la fracción
    arbolada que no se ha podido asignar a ningún grupo (n)."""
    n = len(gdf)
    W = np.zeros((n, len(GROUPS)))
    methods = []
    fcc_col = _col(gdf, FCC_FIELDS)
    fcc = pd.to_numeric(gdf[fcc_col], errors="coerce").fillna(0).to_numpy() / 100 if fcc_col else None
    has_species = np.zeros(n, bool)
    named = np.zeros(n, bool)   # teselas cuya especie o formación se conoce (sea o no hospedadora)

    # a) Campos de especie SP1-SP3 con su ocupación O1-O3: códigos IFN o nombres escritos
    for k, (sp_names, o_names) in enumerate(SPECIES_FIELDS):
        sp_col, o_col = _col(gdf, sp_names), _col(gdf, o_names)
        sp_name = "SP1" if k == 0 else f"SP{k + 1}"
        if not sp_col:
            continue
        raw = gdf[sp_col]
        codes = _to_code(raw)
        txt = raw.where(codes < 0, "").fillna("").astype(str)
        has_species |= (codes > 0) | (txt.str.strip().str.len() > 0).to_numpy()
        named |= (codes > 0) | (txt.str.strip().str.len() > 0).to_numpy()
        if o_col:
            occ = pd.to_numeric(gdf[o_col], errors="coerce").fillna(0).to_numpy()
            occ = occ / (100 if occ.max() > 10 else 10)   # décimas (1-10) o porcentaje
            occ = np.where(occ > 0, occ, 1.0 if sp_name == "SP1" else 0.0)
        else:
            occ = np.full(n, 1.0 if sp_name == "SP1" else 0.0)
        by_code = np.column_stack([np.isin(codes, HOST_GROUPS[g]["codes"]) for g in GROUPS]).astype(float)
        W += occ[:, None] * np.maximum(by_code, _text_weights(txt))
        methods.append(sp_col)

    # b) Texto de la formación arbolada: rellena las teselas que los campos de especie no resolvieron
    upper = {c.upper(): c for c in gdf.columns}
    for name in TEXT_FIELDS:
        text_col = upper.get(name.upper())
        if not text_col:
            continue
        text, coded = _decode(gdf[text_col])
        empty = W.sum(1) == 0
        tw = _text_weights(text)
        W[empty] = tw[empty]
        has_species |= (gdf[text_col].fillna("").astype(str).str.strip().str.len() > 0).to_numpy()
        named |= (text.str.strip().str.len() > 0).to_numpy()
        methods.append(f"{text_col} (códigos del diccionario)" if coded else text_col)
    if not methods:
        raise SystemExit("No encuentro campos de especie (SP1…) ni de formación arbolada. "
                         f"Columnas disponibles: {list(gdf.columns)}")

    if fcc is None:
        fcc = np.where(has_species, 0.7, 0.0)
    W /= np.maximum(W.sum(1, keepdims=True), 1)    # nunca más del 100 % de la tesela
    # Sin asignar = arbolado del que no sabemos la especie (se completará con GBIF). Las formaciones
    # conocidas que no alojan estas setas (eucaliptales, riberas…) cuentan como reconocidas.
    unassigned = np.where((fcc > 0) & (W.sum(1) == 0) & ~named, 1.0, 0.0) * np.clip(fcc, 0, 1)
    W *= np.clip(fcc, 0, 1)[:, None]
    return W, unassigned, "campos " + ", ".join(methods)


def _diagnose(gdf, W, unassigned, name: str):
    area = gdf.to_crs(EQUAL_AREA).area.to_numpy() / 1e6
    ok_km2, bad_km2 = float((W.sum(1) * area).sum()), float((unassigned * area).sum())
    share = ok_km2 / max(ok_km2 + bad_km2, 1e-9)
    print(f"  arbolado hospedador {ok_km2:,.0f} km², especie desconocida {bad_km2:,.0f} km² ({share:.0%} reconocido)")
    if share < 0.8 and bad_km2 > 1:
        cols = [c for c in [_col(gdf, SPECIES_FIELDS[0][0]), _col(gdf, TEXT_FIELDS)] if c]
        mask = unassigned > 0
        d = forarb_dictionary(download=False)
        for c in cols:
            top = gdf.loc[mask, c].astype(str).value_counts().head(8)
            print(f"  AVISO {name}: valores de {c} sin reconocer (los más frecuentes):")
            for v, k in top.items():
                label = f"{v} = {d.get(int(float(v)), 'sin nombre en el diccionario')}" if _is_code(v) and d else repr(v)
                print(f"      {label[:70]:<72} {k} teselas")
        print("  Pégame estas líneas y lo añado a los códigos. Mientras, esas zonas usan GBIF.")


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
    for c in [_col(gdf, SPECIES_FIELDS[0][0]), _col(gdf, TEXT_FIELDS), _col(gdf, FCC_FIELDS)]:
        if c:
            print(f"\nValores más frecuentes de {c}:")
            print(gdf[c].value_counts().head(15).to_string())
    W, unassigned, method = polygon_weights(gdf)
    area = gdf.to_crs(EQUAL_AREA).area.to_numpy() / 1e6
    print(f"\n arbolada por grupo (km²):")
    for gi, g in enumerate(GROUPS):
        print(f"  {HOST_GROUPS[g]['name']:<38} {np.sum(W[:, gi] * area):>9.0f}")
    _diagnose(gdf, W, unassigned, path.name)


def build(step: float = GRID_STEP):
    zips = sorted(MFE_DIR.glob("*.zip"))
    if not zips:
        raise SystemExit(f"No hay ficheros .zip en {MFE_DIR}. Descárgalos del MITECO (ver cabecera).")
    cells = build_grid(step)
    grid = grid_polygons(cells, step)
    cell_area = shapely.area(grid)
    total_g = np.zeros((len(cells), len(GROUPS) + 1))   # última columna: arbolado sin asignar
    total_cov = np.zeros(len(cells))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for z in zips:
        cache = CACHE_DIR / f"{z.stem}_{step}_{int(z.stat().st_mtime)}_v{CACHE_VERSION}.npz"
        if cache.exists():
            d = np.load(cache)
            area_g, covered = d["area_g"], d["covered"]
            print(f"· {z.name}: desde caché")
        else:
            gdf = read_zip(z)
            W, unassigned, method = polygon_weights(gdf)
            print(f"· {z.name}: {len(gdf)} teselas, {method}")
            _diagnose(gdf, W, unassigned, z.name)
            area_g, covered = rasterise(gdf, np.column_stack([W, unassigned]), grid)
            np.savez_compressed(cache, area_g=area_g, covered=covered)
        total_g += area_g
        total_cov += covered

    out = {
        "step": step, "groups": GROUPS, "sources": [z.name for z in zips],
        "coverage": np.round(np.clip(total_cov / cell_area, 0, 1), 3).tolist(),
        "frac": {g: np.round(total_g[:, gi] / cell_area, 4).tolist() for gi, g in enumerate(GROUPS)},
        "unassigned": np.round(total_g[:, -1] / cell_area, 4).tolist(),
    }
    target = DATA_DIR / f"mfe_{step}.json"
    target.write_text(json.dumps(out))
    n_cov = sum(c > 0.5 for c in out["coverage"])
    print(f"OK -> {target.relative_to(DATA_DIR.parent)}  ({n_cov} de {len(cells)} celdas cubiertas por el MFE)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inspect", type=Path, help="muestra campos y asignación de un zip sin procesar")
    ap.add_argument("--codes", action="store_true", help="muestra los códigos de formación y a qué bosque se asignan")
    ap.add_argument("--step", type=float, default=GRID_STEP)
    args = ap.parse_args()
    if args.codes:
        d = forarb_dictionary()
        if not d:
            raise SystemExit("No hay diccionario de formaciones (ver cabecera de este fichero).")
        for code, name in sorted(d.items()):
            w = _text_weights(pd.Series([name]))[0]
            groups = ", ".join(HOST_GROUPS[g]["name"] for g, v in zip(GROUPS, w) if v > 0) or "— (no es hospedador)"
            print(f"{code:>4}  {name[:62]:<64} -> {groups}")
    elif args.inspect:
        inspect(args.inspect)
    else:
        build(args.step)
