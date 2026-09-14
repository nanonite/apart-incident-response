import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium", title="Entropy Analysis — Agent Experiments")


@app.cell
def _():
    import marimo as mo
    return (mo,)


@app.cell
def _(mo):
    mo.md(
        r"""
        # Entropy-Based Analysis of Agent Experiments

        Implementation of the information-theoretic framework from
        *Listening to the Collective: Entropy-Based Early Warning for Emergent Agent Communication*.

        ---

        ## Framework

        **Token-level predictive entropy** (Eq. 3) — the model's uncertainty about the next token:

        $$H_t = -\sum_{v \in V} p(v \mid x_{<t}) \log_2 p(v \mid x_{<t})$$

        Approximated from top-$K$ logprobs by renormalising the covered probability mass.

        **Per-agent entropy** (Eq. 4 operationalisation) — mean token entropy over a generation:

        $$H(X_i) = -\sum_{k=1}^{K} \tilde{p}_i(x_k) \log_2 \tilde{p}_i(x_k)$$

        where $\tilde{p}$ is the top-$K$ distribution renormalised via softmax (Eq. 2).

        **Two-agent system entropy** (Eq. 5):

        $$H(X_1, X_2) = H(X_1) + H(X_2) - I(X_1; X_2)$$

        **Mutual information / total correlation** (Eq. 6):

        $$I(X_1; X_2) = \sum_{x_1 \in \mathcal{X}_1} \sum_{x_2 \in \mathcal{X}_2}
          p(x_1, x_2) \log_2 \frac{p(x_1, x_2)}{p(x_1)\, p(x_2)}$$

        Under the independence baseline $p(x_1, x_2) = p(x_1)p(x_2)$,
        $I = 0$ and $H(X_1, X_2) = H(X_1) + H(X_2)$.
        """
    )
    return


# ── Entropy formulae ──────────────────────────────────────────────────────────

@app.cell
def _():
    import numpy as np

    def _safe_log2(p):
        with np.errstate(divide="ignore"):
            return np.where(p > 0, np.log2(p), 0.0)

    def token_entropy_bits(probs: np.ndarray) -> float:
        """Shannon entropy H (bits) of a probability vector (Eq. 3)."""
        p = np.asarray(probs, dtype=float)
        return float(-np.sum(p * _safe_log2(p)))

    def renormalize_top_k(logprobs: list) -> np.ndarray:
        """Convert raw logprobs to a renormalised top-K probability vector (Eq. 2)."""
        lp = np.asarray(logprobs, dtype=float)
        lp = lp - lp.max()
        p = np.exp(lp)
        return p / p.sum()

    def sampled_surprise_bits(p_sampled: float) -> float:
        """-log2(p) for the actually sampled token."""
        return float(-np.log2(max(p_sampled, 1e-300)))

    def agent_mean_entropy(token_entropies: list) -> float:
        """Mean per-token entropy across a generation — proxy for H(X_i)."""
        return float(np.mean(token_entropies)) if token_entropies else float("nan")

    def system_entropy_independent(h_agents: list) -> float:
        """H(X_1,...,X_n) = sum H(X_i) under mutual independence (TC = 0)."""
        return float(np.sum(h_agents))

    def total_correlation(h_agents: list, h_joint: float) -> float:
        """TC = sum H(X_i) - H(X_1,...,X_n)  (Eq. 4, Watanabe 1960)."""
        return float(np.sum(h_agents) - h_joint)

    return (
        np,
        token_entropy_bits,
        renormalize_top_k,
        sampled_surprise_bits,
        agent_mean_entropy,
        system_entropy_independent,
        total_correlation,
    )


# ── Data loaders ──────────────────────────────────────────────────────────────

@app.cell
def _(np, token_entropy_bits, renormalize_top_k, sampled_surprise_bits):
    import json
    from pathlib import Path
    from dataclasses import dataclass, field
    import sys

    REPO_ROOT = Path(__file__).parent.parent
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from apart_incident_response.run_paths import select_canonical_run_documents

    @dataclass
    class TokenRecord:
        position: int
        sampled_token: str
        sampled_prob: float
        top_tokens: list
        top_probs: np.ndarray
        top_k_entropy_bits: float
        sampled_surprise_bits: float
        partial_entropy_bits: float = None

    @dataclass
    class ExperimentRecord:
        run_id: str
        source: str
        provider: str
        model: str
        tokens: list = field(default_factory=list)

        @property
        def token_entropies(self):
            return [t.top_k_entropy_bits for t in self.tokens]

        @property
        def surprise_sequence(self):
            return [t.sampled_surprise_bits for t in self.tokens]

        @property
        def mean_entropy(self):
            e = self.token_entropies
            return float(np.mean(e)) if e else float("nan")

        @property
        def text(self):
            return "".join(t.sampled_token for t in self.tokens)

    def _load_prob_artifact(artifact, run_id, provider, model):
        rec = ExperimentRecord(run_id=run_id, source="goal_inference", provider=provider, model=model)
        for i, t in enumerate(artifact.get("tokens", [])):
            ent = t.get("entropy", {})
            alts = t.get("top_alternatives", [])
            top_toks = [t["sampled_token"]] + [a["token"] for a in alts]
            top_lp = [t["sampled_logprob"]] + [a["logprob"] for a in alts]
            top_probs = renormalize_top_k(top_lp)
            sp = t.get("sampled_probability", 0.0)
            rec.tokens.append(TokenRecord(
                position=i,
                sampled_token=t["sampled_token"],
                sampled_prob=sp,
                top_tokens=top_toks,
                top_probs=top_probs,
                top_k_entropy_bits=ent.get("top_k_entropy_bits", token_entropy_bits(top_probs)),
                sampled_surprise_bits=ent.get("sampled_surprise_bits", sampled_surprise_bits(sp)),
                partial_entropy_bits=ent.get("partial_entropy_bits"),
            ))
        return rec

    def _load_qwen3_logprobs(logprobs, run_id, model):
        rec = ExperimentRecord(run_id=run_id, source="goal_inference", provider="ollama/qwen3", model=model)
        for i, t in enumerate(logprobs):
            top_lp = [alt["logprob"] for alt in t.get("top_logprobs", [])]
            top_toks = [alt["token"] for alt in t.get("top_logprobs", [])]
            top_probs = renormalize_top_k(top_lp) if top_lp else np.array([1.0])
            ent = t.get("_entropy", {})
            sp = float(np.exp(t["logprob"]))
            rec.tokens.append(TokenRecord(
                position=i,
                sampled_token=t["token"],
                sampled_prob=sp,
                top_tokens=top_toks,
                top_probs=top_probs,
                top_k_entropy_bits=ent.get("top_k_entropy_bits", token_entropy_bits(top_probs)),
                sampled_surprise_bits=ent.get("sampled_surprise_bits", sampled_surprise_bits(sp)),
            ))
        return rec

    def _load_agent_turn_artifact(path):
        d = json.loads(path.read_text())
        records = []
        for turn in d.get("turns", []):
            pa = turn.get("probability_artifact")
            if not pa or not pa.get("tokens"):
                continue
            run_id = (
                f"{path.parent.parent.parent.name}"
                f"/{path.parent.parent.name}"
                f"/turn{turn.get('source_sequence', '?')}"
            )
            records.append(_load_prob_artifact(
                pa,
                run_id=run_id,
                provider=turn.get("provider", "unknown"),
                model=turn.get("model", "unknown"),
            ))
        return records

    def load_all_experiments():
        experiments = []

        for gi_path, d in select_canonical_run_documents(
            sorted(REPO_ROOT.glob("runs/**/goal_inference.json"))
        ):
            rel = str(gi_path.relative_to(REPO_ROOT / "runs"))
            run_id = rel.replace("/goal_inference.json", "")

            pa = d.get("probability_artifact", {})
            if pa and pa.get("tokens"):
                experiments.append(_load_prob_artifact(
                    pa,
                    run_id=run_id,
                    provider=d.get("provider", d.get("route", {}).get("endpoint", "unknown")),
                    model=d.get("response", {}).get("model", d.get("model", "unknown")),
                ))
            elif d.get("logprobs"):
                experiments.append(_load_qwen3_logprobs(
                    d["logprobs"],
                    run_id=run_id,
                    model=d.get("model", "unknown"),
                ))

        for pa_path in sorted(REPO_ROOT.glob("runs/**/agents/*/artifacts/probability_artifacts.json")):
            experiments.extend(_load_agent_turn_artifact(pa_path))

        return experiments

    experiments = load_all_experiments()

    return (
        json,
        Path,
        dataclass,
        field,
        REPO_ROOT,
        TokenRecord,
        ExperimentRecord,
        load_all_experiments,
        experiments,
    )


# ── Experiment selector ───────────────────────────────────────────────────────

@app.cell
def _(mo, experiments):
    if not experiments:
        mo.stop(True, mo.callout(
            mo.md("**No experiments with logprob data found.**"),
            kind="warn",
        ))

    _labels = {
        f"[{e.provider}] {e.run_id}  ({len(e.tokens)} tokens)": e
        for e in experiments
    }

    selected_keys = mo.ui.multiselect(
        options=list(_labels.keys()),
        value=list(_labels.keys()),
        label="Experiments to display",
    )
    mo.vstack([mo.md("## Experiment selection"), selected_keys])
    return selected_keys, _labels


@app.cell
def _(selected_keys, _labels):
    selected = [_labels[k] for k in selected_keys.value]
    return (selected,)


# ── Summary table ─────────────────────────────────────────────────────────────

@app.cell
def _(mo, selected, agent_mean_entropy, np):
    _rows = []
    for _exp in selected:
        _ents = _exp.token_entropies
        _surps = _exp.surprise_sequence
        _rows.append({
            "Run ID": _exp.run_id,
            "Provider": _exp.provider,
            "Model": _exp.model,
            "Tokens": len(_exp.tokens),
            "Mean H_t (bits)": f"{agent_mean_entropy(_ents):.4f}",
            "Std H_t": f"{float(np.std(_ents)):.4f}" if _ents else "—",
            "Mean Surprise (bits)": f"{float(np.mean(_surps)):.4f}" if _surps else "—",
            "Response": _exp.text[:60] + ("…" if len(_exp.text) > 60 else ""),
        })

    mo.vstack([
        mo.md("## Summary"),
        mo.table(_rows) if _rows else mo.callout(
            mo.md("Select at least one experiment above."), kind="info"
        ),
    ])
    return


# ── Plot 1: Token-level entropy trajectory ────────────────────────────────────

@app.cell
def _(mo, selected, np):
    import matplotlib.pyplot as plt
    import matplotlib.cm as cm

    mo.md("## Per-token entropy trajectory  $H_t$ (Eq. 3)")
    return plt, cm


@app.cell
def _(selected, plt, cm, np, mo):
    if not selected:
        mo.stop(True)

    _fig1, _ax1 = plt.subplots(figsize=(10, 4))
    _colors = cm.tab10(np.linspace(0, 1, max(len(selected), 1)))

    for _exp, _col in zip(selected, _colors):
        _ax1.plot(
            range(len(_exp.token_entropies)),
            _exp.token_entropies,
            marker="o", markersize=5,
            label=f"{_exp.run_id} [{_exp.provider}]",
            color=_col,
        )

    _ax1.set_xlabel("Token position")
    _ax1.set_ylabel("$H_t$ (bits)")
    _ax1.set_title("Token-level predictive entropy per position")
    _ax1.legend(fontsize=8, loc="upper right")
    _ax1.grid(True, alpha=0.3)
    _fig1.tight_layout()
    _fig1
    return


# ── Plot 2: Entropy distribution (histogram) ──────────────────────────────────

@app.cell
def _(mo):
    mo.md("## Entropy distribution across tokens")
    return


@app.cell
def _(selected, plt, cm, np, mo):
    if not selected:
        mo.stop(True)

    _fig2, _ax2 = plt.subplots(figsize=(10, 4))
    _colors2 = cm.tab10(np.linspace(0, 1, max(len(selected), 1)))

    for _exp, _col in zip(selected, _colors2):
        _ents = _exp.token_entropies
        if _ents:
            _ax2.hist(
                _ents, bins=min(len(_ents), 20), alpha=0.6,
                label=_exp.run_id, color=_col, edgecolor="white",
            )

    _ax2.set_xlabel("$H_t$ (bits)")
    _ax2.set_ylabel("Count")
    _ax2.set_title("Distribution of per-token entropy")
    _ax2.legend(fontsize=8)
    _ax2.grid(True, alpha=0.3)
    _fig2.tight_layout()
    _fig2
    return


# ── Plot 3: Surprise vs entropy scatter ───────────────────────────────────────

@app.cell
def _(mo):
    mo.md(r"""
    ## Sampled surprise vs partial entropy

    Each point is one token. **x-axis**: $-\log_2 p(\hat{v})$ (surprise of the chosen token).
    **y-axis**: $H_t$ (full top-K entropy). Points on the diagonal are cases where
    the model was nearly certain. Points above the diagonal: high entropy but a
    relatively probable token was still drawn.
    """)
    return


@app.cell
def _(selected, plt, cm, np, mo):
    if not selected:
        mo.stop(True)

    _fig3, _ax3 = plt.subplots(figsize=(7, 7))
    _colors3 = cm.tab10(np.linspace(0, 1, max(len(selected), 1)))
    _all_vals = []

    for _exp, _col in zip(selected, _colors3):
        for _tok in _exp.tokens:
            _x = _tok.sampled_surprise_bits
            _y = _tok.top_k_entropy_bits
            _ax3.scatter(_x, _y, color=_col, alpha=0.75, s=70, zorder=3)
            _ax3.annotate(
                _tok.sampled_token.replace("\n", "↵"),
                (_x, _y), fontsize=7, alpha=0.65,
                xytext=(3, 3), textcoords="offset points",
            )
            _all_vals += [_x, _y]

    if _all_vals:
        _lim = max(_all_vals) * 1.15
        _ax3.plot([0, _lim], [0, _lim], "k--", alpha=0.3, label="surprise = entropy")
        _ax3.set_xlim(0, _lim)
        _ax3.set_ylim(0, _lim)

    _ax3.set_xlabel(r"Sampled surprise $-\log_2 p(\hat{v})$ (bits)")
    _ax3.set_ylabel(r"Top-K entropy $H_t$ (bits)")
    _ax3.set_title("Surprise vs entropy per token")
    _ax3.grid(True, alpha=0.3)
    _handles = [
        plt.Line2D([0], [0], marker="o", color="w",
                   markerfacecolor=cm.tab10(_i / max(len(selected), 1)),
                   markersize=8, label=_e.run_id)
        for _i, _e in enumerate(selected)
    ]
    _ax3.legend(handles=_handles, fontsize=8)
    _fig3.tight_layout()
    _fig3
    return


# ── Plot 4: Multi-agent system entropy ───────────────────────────────────────

@app.cell
def _(mo):
    mo.md(r"""
    ## Multi-agent system entropy (Eq. 5)

    Per-agent $H(X_i)$ and the additive independence baseline $\sum_i H(X_i)$
    (i.e. assuming $TC = 0$). A positive total correlation
    $TC = \sum_i H(X_i) - H(X_1,\ldots,X_n)$ signals statistical coupling between agents.

    *The true joint entropy and MI (Eq. 6) require co-occurrence data from simultaneous
    multi-agent token generation. This panel shows the independence bound.*
    """)
    return


@app.cell
def _(selected, plt, np, agent_mean_entropy, system_entropy_independent, mo):
    if len(selected) < 2:
        mo.stop(True, mo.callout(
            mo.md("Select **2 or more experiments** to see multi-agent system entropy."),
            kind="info",
        ))

    _h_agents = [agent_mean_entropy(_e.token_entropies) for _e in selected]
    _h_sum = system_entropy_independent(_h_agents)
    _agent_labels = [
        f"Agent {_i+1}\n{_e.run_id.split('/')[-1]}"
        for _i, _e in enumerate(selected)
    ]

    _fig4, (_ax4a, _ax4b) = plt.subplots(1, 2, figsize=(12, 5))
    _bar_cols = plt.cm.tab10(np.linspace(0, 1, len(selected)))

    # Left: per-agent H(X_i)
    _bars = _ax4a.bar(_agent_labels, _h_agents, color=_bar_cols, edgecolor="white", zorder=3)
    _ax4a.axhline(
        _h_sum / len(selected), color="black", linestyle="--", alpha=0.5,
        label=f"Mean = {_h_sum/len(selected):.3f} bits",
    )
    _ax4a.set_ylabel("Mean $H(X_i)$ (bits)")
    _ax4a.set_title("Per-agent mean entropy")
    _ax4a.legend(fontsize=9)
    _ax4a.grid(True, alpha=0.3, axis="y")
    for _b, _v in zip(_bars, _h_agents):
        _ax4a.text(
            _b.get_x() + _b.get_width() / 2, _b.get_height() + 0.001,
            f"{_v:.3f}", ha="center", va="bottom", fontsize=9,
        )

    # Right: system entropy breakdown
    _cats = [_e.run_id.split("/")[-1] for _e in selected] + ["Σ H(X_i)\n(independence)"]
    _vals = _h_agents + [_h_sum]
    _bcols2 = list(plt.cm.tab10(np.linspace(0, 1, len(selected)))) + [(0.2, 0.2, 0.2, 0.8)]
    _ax4b.bar(_cats, _vals, color=_bcols2, edgecolor="white", zorder=3)
    _ax4b.set_ylabel("Entropy (bits)")
    _ax4b.set_title(
        f"System entropy — independence baseline\n"
        f"$H_{{sys}} = {_h_sum:.4f}$ bits  (TC = 0 assumed)"
    )
    _ax4b.grid(True, alpha=0.3, axis="y")

    _fig4.tight_layout()
    _fig4
    return


# ── Plot 5: Top-K probability mass ───────────────────────────────────────────

@app.cell
def _(mo):
    mo.md("## Top-K token probability mass per position")
    return


@app.cell
def _(selected, plt, np, mo):
    if not selected:
        mo.stop(True)

    _n = len(selected)
    _fig5, _axes = plt.subplots(1, _n, figsize=(5 * _n, 4), squeeze=False)

    for _i, _exp in enumerate(selected):
        _ax = _axes[0][_i]
        _pos = [_t.position for _t in _exp.tokens]
        _covered = [float(np.sum(_t.top_probs)) for _t in _exp.tokens]
        _residual = [max(0.0, 1.0 - _c) for _c in _covered]

        _ax.bar(_pos, _covered, label="Top-K covered", color="#4c72b0")
        _ax.bar(_pos, _residual, bottom=_covered, label="Residual", color="#dd8452", alpha=0.7)
        _ax.set_xlabel("Token position")
        _ax.set_ylabel("Probability mass")
        _ax.set_title(f"{_exp.run_id.split('/')[-1]}\n[{_exp.provider}]", fontsize=9)
        _ax.set_ylim(0, 1.05)
        _ax.legend(fontsize=8)
        _ax.grid(True, alpha=0.3, axis="y")

    _fig5.tight_layout()
    _fig5
    return


# ── Footer ────────────────────────────────────────────────────────────────────

@app.cell
def _(mo, experiments, REPO_ROOT):
    mo.md(f"""
    ---
    **Runs directory:** `{REPO_ROOT / "runs"}`  |  **Experiments loaded:** {len(experiments)}

    Implements Equations (1)–(6). The MI estimator (Eq. 6) returns 0 (independence bound);
    a full estimate requires joint token co-occurrence from simultaneous multi-agent generation.
    Agent-run `probability_artifacts.json` are loaded automatically once populated.
    """)
    return


if __name__ == "__main__":
    app.run()
