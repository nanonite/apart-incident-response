import shutil
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3] / "artifacts" / "two-agent-entropy"
OUT = Path(__file__).resolve().parent / "temperature_page"  # standalone copy with its own figure folders
MODELS = ["gpt-4o-mini", "llama-3.3-70b", "qwen3-235b"]
CONDS = ["base", "switch", "placebo"]
FIGS = [
    ("fig01_ground_truth.png", "Task success (bars) and verified communication (ticks); right: first cross-agent read (τ_read) and first use (τ_use) in switch runs."),
    ("fig02c_decision_entropy_trajectories.png", "Decision entropy H(q), the uncertainty over the next action, per turn with 95% bootstrap bands. Dashed line: switch at turn 8."),
    ("fig02b_adjusted_entropy_trajectories.png", "Token entropy adjusted for action type and response length, per turn."),
    ("fig04_did_run_level.png", "Run-level change (turns 8–20 minus 1–7) per condition; titles give switch−base and switch−placebo with permutation p-values."),
    ("fig07_post_read_spike.png", "Adjusted entropy of the call right after a READ_LOG (turns ≥ 8), by what the read returned."),
    ("fig05_system_entropy_active_only.png", "System entropy H(X₁,X₂), coupling I(X₁;X₂) with its re-pairing null, and I minus null, for turns where both agents are active."),
]


def pct(v):
    return f"{v * 100:.0f}%"


def pval(p):
    if pd.isna(p):
        return "–"
    txt = "&lt;0.001" if p < 0.001 else f"{p:.3f}"
    return f'<span class="{"sig" if p < 0.05 else ""}">{txt}</span>'


def signed(v):
    return "–" if pd.isna(v) else f"{v:+.3f}"


def chip(c):
    return f'<span class="chip {c}">{c}</span>'


def section_tables(exp: str) -> dict:
    st = ROOT / exp / "analysis" / "stats"
    gt = pd.read_csv(st / "A_ground_truth.csv")
    did = pd.read_csv(st / "D_did_tests.csv")
    mixed = pd.read_csv(st / "E_mixed_model.csv")
    spike = pd.read_csv(st / "I_post_read_spike.csv")
    rows = []
    for m in MODELS:
        for c in CONDS:
            r = gt[(gt.model == m) & (gt.condition == c)].iloc[0]
            rows.append(f"<tr><td>{m}</td><td>{chip(c)}</td><td class=n>{pct(r.task_success)}</td><td class=n>{pct(r.communication_verified)}</td>"
                        f"<td class=n>{'–' if pd.isna(r.tau_read_median) else f'{r.tau_read_median:.0f}'}</td><td class=n>{r.mean_turns:.1f}</td></tr>")
    t_gt = "".join(rows)
    rows = []
    for metric, label in (("H_adj", "adjusted token entropy"), ("H_decision", "decision entropy")):
        for m in MODELS:
            cells = []
            for contrast in ("switch - base", "placebo - base", "switch - placebo"):
                r = did[(did.model == m) & (did.metric == metric) & (did.contrast == contrast)].iloc[0]
                cells.append(f"<td class=n>{signed(r.did_bits)}<small>[{signed(r.ci_low)}, {signed(r.ci_high)}]</small></td>"
                             f"<td class=n>{pval(r.p_holm)}<small>AUC {r.auc:.2f}</small></td>")
            rows.append(f"<tr><td>{label}</td><td>{m}</td>{''.join(cells)}</tr>")
    t_did = "".join(rows)
    rows = []
    for m in MODELS:
        for c in ("switch", "placebo"):
            r = mixed[(mixed.model == m) & (mixed.term == f"C(condition)[T.{c}]:post [OLS cluster-robust]")].iloc[0]
            rows.append(f"<tr><td>{m}</td><td>{chip(c)} × post</td><td class=n>{signed(r.coef)}<small>[{signed(r.ci_low)}, {signed(r.ci_high)}]</small></td><td class=n>{pval(r.p)}</td></tr>")
    t_reg = "".join(rows)
    rows = []
    for m in MODELS:
        vals = {k: spike[(spike.model == m) & (spike.read_returned == k)] for k in ("own entries only", "peer entries", "placebo entries")}
        fmt = lambda df: "–" if df.empty else f"{df.iloc[0].H_adj:.3f}"
        rows.append(f"<tr><td>{m}</td><td class=n>{fmt(vals['own entries only'])}</td><td class=n>{fmt(vals['peer entries'])}</td><td class=n>{fmt(vals['placebo entries'])}</td></tr>")
    t_spike = "".join(rows)
    return {"gt": t_gt, "did": t_did, "reg": t_reg, "spike": t_spike}


def figures(exp: str) -> str:
    blocks = []
    for name, caption in FIGS:
        for theme in ("figures", "figures_dark"):
            dst = OUT / exp / theme
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / exp / "analysis" / theme / name, dst / name)
        blocks.append(
            f'<figure><img class="fig-light" src="{exp}/figures/{name}" alt="{caption}" loading="lazy">'
            f'<img class="fig-dark" src="{exp}/figures_dark/{name}" alt="{caption}" loading="lazy">'
            f"<figcaption>{caption}</figcaption></figure>")
    return "".join(blocks)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    page = (Path(__file__).parent / "temperature_page_template.html").read_text()
    for exp in ("exp2", "exp3"):
        tables = section_tables(exp)
        for key, value in tables.items():
            page = page.replace("{{" + f"{exp}_{key}" + "}}", value)
        page = page.replace("{{" + f"{exp}_figures" + "}}", figures(exp))
    assert "{{" not in page, "unfilled placeholder"
    (OUT / "index.html").write_text(page)
    files = sorted(str(p.relative_to(OUT)) for p in OUT.rglob("*.png"))
    print(len(page), len(files))


main()
