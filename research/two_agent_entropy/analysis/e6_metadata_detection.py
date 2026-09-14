#!/usr/bin/env python3
"""E6 — detección por metadatos, sin logprobs (análisis offline del Exp1).

Rasgos por corrida en la ventana post (fracciones de acción, longitud media de escritura,
turno de la primera entrega, entradas devueltas por lectura, latencia, descifrados
fallidos) y regresión logística con validación dejando-una-corrida-fuera; AUC fuera de
muestra con IC 95 % por bootstrap de corridas. Cuatro detectores: todos los rasgos, sin
volumen, sólo turno de entrega, y sin volumen ni latencia (el más honesto: la latencia
crece con el prompt y actúa como volumen encubierto). Incluye ventana deslizante de 3
turnos y retardo de alarma con falsa alarma controlada por corrida.

Entrada : --root <dir>/full ; --exp1-stats <dir con J_roc.csv>
          (opcional, para la comparación con la entropía del Exp1)
Salidas : <out>/E6_rasgos_corrida.csv, E6_auc.csv

La ventana deslizante, el retardo de alarma y las dos figuras del informe se calcularon en
celdas aparte a partir de `E6_rasgos_corrida.csv` y no los escribe este script.
"""

import argparse as _argparse
import os as _os

_ap = _argparse.ArgumentParser(description=__doc__.splitlines()[0])
_ap.add_argument("--root", default="full",
                 help="directorio con <modelo>/<condicion>/s<NNN>/ (normalmente <exp>/full)")
_ap.add_argument("--out", default="out", help="directorio de salida")
_ap.add_argument("--exp1-stats", default=None,
                 help="directorio stats/ de entropy_analysis.py, para comparar con la entropía")
_args = _ap.parse_args()
ROOT = _args.root
OUT = _args.out
EXP1_STATS = _args.exp1_stats
_os.makedirs(OUT, exist_ok=True)

import json, glob, os, re, difflib, math, time
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import roc_auc_score, roc_curve

# Estilo de figura local (mismas reglas que analysis/figuras_informe.py).
META_GREY = "#888888"


def apply_figure_style(*, frame="open", font=None, sizes=(8, 7, 6), grid=False):
    import matplotlib as mpl
    if frame not in ("open", "boxed", "none"):
        raise ValueError(f"frame must be 'open'|'boxed'|'none', got {frame!r}")
    try:
        import os, sys, glob, matplotlib.font_manager as fm
        fdir = os.path.join(os.environ.get("CONDA_PREFIX") or sys.prefix, "fonts")
        if os.path.isdir(fdir):
            known = {f.fname for f in fm.fontManager.ttflist}
            for f in glob.glob(os.path.join(fdir, "*.ttf")):
                if f not in known:
                    fm.fontManager.addfont(f)
    except Exception:
        pass
    base, secondary, tick = sizes
    boxed = (frame == "boxed")
    rc = {
        "font.family": "sans-serif",
        "font.size": base,
        "axes.labelsize": base,
        "axes.titlesize": base,
        "legend.fontsize": secondary,
        "xtick.labelsize": tick,
        "ytick.labelsize": tick,
        "axes.linewidth": 0.6,
        "xtick.direction": "out", "ytick.direction": "out",
        "xtick.major.size": 3, "ytick.major.size": 3,
        "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "axes.spines.top": boxed, "axes.spines.right": boxed,
        "axes.spines.left": frame != "none", "axes.spines.bottom": frame != "none",
        "axes.grid": bool(grid),
        "legend.frameon": False,
        "figure.dpi": 200,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "axes.titleweight": "normal",
        "axes.titlelocation": "left",
        "axes.labelweight": "normal",
        "lines.linewidth": 1.2,
        "patch.linewidth": 0.6,
        "pdf.fonttype": 42, "ps.fonttype": 42,
    }
    if font:
        rc["font.sans-serif"] = [font, "DejaVu Sans"]
    mpl.rcParams.update(rc)


import matplotlib as mpl, matplotlib.pyplot as plt
os.makedirs(OUT, exist_ok=True)
apply_figure_style()


# load all turns rows (all 3 models) into a flat frame
trows = []
for rd in sorted(glob.glob(f"{ROOT}/*/*/s*")):
    model, cond, s = rd.split("/")[-3:]; seed = int(s[1:]); run_id = f"{model}__{cond}__s{seed:03d}"
    for l in open(f"{rd}/turns.jsonl"):
        r = json.loads(l)
        body = r.get("completion_text") or ""
        wlen = len(body.split(":", 1)[1].strip()) if r["action"] == "write_log" and ":" in body else np.nan
        nret = (len(r.get("returned_real_seqs") or []) + len(r.get("returned_placebo_seqs") or [])) if r["action"] == "read_log" else np.nan
        trows.append(dict(model=model, condition=cond, seed=seed, run_id=run_id, turn=r["turn"], agent=r["agent"], action=r["action"],
                          write_len=wlen, n_returned=nret, latency=r.get("latency_s"), decrypt_fail=(r["action"] == "decrypt" and r.get("decrypt_ok") is False),
                          done=(r["action"] == "done")))
T = pd.DataFrame(trows)

def feats(df):
    act = df[df.action != "done"]
    n = max(len(act), 1)
    fs = df[df.action == "submit"]
    return pd.Series(dict(
        frac_read=(act.action == "read_log").sum() / n,
        frac_write=(act.action == "write_log").sum() / n,
        frac_decrypt=(act.action == "decrypt").sum() / n,
        mean_write_len=act.write_len.mean() if act.write_len.notna().any() else 0.0,
        first_submit_turn=fs.turn.min() if len(fs) else df.turn.max() + 1,
        mean_n_returned=act.n_returned.mean() if act.n_returned.notna().any() else 0.0,
        mean_latency=act.latency.mean() if len(act) else 0.0,
        n_decrypt_failed=act.decrypt_fail.sum(),
        n_active_calls=len(act)))

W = T[(T.turn >= 8) & (T.turn <= 20)]
F = W.groupby(["model", "condition", "seed", "run_id"]).apply(feats).reset_index()
F["first_submit_turn"] = F.first_submit_turn.clip(upper=21)
F.to_csv(f"{OUT}/E6_rasgos_corrida.csv", index=False)

DET = {"(i) todos los rasgos": ["frac_read", "frac_write", "frac_decrypt", "mean_write_len", "first_submit_turn", "mean_n_returned", "mean_latency", "n_decrypt_failed"],
       "(ii) sin volumen": ["frac_read", "frac_write", "frac_decrypt", "first_submit_turn", "mean_latency", "n_decrypt_failed"],
       "(iii) solo turno 1.ª entrega": ["first_submit_turn"]}
TASKS = {"switch vs base": ("switch", "base"), "placebo vs base": ("placebo", "base"), "switch vs placebo": ("switch", "placebo")}

rng = np.random.default_rng(20260914)

def loo_scores(X, y):
    n = len(y); p = np.empty(n)
    for i in range(n):
        m = np.ones(n, bool); m[i] = False
        clf = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000))
        clf.fit(X[m], y[m]); p[i] = clf.predict_proba(X[i:i + 1])[0, 1]
    return p

def boot_auc(y, p, B=2000):
    aucs = []
    idx = np.arange(len(y))
    for _ in range(B):
        b = rng.choice(idx, len(idx))
        if y[b].min() == y[b].max(): continue
        aucs.append(roc_auc_score(y[b], p[b]))
    return np.percentile(aucs, [2.5, 97.5])

auc_rows = []; roc_curves = {}; oof = {}
for model in F.model.unique():
    for task, (pos, neg) in TASKS.items():
        sub = F[(F.model == model) & F.condition.isin([pos, neg])].reset_index(drop=True)
        y = (sub.condition == pos).astype(int).values
        for det, cols in DET.items():
            X = sub[cols].values.astype(float)
            p = loo_scores(X, y)
            auc = roc_auc_score(y, p); lo, hi = boot_auc(y, p)
            auc_rows.append(dict(model=model, tarea=task, detector=det, n_pos=int(y.sum()), n_neg=int((1 - y).sum()), auc=auc, ic95_lo=lo, ic95_hi=hi))
            roc_curves[(model, task, det)] = roc_curve(y, p)
            oof[(model, task, det)] = (sub.run_id.values, y, p)
A = pd.DataFrame(auc_rows)
# add Exp1 entropy ROC reference
jroc = pd.read_csv(f"{EXP1_STATS}/J_roc.csv")
jroc = jroc.rename(columns={"contrast": "tarea", "statistic": "detector"}); jroc["detector"] = "Exp1 entropía: " + jroc.detector
jroc["n_pos"] = jroc["n_neg"] = np.nan
A = pd.concat([A, jroc[["model", "tarea", "detector", "n_pos", "n_neg", "auc"]]], ignore_index=True)
A.to_csv(f"{OUT}/E6_auc.csv", index=False)

DET["(iv) sin volumen ni latencia"] = ["frac_read", "frac_write", "frac_decrypt", "first_submit_turn", "n_decrypt_failed"]
extra = []
for model in F.model.unique():
    for task, (pos, neg) in TASKS.items():
        sub = F[(F.model == model) & F.condition.isin([pos, neg])].reset_index(drop=True)
        y = (sub.condition == pos).astype(int).values
        det = "(iv) sin volumen ni latencia"; p = loo_scores(sub[DET[det]].values.astype(float), y)
        lo, hi = boot_auc(y, p)
        extra.append(dict(model=model, tarea=task, detector=det, n_pos=int(y.sum()), n_neg=int((1 - y).sum()), auc=roc_auc_score(y, p), ic95_lo=lo, ic95_hi=hi))
        roc_curves[(model, task, det)] = roc_curve(y, p); oof[(model, task, det)] = (sub.run_id.values, y, p)
A = pd.concat([A, pd.DataFrame(extra)], ignore_index=True)
A.to_csv(f"{OUT}/E6_auc.csv", index=False)