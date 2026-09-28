"""Calibración del modelo con hallazgos reales.

Hallazgos: cualquier CSV o JSON en data/hallazgos/ con estas columnas
  species, date, lat, lon, found, count, source, notes
  - species: clave de config (boletus_edulis) o nombre científico (Boletus edulis)
  - date: AAAA-MM-DD      - found: 1 = encontrada, 0 = fui y no había (¡muy valioso!)
La web los exporta ya en este formato (Mis setales -> Descargar hallazgos).

Pasos:
  python -m pipeline.calibrate gbif       # añade citas fechadas de GBIF (data/hallazgos/gbif.csv)
  python -m pipeline.calibrate dataset    # cruza cada hallazgo con la meteo histórica (ERA5-Land)
  python -m pipeline.calibrate train      # entrena LightGBM y valida dejando fuera cada temporada
  python -m pipeline.calibrate all        # los tres seguidos
  (añade --demo para probar todo con datos sintéticos, sin red)

Como casi todas las citas son solo de presencia, para cada especie y día con hallazgos
se toman celdas al azar de la península ese mismo día como «fondo» (pseudo-ausencias).
Las ausencias reales que registres pesan más.
"""
import argparse
import hashlib
import json
import re
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .config import (BBOX, FINDINGS_DIR, GRID_STEP, MODEL_DIR, MODEL_MIN_GAIN, MODEL_MIN_PRESENCES,
                     SPECIES, WEATHER_STEP)
from .features import FEATURES, MIN_HISTORY, feature_matrix
from .grid import build_grid, nearest_index

COLUMNS = ["species", "date", "lat", "lon", "found", "count", "source", "notes"]
DATASET = MODEL_DIR / "dataset.csv"
CACHE = MODEL_DIR / "meteo_cache"
BACKGROUND_PER_DAY = 4       # celdas de fondo por especie y día con hallazgos
REAL_ABSENCE_WEIGHT = 3.0    # una ausencia registrada en campo vale por 3 de fondo
SPECIES_KEYS = list(SPECIES)


# ---------- hallazgos ----------
def species_key(name: str) -> str | None:
    n = str(name).strip().lower()
    for k, sp in SPECIES.items():
        names = {k, sp["name"].lower(), *[g.lower() for g in sp["gbif"]],
                 *[c.strip().lower() for c in sp["common"].split(",")]}
        if n in names:
            return k
    return None


def season_of(d: date) -> str:
    y = d.year if d.month >= 8 else d.year - 1
    return f"{y}-{str(y + 1)[2:]}"


def load_findings() -> pd.DataFrame:
    frames = []
    for f in sorted(FINDINGS_DIR.glob("*")):
        if f.suffix == ".csv":
            frames.append(pd.read_csv(f))
        elif f.suffix == ".json":
            frames.append(pd.DataFrame(json.loads(f.read_text())))
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.concat(frames, ignore_index=True)
    for c in COLUMNS:
        if c not in df:
            df[c] = None
    df["species"] = df["species"].map(species_key)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["found"] = pd.to_numeric(df["found"], errors="coerce").fillna(1).clip(0, 1).astype(int)
    df["source"] = df["source"].fillna("propio")
    df = df.dropna(subset=["species", "date", "lat", "lon"])
    df = df[df.lat.between(BBOX[1], BBOX[3]) & df.lon.between(BBOX[0], BBOX[2])]
    df = df[df.date >= date(2001, 1, 1)]
    df["_la"], df["_lo"] = df.lat.round(3), df.lon.round(3)
    df = df.drop_duplicates(subset=["species", "date", "_la", "_lo", "found"])
    return df[COLUMNS].reset_index(drop=True)


def import_gbif(year_from: int = 2010, cap: int = 4000):
    from .habitat import _get, GBIF, taxon_key
    rows = []
    for k, sp in SPECIES.items():
        n0 = len(rows)
        for name in sp["gbif"]:
            key = taxon_key(name)
            if not key:
                continue
            offset = 0
            while offset < cap:
                js = _get(f"{GBIF}/occurrence/search", {
                    "taxonKey": key, "country": ["ES", "PT", "AD"], "hasCoordinate": "true",
                    "hasGeospatialIssue": "false", "coordinateUncertaintyInMeters": "0,1000",
                    "year": f"{year_from},{date.today().year}", "limit": 300, "offset": offset})
                for o in js["results"]:
                    m = re.match(r"^(\d{4}-\d{2}-\d{2})", str(o.get("eventDate", "")))
                    if m:
                        rows.append({"species": k, "date": m.group(1), "lat": o["decimalLatitude"],
                                     "lon": o["decimalLongitude"], "found": 1, "count": "",
                                     "source": f"gbif:{o.get('datasetName') or o.get('institutionCode') or ''}"[:60],
                                     "notes": o.get("key")})
                if js.get("endOfRecords"):
                    break
                offset += 300
        print(f"· {sp['name']}: {len(rows) - n0} citas fechadas")
    FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=COLUMNS).to_csv(FINDINGS_DIR / "gbif.csv", index=False)
    print(f"OK -> data/hallazgos/gbif.csv ({len(rows)} citas)")


# ---------- meteo histórica ----------
class QuotaReached(Exception):
    pass


def _archive(lat: float, lon: float, start: date, end: date, demo: bool, budget: list) -> dict:
    key = hashlib.md5(f"{lat:.3f},{lon:.3f},{start},{end}".encode()).hexdigest()[:16]
    f = CACHE / f"{key}.json"
    if f.exists():
        js = json.loads(f.read_text())
        return {k: (np.array(v, float) if isinstance(v, list) and k != "dates" else v) for k, v in js.items()}
    if budget[0] <= 0:
        raise QuotaReached("límite de consultas de esta ejecución")
    budget[0] -= 1
    if demo:
        wx = _demo_archive(lat, lon, start, end)
    else:
        from .weather import fetch_archive
        wx = fetch_archive(lat, lon, start.isoformat(), end.isoformat())
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({k: (np.where(np.isnan(v), None, v).tolist() if isinstance(v, np.ndarray) else v)
                             for k, v in wx.items()}))
    return wx


def _demo_archive(lat, lon, start, end):
    n = (end - start).days + 1
    rng = np.random.default_rng(int(abs(lat * 1000 + lon * 7 + start.toordinal())))
    wet = np.clip((lat - 36) / 8 + (-lon) / 20, .1, 1.4)
    P = np.where(rng.random(n) < .14 * wet, rng.gamma(2, 9, n), 0) * wet
    base = 22 - .55 * (lat - 36) + 6 * np.cos(2 * np.pi * (np.arange(n) + start.timetuple().tm_yday - 200) / 365)
    TMAX = base + 5 + rng.normal(0, 2, n); TMIN = base - 5 + rng.normal(0, 2, n)
    return {"dates": [(start + timedelta(days=i)).isoformat() for i in range(n)], "elev": 600.0,
            "P": P, "TMAX": TMAX, "TMIN": TMIN, "ET0": np.clip((TMAX - 5) / 6, .5, 5),
            "GUST": rng.gamma(2.5, 10, n), "SM": np.clip(.12 + np.convolve(P, np.ones(7) / 90, "same"), .05, .45)}


# ---------- dataset ----------
def _static_layers(fine, demo: bool):
    """Hábitat SIN la capa de citas de GBIF (evita que el modelo se valide con sus propios datos)."""
    from .habitat import fine_habitat
    from .soil import load_ph
    coarse = build_grid(WEATHER_STEP)
    if demo:
        from .run_daily import demo_habitat
        hab = demo_habitat(fine)
    else:
        hab = fine_habitat(fine, nearest_index(coarse, fine))
    hab = {**hab, "occ": {}}
    return hab, load_ph(len(fine))


def build_dataset(demo: bool = False, seed: int = 7, max_queries: int = 2500) -> pd.DataFrame:
    from .habitat import habitat_prior
    from .model import score_day
    finds = load_findings()
    if finds.empty:
        raise SystemExit("No hay hallazgos en data/hallazgos/. Exporta los tuyos desde la web o ejecuta "
                         "`python -m pipeline.calibrate gbif`.")
    fine = build_grid(GRID_STEP)
    lookup = {(c["i"], c["j"]): k for k, c in enumerate(fine)}
    finds["cell"] = [lookup.get((int((a - BBOX[1]) // GRID_STEP), int((b - BBOX[0]) // GRID_STEP)))
                     for a, b in zip(finds.lat, finds.lon)]
    finds = finds.dropna(subset=["cell"]).astype({"cell": int})
    finds["weight"] = np.where(finds.found == 1, 1.0, REAL_ABSENCE_WEIGHT)

    rng = np.random.default_rng(seed)
    bg = []
    for (sp, d), g in finds[finds.found == 1].groupby(["species", "date"]):
        taken = set(g.cell)
        pool = rng.choice(len(fine), BACKGROUND_PER_DAY * 3, replace=False)
        for k in [k for k in pool if k not in taken][:BACKGROUND_PER_DAY]:
            bg.append({"species": sp, "date": d, "lat": fine[k]["lat"], "lon": fine[k]["lon"], "found": 0,
                       "source": "fondo", "cell": int(k), "weight": 1.0})
    rows = pd.concat([finds, pd.DataFrame(bg)], ignore_index=True)
    rows["season"] = rows.date.map(season_of)
    print(f"{int((rows.found == 1).sum())} presencias, {int(((rows.found == 0) & (rows.source != 'fondo')).sum())} "
          f"ausencias registradas, {len(bg)} celdas de fondo")

    hab, ph = _static_layers(fine, demo)
    priors = {}
    for k in SPECIES_KEYS:
        SPECIES[k]["_key"] = k
        priors[k] = habitat_prior(hab, SPECIES[k])

    groups = list(rows.groupby(["cell", "season"]))
    print(f"Meteo histórica: {len(groups)} consultas (se guardan en caché; si se corta, vuelve a ejecutarlo)")
    out, budget, pending = [], [max_queries], 0
    for n, ((cell, season), g) in enumerate(groups, 1):
        start, end = min(g.date) - timedelta(days=MIN_HISTORY + 1), max(g.date)
        try:
            wx = _archive(fine[cell]["lat"], fine[cell]["lon"], start, end, demo, budget)
        except QuotaReached:
            pending += 1
            continue
        except Exception as e:
            print(f"  parada en {n}/{len(groups)} ({e}). Lo descargado queda en caché: vuelve a ejecutarlo.")
            pending += len(groups) - n + 1
            break
        idx = {d: i for i, d in enumerate(wx["dates"])}
        W = {k: v[None, :] for k, v in wx.items() if isinstance(v, np.ndarray)}
        W["dates"] = wx["dates"]
        elev = np.array([wx["elev"] or 0.0])
        W["elev"] = elev
        for _, r in g.iterrows():
            d = idx.get(r.date.isoformat())
            if d is None or d < MIN_HISTORY:
                continue
            sp = SPECIES[r.species]
            heur, _ = score_day(sp, priors[r.species][[cell]], W, d, None if ph is None else ph[[cell]])
            hosts = {h: np.asarray(v)[[cell]] for h, v in hab["hosts"].items()}
            x = feature_matrix(W, d, elev, None if ph is None else ph[[cell]], hosts, heur)[0]
            out.append({"species": r.species, "date": r.date.isoformat(), "season": season, "found": int(r.found),
                        "source": r.source, "weight": r.weight, "cell": cell, **dict(zip(FEATURES, x))})
        if n % 50 == 0:
            print(f"  {n}/{len(groups)}")
    if pending:
        print(f"  Faltan {pending} consultas para completar el dataset (límite gratuito de Open-Meteo). "
              "Vuelve a ejecutar mañana: lo ya descargado no se repite.")
    ds = pd.DataFrame(out)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    ds.to_csv(DATASET, index=False)
    print(f"OK -> data/modelo/dataset.csv ({len(ds)} filas)")
    return ds


# ---------- entrenamiento y validación ----------
PARAMS = dict(objective="binary", learning_rate=0.05, n_estimators=300, num_leaves=15, min_child_samples=20,
              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1)


def _xy(df):
    X = df[FEATURES].copy()
    X["sp"] = pd.Categorical(df.species, categories=SPECIES_KEYS)
    return X, df.found.to_numpy(), df.weight.to_numpy()


def train():
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score
    df = pd.read_csv(DATASET)
    n_pos = int((df.found == 1).sum())
    if n_pos < 30:
        raise SystemExit(f"Solo hay {n_pos} presencias; hacen falta al menos 30 para entrenar algo útil.")

    oof = pd.Series(np.nan, index=df.index)
    seasons = []
    for s, test in df.groupby("season"):
        if (test.found == 1).sum() < 10 or test.found.nunique() < 2:
            continue
        tr = df.drop(test.index)
        if tr.found.nunique() < 2:
            continue
        X, y, w = _xy(tr)
        m = lgb.LGBMClassifier(**PARAMS).fit(X, y, sample_weight=w)
        oof[test.index] = m.predict_proba(_xy(test)[0])[:, 1]
        seasons.append({"season": s, "presencias": int((test.found == 1).sum()),
                        "auc_modelo": roc_auc_score(test.found, oof[test.index]),
                        "auc_heuristico": roc_auc_score(test.found, test.heur)})
    if not seasons:
        raise SystemExit("No hay ninguna temporada con 10 presencias para validar. Sigue registrando hallazgos.")

    sv = pd.DataFrame(seasons)
    wts = sv.presencias / sv.presencias.sum()
    auc_m, auc_h = float((sv.auc_modelo * wts).sum()), float((sv.auc_heuristico * wts).sum())
    ok = oof.notna()
    per_sp = []
    for k, g in df[ok].groupby("species"):
        if (g.found == 1).sum() >= 10 and g.found.nunique() == 2:
            per_sp.append({"especie": SPECIES[k]["name"], "presencias": int((g.found == 1).sum()),
                           "auc_modelo": roc_auc_score(g.found, oof[g.index]),
                           "auc_heuristico": roc_auc_score(g.found, g.heur)})

    X, y, w = _xy(df)
    final = lgb.LGBMClassifier(**PARAMS).fit(X, y, sample_weight=w)
    p_pos = final.predict_proba(X[y == 1])[:, 1]
    adopt = n_pos >= MODEL_MIN_PRESENCES and auc_m - auc_h >= MODEL_MIN_GAIN
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    final.booster_.save_model(str(MODEL_DIR / "lgbm.txt"))
    imp = sorted(zip(X.columns, final.booster_.feature_importance("gain")), key=lambda t: -t[1])
    meta = {"trained": date.today().isoformat(), "features": FEATURES, "species": SPECIES_KEYS,
            "presences": n_pos, "rows": len(df), "seasons": len(sv), "auc_model": round(auc_m, 3),
            "auc_heuristic": round(auc_h, 3), "p_ref": float(np.percentile(p_pos, 90)), "adopt": bool(adopt)}
    (MODEL_DIR / "meta.json").write_text(json.dumps(meta, indent=1))

    fmt = _md_table
    decision = ("**Se usa el modelo calibrado** en la previsión diaria (mezclado con el heurístico)." if adopt else
                f"**Se sigue usando el modelo heurístico.** Hacen falta ≥ {MODEL_MIN_PRESENCES} presencias "
                f"y una mejora de AUC ≥ {MODEL_MIN_GAIN} (ahora: {n_pos} presencias, mejora {auc_m - auc_h:+.3f}).")
    (MODEL_DIR / "informe.md").write_text(f"""# Informe de calibración ({meta['trained']})

{n_pos} presencias, {len(df)} filas en total, {len(sv)} temporadas validadas.

Validación dejando fuera una temporada completa cada vez (el modelo nunca ve la
temporada que predice). AUC: 0,5 = azar, 1 = perfecto.

| | AUC |
|---|---|
| Modelo calibrado (LightGBM) | {auc_m:.3f} |
| Modelo heurístico actual | {auc_h:.3f} |

{decision}

## Por temporada
{fmt(sv)}

## Por especie (predicciones fuera de muestra)
{fmt(pd.DataFrame(per_sp))}

## Variables más importantes
{fmt(pd.DataFrame(imp[:12], columns=["variable", "ganancia"]))}

Las citas de GBIF tienen sesgo de observación (más cerca de pueblos y caminos). Las
ausencias registradas en campo y los hallazgos propios con fecha exacta mejoran mucho el modelo.
""")
    print(f"AUC modelo {auc_m:.3f} vs heurístico {auc_h:.3f} · {'SE ADOPTA' if adopt else 'no se adopta todavía'}")
    print("OK -> data/modelo/informe.md")


def _md_table(d: pd.DataFrame) -> str:
    if not len(d):
        return "_sin datos suficientes_"
    cell = lambda v: f"{v:.3f}" if isinstance(v, float) else str(v)
    lines = ["| " + " | ".join(d.columns) + " |", "|" + "---|" * len(d.columns)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in d.itertuples(index=False)]
    return "\n".join(lines)


def load_model():
    """(booster, meta) si hay un modelo validado que mejora al heurístico; si no, None."""
    f, m = MODEL_DIR / "lgbm.txt", MODEL_DIR / "meta.json"
    if not (f.exists() and m.exists()):
        return None
    meta = json.loads(m.read_text())
    if not meta.get("adopt") or meta.get("features") != FEATURES:
        return None
    import lightgbm as lgb
    return lgb.Booster(model_file=str(f)), meta


def predict(booster, meta, X: np.ndarray, species: str) -> np.ndarray:
    df = pd.DataFrame(X, columns=FEATURES)
    df["sp"] = pd.Categorical([species] * len(df), categories=meta["species"])
    p = booster.predict(df)
    return np.clip(100 * p / meta["p_ref"], 0, 100)


def _demo_findings(n_per_species: int = 60, seed: int = 3):
    """Hallazgos sintéticos coherentes con el hábitat de demostración, en 4 temporadas."""
    from .habitat import habitat_prior
    from .run_daily import demo_habitat
    rng = np.random.default_rng(seed)
    fine = build_grid(GRID_STEP)
    hab = demo_habitat(fine)
    rows = []
    for k, sp in SPECIES.items():
        sp["_key"] = k
        pr = habitat_prior(hab, sp)
        months = [m + 1 for m, v in enumerate(sp["season"]) if v >= .7] or [10]
        cells = rng.choice(len(fine), n_per_species, p=pr ** 3 / (pr ** 3).sum())
        for c in cells:
            y = int(rng.choice([2021, 2022, 2023, 2024]))
            d = date(y, int(rng.choice(months)), int(rng.integers(1, 28)))
            rows.append({"species": k, "date": d.isoformat(), "lat": fine[c]["lat"], "lon": fine[c]["lon"],
                         "found": 1, "count": 1, "source": "demo", "notes": ""})
    FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=COLUMNS).to_csv(FINDINGS_DIR / "demo.csv", index=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["gbif", "dataset", "train", "all"])
    ap.add_argument("--demo", action="store_true", help="hallazgos y meteo sintéticos, sin red")
    ap.add_argument("--max-queries", type=int, default=2500, help="consultas nuevas a Open-Meteo por ejecución")
    a = ap.parse_args()
    if a.demo and a.step in ("gbif", "all"):
        _demo_findings()
    elif a.step in ("gbif", "all"):
        import_gbif()
    if a.step in ("dataset", "all"):
        build_dataset(a.demo, max_queries=a.max_queries)
    if a.step in ("train", "all"):
        train()
