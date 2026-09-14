"""Flatten every run into analysis tables and build report.html.

Tables (``<exp>/tables_<phase>/``):
    runs.csv              1 row per run: checker verdicts, timings (tau), validity, cost
    calls.csv             1 row per agent-turn: action, ground-truth state, entropy summaries,
                          action distribution q(a), usage, full completion text
    tokens.csv.gz         1 row per generated token: raw logprob + entropy metrics
    topk.csv.gz           1 row per (token, top-k alternative): raw logprob, full-vocab and renormalised prob
    system_entropy.csv    model x condition x turn: H(X1), H(X2), I(X1;X2), H(X1,X2) (soft + hard),
                          shuffled-pair I, token-entropy means, 95% bootstrap CIs, runs present
    aligned_tau_read.csv  switch runs aligned on the first cross-agent read (turn - tau_read)
"""

from __future__ import annotations

import csv
import gzip
import html
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean

import entropy as E
from scenario import AGENTS

CONDITION_COLOURS = {"base": "#64748b", "switch": "#0b6e8a", "placebo": "#c2410c"}
Q_STATES = list(E.ACTIONS) + [E.DONE]


def _run_dirs(exp: Path, phase: str) -> list[Path]:
    pattern = "full/*/*/s*" if phase == "full" else "gate/*/*/switch/s*"
    return sorted(p for p in exp.glob(pattern) if (p / "check.json").exists())


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def _mean_ci(values: list[float], resamples: int = 500, seed: int = 0) -> tuple[float | None, float | None, float | None]:
    import random
    if not values:
        return None, None, None
    rng = random.Random(seed)
    boots = sorted(mean(rng.choice(values) for _ in values) for _ in range(resamples)) if len(values) > 1 else [values[0]]
    return mean(values), boots[int(0.025 * len(boots))], boots[max(0, int(0.975 * len(boots)) - 1)]


def main(exp: Path, phase: str = "full") -> dict:
    exp = Path(exp)
    out = exp / f"tables_{phase}"
    out.mkdir(parents=True, exist_ok=True)
    runs, calls = [], []
    tok_file = gzip.open(out / "tokens.csv.gz", "wt", newline="", encoding="utf-8")
    alt_file = gzip.open(out / "topk.csv.gz", "wt", newline="", encoding="utf-8")
    tok_w, alt_w = csv.writer(tok_file), csv.writer(alt_file)
    tok_w.writerow(["model", "condition", "seed", "turn", "agent", "pos", "token", "sampled_logprob_ln", "sampled_prob",
                    "surprisal_bits", "H_lower_bits", "H_renorm_bits", "coverage", "k", "placeholder", "chosen_in_topk"])
    alt_w.writerow(["model", "condition", "seed", "turn", "agent", "pos", "rank", "alt_token", "alt_logprob_ln",
                    "alt_prob_full_vocab", "alt_prob_renorm_topk"])

    for run_dir in _run_dirs(exp, phase):
        meta = json.loads((run_dir / "meta.json").read_text())
        check = json.loads((run_dir / "check.json").read_text())
        model, condition, seed = meta["model"]["label"], meta["condition"], meta["seed"]
        comm = check["communication"]
        runs.append({
            "model": model, "condition": condition, "seed": seed, "run_dir": str(run_dir.relative_to(exp)),
            "turns_executed": meta["turns_executed"], "stop_reason": meta["stop_reason"], "calls": meta["calls"],
            "api_errors": meta["api_errors"], "cost_usd": meta["cost_usd"], "valid": check["valid"],
            "flags": "|".join(f["flag"] for f in check["flags"]), "task_success": check["task_success"],
            "n_complete": check["n_complete"], "grade_A1": check["completion"]["A1"], "grade_A2": check["completion"]["A2"],
            "communication_verified": check["communication_verified"],
            "complete_via_verified_channel": check["complete_via_verified_channel"],
            **{f"{d}_{k}": comm[d][k] for d in comm for k in ("verdict", "tau_write", "tau_read", "tau_use")},
            "tau_first_foreign_read": check["tau_first_foreign_read"],
            "placebo_decrypt_attempts": check["placebo_decrypt_attempts"], "parse_fail_rate": check["parse_fail_rate"],
        })
        for t in _load_jsonl(run_dir / "turns.jsonl"):
            ent = t.get("entropy") or {}
            q = t.get("q_action") or {}
            usage = t.get("usage") or {}
            calls.append({
                "model": model, "condition": condition, "seed": seed, "turn": t["turn"], "agent": t["agent"],
                "position_in_turn": t["position_in_turn"], "read_policy": t.get("read_policy"),
                "action": t.get("action"), "parse_mode": t.get("parse_mode"), "api_error": t.get("api_error"),
                "n_real_foreign_returned": len(t.get("returned_real_foreign_seqs") or []) if t.get("action") == "read_log" else None,
                "n_placebo_returned": len(t.get("returned_placebo_seqs") or []) if t.get("action") == "read_log" else None,
                "decrypt_asset": t.get("asset"), "decrypt_ok": t.get("decrypt_ok"), "password_source": t.get("password_source"),
                "submit_grade": t.get("grade"), "decrypted_after": "|".join(t.get("decrypted_after") or []),
                **{k: ent.get(k) for k in ("n_tokens", "n_placeholders", "mean_H_lower_bits", "mean_H_renorm_bits",
                                           "sum_H_lower_bits", "mean_surprisal_bits", "sum_surprisal_bits", "mean_coverage")},
                **{f"q_{s}": q.get(s) for s in Q_STATES},
                "action_token_pos": (t.get("action_token") or {}).get("position"),
                "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
                "cost_usd": t.get("cost_usd"), "latency_s": t.get("latency_s"), "finish_reason": t.get("finish_reason"),
                "provider_returned": t.get("provider_returned"), "completion_text": t.get("completion_text"),
            })
        raw_rows = _load_jsonl(run_dir / "logprobs_raw.jsonl")
        ent_rows = _load_jsonl(run_dir / "entropy_tokens.jsonl")
        for raw, ent in zip(raw_rows, ent_rows):
            key = [model, condition, seed, raw["turn"], raw["agent"]]
            for pos, (rt, mt) in enumerate(zip(raw["tokens"], ent["tokens"])):
                tok_w.writerow(key + [pos, rt.get("token"), mt["sampled_logprob"], mt["sampled_prob"], mt["surprisal_bits"],
                                      mt["H_lower_bits"], mt["H_renorm_bits"], mt["coverage"], mt["k"], mt["placeholder"],
                                      mt["chosen_in_topk"]])
                alts = [a for a in (rt.get("top_logprobs") or []) if a.get("logprob", E.PLACEHOLDER) > E.PLACEHOLDER + 1]
                cover = sum(math.exp(a["logprob"]) for a in alts) or 1.0
                for rank, alt in enumerate(alts):
                    p = math.exp(alt["logprob"])
                    alt_w.writerow(key + [pos, rank, alt.get("token"), alt["logprob"], p, p / cover])
    tok_file.close()
    alt_file.close()

    _write_csv(out / "runs.csv", runs)
    _write_csv(out / "calls.csv", calls)
    system = _system_entropy(calls)
    _write_csv(out / "system_entropy.csv", system)
    aligned = _aligned(calls, runs)
    _write_csv(out / "aligned_tau_read.csv", aligned)
    report = _report(exp, phase, runs, system, aligned)
    return {"runs": len(runs), "calls": len(calls), "tables": str(out), "report": str(report)}


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _system_entropy(calls: list[dict]) -> list[dict]:
    """Per model x condition x turn, across runs: the article's decomposition + token entropy."""

    by_cell: dict[tuple, dict[int, dict[str, dict]]] = defaultdict(lambda: defaultdict(dict))
    for c in calls:
        by_cell[(c["model"], c["condition"], c["turn"])][c["seed"]][c["agent"]] = c
    rows = []
    for (model, condition, turn), seeds in sorted(by_cell.items()):
        pairs, hard1, hard2 = [], [], []
        tokH = {a: [] for a in AGENTS}
        tokS = {a: [] for a in AGENTS}
        for seed, agents in seeds.items():
            if not all(a in agents for a in AGENTS):
                continue
            qs, acts = [], []
            for a in AGENTS:
                c = agents[a]
                if c["action"] == "done":
                    qs.append(E.point_mass(E.DONE))
                    acts.append(E.DONE)
                else:
                    q = {s: c[f"q_{s}"] for s in E.ACTIONS if c.get(f"q_{s}") is not None}
                    qs.append(q if q else None)
                    acts.append({"read_log": "READ", "write_log": "WRITE", "decrypt": "DECRYPT", "submit": "SUBMIT"}.get(c["action"], "OTHER"))
                    if c.get("mean_H_renorm_bits") is not None:
                        tokH[a].append(c["mean_H_renorm_bits"])
                        tokS[a].append(c["mean_surprisal_bits"])
            if all(q is not None for q in qs):
                pairs.append((qs[0], qs[1]))
                hard1.append(acts[0])
                hard2.append(acts[1])
        row = {"model": model, "condition": condition, "turn": turn, "runs_present": len(seeds), "runs_paired": len(pairs)}
        if len(pairs) >= 2:
            soft = E.mixture_mi([p[0] for p in pairs], [p[1] for p in pairs])
            shuf = E.shuffled_mi([p[0] for p in pairs], [p[1] for p in pairs])
            ci = E.bootstrap(E.mixture_mi, pairs, resamples=300, seed=turn)
            hard = E.hard_mi(hard1, hard2)
            row |= {
                "H1_bits": soft["H1_bits"], "H2_bits": soft["H2_bits"], "sum_H_bits": soft["sum_H_bits"],
                "I_bits": soft["I_bits"], "H_system_bits": soft["H_system_bits"],
                "I_ci_low": ci["I_bits"][0], "I_ci_high": ci["I_bits"][1],
                "H_system_ci_low": ci["H_system_bits"][0], "H_system_ci_high": ci["H_system_bits"][1],
                "I_shuffled_bits": shuf["I_bits"], "I_minus_shuffled_bits": soft["I_bits"] - shuf["I_bits"],
                "hard_H1_bits": hard["H1_bits"], "hard_H2_bits": hard["H2_bits"], "hard_I_bits": hard["I_bits"],
                "hard_I_miller_madow_bits": hard["I_miller_madow_bits"], "hard_H_system_bits": hard["H_system_bits"],
                **{f"p1_{s}": soft["p1"].get(s, 0.0) for s in Q_STATES},
                **{f"p2_{s}": soft["p2"].get(s, 0.0) for s in Q_STATES},
            }
        for a in AGENTS:
            m, lo, hi = _mean_ci(tokH[a], seed=turn)
            row |= {f"tokH_{a}_mean": m, f"tokH_{a}_ci_low": lo, f"tokH_{a}_ci_high": hi,
                    f"tokS_{a}_mean": mean(tokS[a]) if tokS[a] else None, f"tokH_{a}_n": len(tokH[a])}
        sums = [x + y for x, y in zip(tokH["A1"], tokH["A2"])] if len(tokH["A1"]) == len(tokH["A2"]) else []
        m, lo, hi = _mean_ci(sums, seed=turn)
        row |= {"tokH_sum_mean": m, "tokH_sum_ci_low": lo, "tokH_sum_ci_high": hi}
        rows.append(row)
    return rows


def _aligned(calls: list[dict], runs: list[dict]) -> list[dict]:
    tau = {(r["model"], r["seed"]): r["tau_first_foreign_read"] for r in runs if r["condition"] == "switch" and r["tau_first_foreign_read"]}
    cells: dict[tuple, list[float]] = defaultdict(list)
    for c in calls:
        if c["condition"] != "switch" or (c["model"], c["seed"]) not in tau or c.get("mean_H_renorm_bits") is None:
            continue
        cells[(c["model"], c["agent"], c["turn"] - tau[(c["model"], c["seed"])])].append(c["mean_H_renorm_bits"])
    rows = []
    for (model, agent, rel), values in sorted(cells.items()):
        m, lo, hi = _mean_ci(values, seed=rel + 100)
        rows.append({"model": model, "agent": agent, "turn_minus_tau_read": rel, "n": len(values),
                     "tokH_mean": m, "tokH_ci_low": lo, "tokH_ci_high": hi})
    return rows


# --------------------------------------------------------------------------- report

def _chart(title: str, series: list[dict], *, switch_turn: int | None = 8, y_label: str = "bits",
           x_label: str = "turn") -> str:
    width, height, left, right, top, bottom = 640, 260, 52, 14, 30, 40
    xs = [x for s in series for x, *_ in s["points"]]
    ys = [v for s in series for _, y, lo, hi in s["points"] for v in (y, lo, hi) if v is not None]
    if not xs or not ys:
        return f"<figure><figcaption>{html.escape(title)}: no data</figcaption></figure>"
    x0, x1 = min(xs), max(xs)
    y1 = max(ys) * 1.08 or 1.0
    y0 = min(0.0, min(ys))
    sx = lambda x: left + (width - left - right) * ((x - x0) / ((x1 - x0) or 1))
    sy = lambda y: top + (height - top - bottom) * (1 - (y - y0) / ((y1 - y0) or 1))
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">']
    for i in range(5):
        v = y0 + (y1 - y0) * i / 4
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{sy(v):.1f}" y2="{sy(v):.1f}" class="grid"/>'
                     f'<text x="{left - 6}" y="{sy(v) + 4:.1f}" text-anchor="end" class="tick">{v:.2f}</text>')
    step = max(1, round((x1 - x0) / 10))
    for x in range(int(x0), int(x1) + 1, step):
        parts.append(f'<text x="{sx(x):.1f}" y="{height - bottom + 16}" text-anchor="middle" class="tick">{x}</text>')
    parts.append(f'<text x="{(left + width - right) / 2}" y="{height - 6}" text-anchor="middle" class="axis">{x_label}</text>')
    parts.append(f'<text x="12" y="{top - 12}" class="axis">{y_label}</text>')
    if switch_turn is not None and x0 <= switch_turn <= x1:
        parts.append(f'<line x1="{sx(switch_turn):.1f}" x2="{sx(switch_turn):.1f}" y1="{top}" y2="{height - bottom}" class="switch"/>'
                     f'<text x="{sx(switch_turn) + 4:.1f}" y="{top + 10}" class="switch-label">switch</text>')
    for s in series:
        pts = [(x, y, lo, hi) for x, y, lo, hi in s["points"] if y is not None]
        band = [(x, lo, hi) for x, _, lo, hi in pts if lo is not None and hi is not None]
        if len(band) > 1:
            poly = " ".join(f"{sx(x):.1f},{sy(hi):.1f}" for x, _, hi in band) + " " + \
                   " ".join(f"{sx(x):.1f},{sy(lo):.1f}" for x, lo, _ in reversed(band))
            parts.append(f'<polygon points="{poly}" fill="{s["colour"]}" fill-opacity="0.12"/>')
        if pts:
            parts.append(f'<polyline points="{" ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y, *_ in pts)}" fill="none" '
                         f'stroke="{s["colour"]}" stroke-width="2"/>')
    parts.append("</svg>")
    legend = "".join(f'<span><i style="background:{s["colour"]}"></i>{html.escape(s["name"])}</span>' for s in series)
    return f'<figure><figcaption>{html.escape(title)}</figcaption><div class="legend">{legend}</div>{"".join(parts)}</figure>'


def _report(exp: Path, phase: str, runs: list[dict], system: list[dict], aligned: list[dict]) -> Path:
    models = sorted({r["model"] for r in runs})
    conditions = [c for c in ("base", "switch", "placebo") if any(r["condition"] == c for r in runs)]
    sections = []
    for model in models:
        rate_rows = []
        for condition in conditions:
            items = [r for r in runs if r["model"] == model and r["condition"] == condition]
            if not items:
                continue
            n = len(items)
            rate_rows.append(
                f"<tr><td>{condition}</td><td>{n}</td>"
                f"<td>{sum(r['valid'] for r in items)}</td>"
                f"<td>{sum(r['task_success'] for r in items) / n:.0%}</td>"
                f"<td>{sum(r['communication_verified'] for r in items) / n:.0%}</td>"
                f"<td>{sum(r['complete_via_verified_channel'] for r in items) / n:.0%}</td>"
                f"<td>{sum(r['n_complete'] == 2 for r in items) / n:.0%}</td>"
                f"<td>{mean(r['turns_executed'] for r in items):.1f}</td>"
                f"<td>${sum(r['cost_usd'] for r in items):.3f}</td></tr>")
        cells = {c: sorted((r for r in system if r["model"] == model and r["condition"] == c), key=lambda r: r["turn"]) for c in conditions}

        def series(key, lo=None, hi=None):
            return [{"name": c, "colour": CONDITION_COLOURS[c],
                     "points": [(r["turn"], r.get(key), r.get(lo) if lo else None, r.get(hi) if hi else None) for r in cells[c]]}
                    for c in conditions]

        charts = [
            _chart("System entropy H(X1,X2) = H(X1)+H(X2)-I over the action variable", series("H_system_bits", "H_system_ci_low", "H_system_ci_high")),
            _chart("Coupling I(X1;X2) (bits, 95% bootstrap CI)", series("I_bits", "I_ci_low", "I_ci_high")),
            _chart("Coupling minus shuffled-pair baseline", series("I_minus_shuffled_bits")),
            _chart("Token entropy, A1 + A2 (mean top-20 renormalised, bits/token)", series("tokH_sum_mean", "tokH_sum_ci_low", "tokH_sum_ci_high")),
        ]
        al = [r for r in aligned if r["model"] == model]
        if al:
            charts.append(_chart("Switch runs aligned on first cross-agent read: token entropy per agent",
                                 [{"name": a, "colour": "#0b6e8a" if a == "A1" else "#7c3aed",
                                   "points": [(r["turn_minus_tau_read"], r["tokH_mean"], r["tokH_ci_low"], r["tokH_ci_high"])
                                              for r in al if r["agent"] == a]} for a in AGENTS],
                                 switch_turn=0, x_label="turn − τ_read"))
        sections.append(f"""<section><h2>{html.escape(model)}</h2>
<table><thead><tr><th>condition</th><th>runs</th><th>valid</th><th>task success</th><th>comm. verified</th>
<th>complete via channel</th><th>both complete</th><th>mean turns</th><th>cost</th></tr></thead><tbody>{''.join(rate_rows)}</tbody></table>
<div class="charts">{''.join(charts)}</div></section>""")

    page = f"""<!doctype html><meta charset="utf-8"><title>Two-agent entropy · {html.escape(exp.name)}</title>
<style>
:root{{--bg:#f6f7f8;--ink:#15212b;--muted:#5a6872;--rule:#d9e0e3;--card:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f161a;--ink:#e2eaec;--muted:#93a3ab;--rule:#26343b;--card:#152026}}}}
body{{background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,sans-serif;margin:0;padding:24px 20px 60px}}
main{{max-width:1340px;margin:0 auto}} h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:18px;margin:32px 0 10px}}
p.meta{{color:var(--muted);margin:0 0 16px}}
table{{border-collapse:collapse;background:var(--card);font-variant-numeric:tabular-nums;margin-bottom:12px}}
th,td{{border-bottom:1px solid var(--rule);padding:6px 10px;text-align:left}} th{{color:var(--muted);font-weight:600;font-size:12px}}
.charts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:12px}}
figure{{margin:0;background:var(--card);border:1px solid var(--rule);border-radius:8px;padding:10px}}
figcaption{{font-weight:600;font-size:13px}} svg{{width:100%;height:auto}}
.grid{{stroke:var(--rule)}} .tick{{fill:var(--muted);font-size:10px}} .axis{{fill:var(--muted);font-size:11px}}
.switch{{stroke:var(--ink);stroke-dasharray:4 3}} .switch-label{{fill:var(--ink);font-size:10px}}
.legend{{display:flex;gap:14px;font-size:12px;color:var(--muted);margin:4px 0}} .legend i{{display:inline-block;width:14px;height:3px;margin-right:6px;vertical-align:middle}}
</style><main>
<h1>Two-agent shared-log entropy</h1>
<p class="meta">experiment {html.escape(exp.name)} · phase {phase} · {len(runs)} runs · tables in tables_{phase}/ ·
system entropy over the per-turn action variable X_i ∈ {{READ, WRITE, DECRYPT, SUBMIT, OTHER, DONE}} across runs</p>
{''.join(sections)}</main>"""
    path = exp / f"report_{phase}.html"
    path.write_text(page, encoding="utf-8")
    return path


if __name__ == "__main__":
    import sys
    print(main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "full"))
