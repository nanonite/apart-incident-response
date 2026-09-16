#!/usr/bin/env python3
"""E2 — compuerta de integridad del flujo de logprobs (análisis offline del Exp1).

Recorre las respuestas crudas de la API (`api_raw/*.json`) de cada corrida, reconstruye el
texto concatenando los tokens con logprob (descartando marcadores de fin), lo compara con
`message.content` por `difflib.SequenceMatcher(autojunk=False)` y comprueba si el token de
acción aparece en los 6 primeros tokens. Bandera por llamada
`LOGPROB_STREAM_INCOMPLETE = similitud < 0,99 ∨ token de acción ausente`; veredicto por
corrida VALIDA (≤ 5 % marcadas) / PARCIAL (≤ 20 %) / INVALIDA.

Es la versión de análisis de la compuerta que `checker.logprob_integrity` aplica ahora en
línea; sirve para auditar corridas antiguas que no la llevan.

Entrada : --root <dir>/full con la estructura <modelo>/<condicion>/s<NNN>/
Salida  : <out>/E2_integridad_corridas.csv (una fila por corrida, con el veredicto)

La tabla por llamada y el resumen por celda del informe se derivaron de este mismo recorrido
en celdas aparte y no los escribe este script; el DataFrame `calls` queda en memoria si se
ejecuta de forma interactiva.
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

EOT = {"<|eot_id|>", "<|im_end|>", "<|endoftext|>", "<|end|>", "<|eom_id|>", "</s>", "<|start_header_id|>", "<|end_header_id|>"}
ACTION_RE = re.compile(r"^\s*(READ_LOG|WRITE_LOG|DECRYPT_SCHEMA|DECRYPT_BRAND_KIT|SUBMIT_REPORT)")

def strip_eot(tok):
    return "" if tok in EOT else tok

rows = []
t0 = time.time()
run_dirs = sorted(glob.glob(f"{ROOT}/*/*/s*"))
print(f"corridas encontradas: {len(run_dirs)}")
for rd in run_dirs:
    model, cond, s = rd.split("/")[-3:]
    seed = int(s[1:])
    turns = {}
    for line in open(f"{rd}/turns.jsonl"):
        r = json.loads(line)
        turns[(r["turn"], r["agent"])] = r
    for f in sorted(glob.glob(f"{rd}/api_raw/*.json")):
        m = re.match(r"t(\d+)_(A\d)\.json", os.path.basename(f))
        turn, agent = int(m.group(1)), m.group(2)
        tr = turns.get((turn, agent), {})
        d = json.load(open(f))
        resp = d.get("response") or {}
        ch = (resp.get("choices") or [{}])[0]
        content = (ch.get("message") or {}).get("content") or ""
        lp = (ch.get("logprobs") or {}).get("content") or []
        toks = [t.get("token", "") for t in lp]
        n_lp = len(toks)
        n_valid = sum(1 for t in lp if t.get("logprob") is not None and math.isfinite(t.get("logprob", float("nan"))))
        recon = "".join(strip_eot(t) for t in toks)
        content_c = content
        for e in EOT:
            content_c = content_c.replace(e, "")
        sim = difflib.SequenceMatcher(None, recon, content_c, autojunk=False).ratio() if (recon or content_c) else 1.0
        usage = resp.get("usage") or tr.get("usage") or {}
        ctok = usage.get("completion_tokens")
        ratio = n_lp / ctok if ctok else np.nan
        first5 = "".join(strip_eot(t) for t in toks[:6])
        m_act_tok = ACTION_RE.match(first5)
        m_act_txt = ACTION_RE.match(content_c)
        action = tr.get("action")
        rows.append(dict(model=model, condition=cond, seed=seed, run_id=f"{model}__{cond}__s{seed:03d}", turn=turn, agent=agent,
                         action=action, parse_mode=tr.get("parse_mode"), finish=tr.get("finish_reason") or ch.get("finish_reason"),
                         provider=resp.get("provider"), n_logprob_tokens=n_lp, n_valid_logprob=n_valid,
                         completion_tokens=ctok, ratio_tokens=ratio, len_content=len(content_c), len_recon=len(recon),
                         similarity=sim, action_token_present=bool(m_act_tok), action_in_text=bool(m_act_txt),
                         action_token_first6=first5[:40]))
calls = pd.DataFrame(rows)

calls["LOGPROB_STREAM_INCOMPLETE"] = (calls.similarity < 0.99) | (~calls.action_token_present & (calls.action != "done"))

g = calls.groupby(["model", "condition", "seed", "run_id"])
runs_e2 = g.agg(n_calls=("turn", "size"),
                frac_flag=("LOGPROB_STREAM_INCOMPLETE", "mean"),
                frac_sim_lt99=("similarity", lambda s: (s < 0.99).mean()),
                frac_action_missing=("action_token_present", lambda s: 1 - s.mean()),
                frac_empty_stream=("n_logprob_tokens", lambda s: (s == 0).mean()),
                sim_median=("similarity", "median"),
                ratio_tokens_median=("ratio_tokens", "median")).reset_index()

def verdict(f):
    return "VALIDA" if f <= 0.05 else ("PARCIAL" if f <= 0.20 else "INVALIDA")

runs_e2["veredicto_entropico"] = runs_e2.frac_flag.map(verdict)
runs_e2["medidas_validas"] = np.where(runs_e2.veredicto_entropico == "VALIDA",
                                       "H_renorm;H_lower;surprisal;q_action;acciones",
                                       "acciones(parser de texto)")

os.makedirs(OUT, exist_ok=True)
runs_e2.to_csv(f"{OUT}/E2_integridad_corridas.csv", index=False)