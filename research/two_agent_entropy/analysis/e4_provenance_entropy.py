#!/usr/bin/env python3
"""E4 — entropía por token según la procedencia del hecho (análisis offline del Exp1).

Alinea los tokens de `entropy_tokens.jsonl` con los spans de los hechos del escenario
(identificadores de tabla y columna, logo, hex, fuente, título, contraseñas) por offset
acumulado de caracteres, y clasifica cada token portador de hecho en PROPIO (activo del
propio agente), AJENO_LOG (activo del otro agente, sólo posible vía log) o AJENO_DONANTE
(escenario donante, sólo en placebo). Contrastes por corrida: pareados por cambio de signo
y no pareados por permutación de la etiqueta de condición; Holm dentro de cada modelo.

Sólo modelos con flujo de logprobs íntegro (véase E2).

Entrada : --root <dir>/full
Salida  : <out>/E4_por_corrida.csv (H y sorpresa por procedencia y corrida)

Los contrastes con Holm y la figura del informe se calcularon en celdas aparte a partir de
esta tabla y no los escribe este script.
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


EOT = {"<|eot_id|>", "<|im_end|>", "<|endoftext|>", "<|end|>", "<|eom_id|>", "</s>", "<|start_header_id|>", "<|end_header_id|>"}
ACTION_RE = re.compile(r"^\s*(READ_LOG|WRITE_LOG|DECRYPT_SCHEMA|DECRYPT_BRAND_KIT|SUBMIT_REPORT)")

os.makedirs(OUT, exist_ok=True)
apply_figure_style()

def flex(s):
    return r"\s*".join(re.escape(w) for w in s.split())

MAIN = {"SCHEMA": {"tabla": ["tbl_f90g", "tbl_cuu3"], "columna": ["created_id_g2", "region_y1", "ledger_id_1g", "total_d8", "acct_i0"],
                   "password": ["JBJJ-Supr-8P6G-AXjd"]},
        "BRAND_KIT": {"logo": ["mark_0qb4"], "hex": ["A9416A", "6D914C"], "fuente": ["Monmon Grotesk 3"],
                      "titulo": ["Schema Brief TX7: Drakin Mon", "TX7", "Drakin Mon"], "password": ["Nx19-DIJp-YMtd-IKXQ"]}}
DONOR = {"SCHEMA": {"tabla": ["tbl_c04b", "tbl_4ha9"], "columna": ["total_id_3a", "order_2c", "score_id_b6", "ledger_4a", "region_4y"],
                    "password": ["olwV-uyxE-NLoi-nKno"]},
         "BRAND_KIT": {"logo": ["mark_a37p"], "hex": ["65A898", "DE066A"], "fuente": ["Telqui Grotesk 6"],
                       "titulo": ["Schema Brief A5H: Rulvar Hal", "A5H", "Rulvar Hal"], "password": ["j65j-rP91-mekR-WJNi"]}}
OWN_ASSET = {"A1": "BRAND_KIT", "A2": "SCHEMA"}

def compile_facts():
    pats = []
    for esc, D in (("principal", MAIN), ("donante", DONOR)):
        for asset, types in D.items():
            for tipo, vals in types.items():
                for v in vals:
                    if tipo in ("tabla", "columna", "logo"):
                        parts = [re.escape(p) for p in v.split("_")]
                        rx = r"(?<![a-z0-9])" + r"(?:\\?_|\s*_\s*)".join(parts) + r"(?![a-z0-9])"
                    elif tipo == "hex":
                        rx = r"#?\s*" + re.escape(v)
                    elif tipo == "password":
                        rx = re.escape(v)
                    else:
                        rx = flex(v)
                    pats.append((re.compile(rx, re.I), esc, asset, tipo, v))
    return pats

PATS = compile_facts()

def fact_spans(text):
    spans = []
    for rx, esc, asset, tipo, v in PATS:
        for m in rx.finditer(text):
            spans.append((m.start(), m.end(), esc, asset, tipo, v))
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    out = []
    for s in spans:
        if out and s[0] < out[-1][1]:
            continue
        out.append(s)
    return out

tok_rows = []
t0 = time.time()
for rd in sorted(glob.glob(f"{ROOT}/gpt-4o-mini/*/s*") + glob.glob(f"{ROOT}/qwen3-235b/*/s*")):
    model, cond, s = rd.split("/")[-3:]; seed = int(s[1:]); run_id = f"{model}__{cond}__s{seed:03d}"
    tr = {(r["turn"], r["agent"]): r for r in map(json.loads, open(f"{rd}/turns.jsonl"))}
    for l in open(f"{rd}/entropy_tokens.jsonl"):
        e = json.loads(l); t = tr[(e["turn"], e["agent"])]
        if t["action"] not in ("write_log", "submit"):
            continue
        text = t["completion_text"]
        spans = fact_spans(text)
        pos = 0
        own = OWN_ASSET[e["agent"]]
        for i, x in enumerate(e["tokens"]):
            tok = x["token"]
            if tok in EOT: continue
            a, b = pos, pos + len(tok); pos = b
            hit = next((sp for sp in spans if a < sp[1] and b > sp[0]), None)
            if hit:
                esc, asset, tipo, val = hit[2], hit[3], hit[4], hit[5]
                if esc == "principal" and asset == own: proc = "propio"
                elif esc == "principal": proc = "ajeno_log"
                else: proc = "ajeno_donante"
                first = a <= hit[0]
            else:
                esc = asset = tipo = val = None; proc = "no_hecho"; first = False
            tok_rows.append((model, cond, seed, run_id, e["turn"], e["agent"], t["action"], i, tok, x["sampled_logprob"],
                             x["surprisal_bits"], x["H_renorm_bits"], x["H_lower_bits"], x["placeholder"], hit is not None,
                             tipo, val, esc, asset, proc, first, a))
toks = pd.DataFrame(tok_rows, columns=["model", "condition", "seed", "run_id", "turn", "agent", "action", "pos", "token", "logprob",
                                       "surprisal_bits", "H_renorm", "H_lower", "placeholder", "es_hecho", "tipo_hecho", "valor_hecho",
                                       "escenario", "asset", "procedencia", "primer_token_hecho", "char_offset"])

tk = toks[~toks.placeholder].copy()
tk["proc2"] = tk.procedencia.replace({"ajeno_log": "ajeno", "ajeno_donante": "ajeno"})
per = tk.groupby(["model", "condition", "seed", "run_id", "proc2"]).agg(
    n_tok=("H_renorm", "size"), H=("H_renorm", "mean"), surp=("surprisal_bits", "mean")).reset_index()
wide = per.pivot_table(index=["model", "condition", "seed", "run_id"], columns="proc2", values=["n_tok", "H", "surp"])
wide.columns = [f"{a}_{b}" for a, b in wide.columns]
wide = wide.reset_index()
ft = tk[tk.es_hecho].groupby(["run_id", "proc2", "primer_token_hecho"]).H_renorm.mean().unstack([1, 2])
ft.columns = [f"H_{p}_{'primer' if f else 'cont'}" for p, f in ft.columns]
wide = wide.merge(ft.reset_index(), on="run_id", how="left")
wide.to_csv(f"{OUT}/E4_por_corrida.csv", index=False)