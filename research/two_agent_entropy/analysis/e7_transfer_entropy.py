#!/usr/bin/env python3
"""E7 — entropía de transferencia entre las secuencias de acciones (análisis offline).

Estados por turno y agente {READ, WRITE, DECRYPT, SUBMIT, DONE, OTHER} tomados del parser
del texto —no de los logprobs—, así que el análisis vale también para corridas cuya
compuerta entrópica falla. Estimador plug-in TE(A→B) = I(B_t ; A_{t−1} | B_{t−1}) sobre las
cuentas agregadas de las corridas de cada celda, en ventana pre y post, contra dos nulos:
barajado por bloques de longitud 3 de la secuencia fuente dentro de cada corrida y
emparejamiento cruzado entre corridas.

Entrada : --root <dir>/full ; --exp1-stats <dir con G_system_entropy.csv> (opcional)
Salidas : <out>/E7_te_resumen.csv, E7_te_por_turno.csv, E7_entropia_transferencia.png
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

import json, glob, os, re, math, time
import numpy as np, pandas as pd

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

MODELS = ["gpt-4o-mini", "qwen3-235b", "llama-3.3-70b"]

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

STATES = ["READ", "WRITE", "DECRYPT", "SUBMIT", "DONE", "OTHER(unparsed/error API)"]
SMAP = {"read_log": 0, "write_log": 1, "decrypt": 2, "submit": 3, "done": 4, "unparsed": 5}
K = len(STATES); TMAX = 20
seqs = {}
for rid, g in T.groupby("run_id"):
    arr = {}
    for ag in ["A1", "A2"]:
        a = np.full(TMAX, 4, int)
        gg = g[(g.agent == ag) & (g.turn <= TMAX)]
        a[gg.turn.values - 1] = gg.action.map(SMAP).fillna(5).astype(int).values
        sub = np.where(a == 3)[0]
        if len(sub): a[sub[0] + 1:] = 4
        arr[ag] = a
    seqs[rid] = dict(model=g.model.iloc[0], condition=g.condition.iloc[0], **arr)

G = pd.read_csv(f"{EXP1_STATS}/G_system_entropy.csv")
G = G[G.variant == "all_states"]

rng = np.random.default_rng(20260914)

WINDOWS = {"pre (t=2-7)": np.arange(1, 7), "post (t=9-20)": np.arange(8, 20)}
NREP = 2000; L_BLOCK = 3

def te_from_arrays(S, D, t_idx):
    d_t = D[:, t_idx].ravel(); d_p = D[:, t_idx - 1].ravel(); s_p = S[:, t_idx - 1].ravel()
    n = len(d_t)
    def H(*cols):
        idx = np.zeros(n, int)
        for c in cols: idx = idx * K + c
        c = np.bincount(idx); p = c[c > 0] / n
        return -(p * np.log2(p)).sum()
    return H(d_t, d_p) - H(d_p) - H(d_t, d_p, s_p) + H(d_p, s_p)

def block_shuffle(S, L, rng):
    n, Tn = S.shape; out = np.empty_like(S)
    nb = int(np.ceil(Tn / L))
    for i in range(n):
        blocks = [S[i, b * L:(b + 1) * L] for b in range(nb)]
        perm = rng.permutation(nb)
        out[i] = np.concatenate([blocks[j] for j in perm])[:Tn]
    return out

res_rows = []; turn_rows = []
t0 = time.time()
for model in MODELS:
    for cond in ["base", "switch", "placebo"]:
        ids = [r for r, s in seqs.items() if s["model"] == model and s["condition"] == cond]
        A1 = np.array([seqs[r]["A1"] for r in ids]); A2 = np.array([seqs[r]["A2"] for r in ids])
        for wname, tix in WINDOWS.items():
            for direction, (S, D) in {"A1->A2": (A1, A2), "A2->A1": (A2, A1)}.items():
                te = te_from_arrays(S, D, tix)
                null_b = np.array([te_from_arrays(block_shuffle(S, L_BLOCK, rng), D, tix) for _ in range(NREP)])
                null_x = []
                for _ in range(NREP):
                    while True:
                        perm = rng.permutation(len(ids))
                        if not np.any(perm == np.arange(len(ids))): break
                    null_x.append(te_from_arrays(S[perm], D, tix))
                null_x = np.array(null_x)
                res_rows.append(dict(model=model, condition=cond, ventana=wname, direccion=direction, n_runs=len(ids), n_transiciones=len(ids) * len(tix),
                                     TE_bits=te, TE_nulo_bloques_media=null_b.mean(), TE_nulo_bloques_p95=np.percentile(null_b, 95), exceso_bloques=te - null_b.mean(),
                                     p_bloques=(np.sum(null_b >= te - 1e-12) + 1) / (NREP + 1),
                                     TE_nulo_cruzado_media=null_x.mean(), TE_nulo_cruzado_p95=np.percentile(null_x, 95), exceso_cruzado=te - null_x.mean(),
                                     p_cruzado=(np.sum(null_x >= te - 1e-12) + 1) / (NREP + 1), n_rep=NREP, L_bloque=L_BLOCK))
        for t in range(2, TMAX + 1):
            tix = np.array([t - 1])
            for direction, (S, D) in {"A1->A2": (A1, A2), "A2->A1": (A2, A1)}.items():
                te = te_from_arrays(S, D, tix)
                null_x = np.array([te_from_arrays(S[rng.permutation(len(ids))], D, tix) for _ in range(500)])
                gI = G[(G.model == model) & (G.condition == cond) & (G.turn == t)]
                turn_rows.append(dict(model=model, condition=cond, turn=t, direccion=direction, n_runs=len(ids), TE_bits=te,
                                      TE_nulo_cruzado_media=null_x.mean(), exceso=te - null_x.mean(), p_cruzado=(np.sum(null_x >= te - 1e-12) + 1) / 501,
                                      I_inst_exp1=gI.I.iloc[0] if len(gI) else np.nan, I_inst_exceso_exp1=gI.I_excess.iloc[0] if len(gI) else np.nan, p_perm_I_exp1=gI.p_perm.iloc[0] if len(gI) else np.nan))
TE = pd.DataFrame(res_rows); TEt = pd.DataFrame(turn_rows)
TE.to_csv(f"{OUT}/E7_te_resumen.csv", index=False); TEt.to_csv(f"{OUT}/E7_te_por_turno.csv", index=False)
print(time.time() - t0)
print(TE[["model", "condition", "ventana", "direccion", "TE_bits", "TE_nulo_bloques_media", "exceso_bloques", "p_bloques", "TE_nulo_cruzado_media", "exceso_cruzado", "p_cruzado"]].round(4).to_string())