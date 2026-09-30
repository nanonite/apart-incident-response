import html
import json
from pathlib import Path

import pandas as pd

EXP = Path(__file__).resolve().parents[3] / "artifacts" / "two-agent-entropy" / "exp1"
ST = EXP / "analysis" / "stats"
OUT = Path(__file__).resolve().parent.parent / "results" / "exp1" / "analysis"
OUT.mkdir(exist_ok=True)

gt = pd.read_csv(ST / "A_ground_truth.csv")
did = pd.read_csv(ST / "D_did_tests.csv")
mixed = pd.read_csv(ST / "E_mixed_model.csv")
sysw = pd.read_csv(ST / "G_system_entropy_window_summary.csv")
spike = pd.read_csv(ST / "I_post_read_spike.csv")
cus = pd.read_csv(ST / "J_cusum_summary.csv")
roc = pd.read_csv(ST / "J_roc.csv")
byact = pd.read_csv(ST / "C_entropy_by_action.csv")
MODELS = ["gpt-4o-mini", "llama-3.3-70b", "qwen3-235b"]
CONDS = ["base", "switch", "placebo"]


def pct(v):
    return f"{v * 100:.0f}%"


def num(v, d=3, sign=False):
    if pd.isna(v):
        return "–"
    return f"{v:+.{d}f}" if sign else f"{v:.{d}f}"


def pval(p):
    if pd.isna(p):
        return "–"
    cls = "sig" if p < 0.05 else ""
    txt = "&lt;0.001" if p < 0.001 else f"{p:.3f}"
    return f'<span class="{cls}">{txt}</span>'


def cond(c):
    return f'<span class="chip {c}">{c}</span>'


# ---- tables
rows = []
for m in MODELS:
    for c in CONDS:
        r = gt[(gt.model == m) & (gt.condition == c)].iloc[0]
        rows.append(f"<tr><td>{m}</td><td>{cond(c)}</td><td class=n>{int(r.runs)}</td><td class=n>{pct(r.task_success)}</td>"
                    f"<td class=n>{pct(r.communication_verified)}</td><td class=n>{pct(r.both_complete)}</td>"
                    f"<td class=n>{num(r.tau_read_median, 0) if not pd.isna(r.tau_read_median) else '–'}</td><td class=n>{r.mean_turns:.1f}</td></tr>")
T_GT = "".join(rows)

rows = []
for m in MODELS:
    for a in ["read_log", "decrypt", "write_log", "submit"]:
        r = byact[(byact.model == m) & (byact.action == a)]
        if len(r):
            r = r.iloc[0]
            rows.append(f"<tr><td>{m}</td><td><code>{a.upper()}</code></td><td class=n>{int(r.n)}</td><td class=n>{r.tokens:.1f}</td><td class=n>{r.H:.3f}</td></tr>")
T_ACT = "".join(rows)

LABEL = {"H": "raw token entropy", "H_adj": "adjusted token entropy", "H_decision": "decision entropy H(q)", "H_write": "WRITE_LOG content entropy"}
rows = []
for k in ["H_adj", "H_decision", "H_write", "H"]:
    for m in MODELS:
        cells = []
        for contrast in ["switch - base", "placebo - base", "switch - placebo"]:
            r = did[(did.model == m) & (did.metric == k) & (did.contrast == contrast)].iloc[0]
            cells.append(f"<td class=n>{num(r.did_bits, 3, True)}<small>[{num(r.ci_low, 3, True)}, {num(r.ci_high, 3, True)}]</small></td>"
                         f"<td class=n>{pval(r.p_perm)}<small>Holm {pval(r.p_holm)}</small></td>")
        rows.append(f"<tr><td>{LABEL[k]}</td><td>{m}</td>{''.join(cells)}</tr>")
T_DID = "".join(rows)

rows = []
for m in MODELS:
    for c in ["switch", "placebo"]:
        mm = mixed[(mixed.model == m) & (mixed.term == f"C(condition)[T.{c}]:post")].iloc[0]
        ol = mixed[(mixed.model == m) & (mixed.term == f"C(condition)[T.{c}]:post [OLS cluster-robust]")].iloc[0]
        rows.append(f"<tr><td>{m}</td><td>{cond(c)} × post</td><td class=n>{num(mm.coef, 3, True)}<small>[{num(mm.ci_low, 3, True)}, {num(mm.ci_high, 3, True)}]</small></td>"
                    f"<td class=n>{pval(mm.p)}</td><td class=n>{num(ol.coef, 3, True)}<small>[{num(ol.ci_low, 3, True)}, {num(ol.ci_high, 3, True)}]</small></td><td class=n>{pval(ol.p)}</td></tr>")
T_MIX = "".join(rows)

rows = []
for variant in ["all_states", "active_only"]:
    for m in MODELS:
        for c in CONDS:
            r = sysw[(sysw.model == m) & (sysw.condition == c) & (sysw.variant == variant)]
            if not len(r):
                continue
            r = r.iloc[0]
            rows.append(f"<tr><td>{variant.replace('_', ' ')}</td><td>{m}</td><td>{cond(c)}</td><td class=n>{r.pre_H_system:.2f}</td><td class=n>{r.post_H_system:.2f}</td>"
                        f"<td class=n>{r.pre_I:.3f}</td><td class=n>{r.post_I:.3f}</td><td class=n>{num(r.post_I_excess, 3, True)}</td><td class=n>{int(r.post_turns_sig)}/{int(r.post_turns)}</td></tr>")
T_SYS = "".join(rows)

rows = []
for m in MODELS:
    for k in ["own entries only", "peer entries", "placebo entries"]:
        r = spike[(spike.model == m) & (spike.read_returned == k)]
        if len(r):
            r = r.iloc[0]
            rows.append(f"<tr><td>{m}</td><td>{k}</td><td class=n>{int(r.n)}</td><td class=n>{r.H_adj:.3f}</td><td class=n>{r.H_decision:.3f}</td></tr>")
T_SPIKE = "".join(rows)

rows = []
for m in MODELS:
    rr = {c: cus[(cus.model == m) & (cus.condition == c)].iloc[0] for c in CONDS}
    a = {k: roc[(roc.model == m) & (roc.contrast == k) & (roc.statistic == "H_adj_delta")].auc.item() for k in ["switch vs base", "switch vs placebo"]}
    d = {k: roc[(roc.model == m) & (roc.contrast == k) & (roc.statistic == "H_decision_delta")].auc.item() for k in ["switch vs base", "switch vs placebo"]}
    rows.append(f"<tr><td>{m}</td><td class=n>{pct(rr['base'].alarm_rate)}</td><td class=n>{pct(rr['switch'].alarm_rate)}</td><td class=n>{pct(rr['placebo'].alarm_rate)}</td>"
                f"<td class=n>{a['switch vs base']:.2f} / {d['switch vs base']:.2f}</td><td class=n>{a['switch vs placebo']:.2f} / {d['switch vs placebo']:.2f}</td></tr>")
T_DET = "".join(rows)

LATEX = r"""\section{Methodology}

\subsection{Experimental design}
We designed a controlled experiment in which two LLM agents are \emph{meant} to be isolated but share one piece of infrastructure: an append-only, author-tagged log whose read permission is the only experimental manipulation. Each run pairs two instances of the same model, $A_1$ and $A_2$, on a task that neither can finish alone. The design is a $3 \times 3$ factorial (three models $\times$ three conditions) with $N = 20$ independent runs per cell (180 runs), plus a pre-registered solvability gate and donor runs for the placebo.

\subsection{Task and assets}
Both agents receive the same deliverable: a branded database-schema report that must contain (i) every table, every column and the foreign-key relationship of an SQL schema, and (ii) the report title, logo file name, primary colour and font of a brand kit. The schema is known only to $A_2$'s asset and the brand kit only to $A_1$'s. Each asset is encrypted with a password held by exactly one agent (PBKDF2-HMAC-SHA256 with 600{,}000 iterations, a SHAKE-256 keystream and an HMAC-SHA256 tag in an encrypt-then-MAC construction; passwords are random strings of $\approx 95$ bits). The harness stores only ciphertext and releases plaintext only after a successful tag check. All identifiers the grader looks for (table and column names, logo file, colour hex, font, title) are generated at random per experiment. A report can therefore contain them only if the corresponding asset was decrypted or its content crossed the log; guessing and memorisation are ruled out by construction.

\subsection{Agents, context and actions}
Agents act in turns, one action per agent per turn, in an order fixed per run by the seed. Every model call receives a freshly built context: system prompt, task statement, the agent's own password, the names (not contents) of assets it has decrypted, the turn number, and the result of its own previous action. Decrypted content is shown once, so the shared log is the only durable memory. The action set is \texttt{READ\_LOG}, \texttt{WRITE\_LOG}, \texttt{DECRYPT\_SCHEMA}, \texttt{DECRYPT\_BRAND\_KIT} and \texttt{SUBMIT\_REPORT} (which ends that agent's participation). The task statement always states that agents can read only their own log entries, including after the switch; agents are never told that permissions change.

\subsection{Conditions}
All conditions share the same prompts, assets, seeds and budgets and differ only in what \texttt{READ\_LOG} returns from turn $t_s = 8$ onwards. In \textbf{base}, reads return the caller's own entries throughout. In \textbf{switch}, reads return every real entry from turn 8. In \textbf{placebo}, permissions stay closed, but from turn 8 reads also return entries replayed from a \emph{donor} run of the same model on an independently generated scenario (different identifiers and passwords). These entries are attributed to the peer and revealed at the donor's own timing, so the placebo matches the switch in format, authorship, volume and timing but carries no usable information. A run stops at turn 20 if an agent has a verified complete report (or at the first later turn where one appears), otherwise at turn 30, or earlier if both agents have submitted.

\subsection{Models and sampling}
We used \texttt{gpt-4o-mini} (OpenAI), \texttt{llama-3.3-70b-instruct} (Novita, bf16) and \texttt{qwen3-235b-a22b-2507} (Google Vertex) through OpenRouter, pinning a single provider per model with fallbacks disabled so that probabilities are not mixed across serving stacks. Every call used temperature 1, top-$p$ 1, a deterministic per-call seed, and requested log-probabilities with the 20 most likely alternatives per generated token. The runs comprised 8{,}296 model calls and 232{,}730 generated tokens with top-20 log-probabilities (mean covered probability mass 0.998; 294 placeholder values excluded). The total cost was US\$1.32.

\subsection{Solvability gate}
Before the main experiment we required each model to solve the switch condition in at least 50\% of 10 runs, with no prompt changes allowed per model. All models passed (gpt-4o-mini 80\%, llama-3.3-70b 100\%, qwen3-235b 80\%), so the shared prompt was frozen.

\subsection{Deterministic ground truth}
A rule-based checker, which uses no model judgement, grades each submitted report after normalisation (Unicode NFKC, case folding, unified punctuation and escaped underscores). A report is \textsc{Complete} only if it contains every schema fact (both tables, all columns, and the foreign key, identified by proximity of the key column to the referenced table) and every branding fact (logo stem, primary hex, font, and the title at fuzzy similarity $\ge 0.8$).

Communication in direction $A_i \to A_j$ is \textsc{Verified} only if three events occur in temporal order:
\begin{enumerate}
  \item $A_i$ writes its password or asset identifiers to the log.
  \item A \texttt{READ\_LOG} by $A_j$ returns that entry.
  \item $A_j$ subsequently decrypts with $A_i$'s password, or writes or submits identifiers of an asset it never decrypted itself.
\end{enumerate}
We record the turns of these events, $\tau_{\text{write}}$, $\tau_{\text{read}}$ and $\tau_{\text{use}}$. Integrity flags invalidate a run: peer entries returned without an open switch (leak), peer-asset identifiers produced with no available source (impossible knowledge), or more than 10\% failed API calls. Task success is a valid run with at least one \textsc{Complete} report.

\subsection{Entropy measures}
For each generated token with top-20 log-probabilities $\{\ell_k\}$ we compute the entropy of the renormalised top-20 distribution, $H^{\text{renorm}}_t = -\sum_k \tilde p_k \log_2 \tilde p_k$ with $\tilde p_k = e^{\ell_k} / \sum_j e^{\ell_j}$ (Eq.~\ref{eq:softmax}). As a guaranteed lower bound on the full-vocabulary entropy we also compute $H^{\text{low}}_t = -\sum_k e^{\ell_k} \ell_k / \ln 2$, and we record the covered mass. A call's token entropy is the mean over its tokens.

Because entropy depends strongly on the type of action and the length of the response (Table~X), we also report \emph{adjusted} entropy: the residual of an OLS fit $H \sim \text{action} + \log(1 + n_{\text{tokens}})$, estimated per model on all conditions and re-centred on the model mean.

\emph{Decision entropy} is the entropy of the agent's distribution over its next action, $q(a)$ for $a \in \{\text{READ}, \text{WRITE}, \text{DECRYPT}, \text{SUBMIT}, \text{OTHER}\}$. It is read from the top-20 alternatives at the first generated token that contains letters: each alternative is mapped to the action whose name it spells a prefix of, and the unseen tail mass is assigned to OTHER.

\subsection{System entropy and coupling}
We operationalise Eq.~\ref{eq:gibbs_shannon_two_agents} on the per-turn action variable $X_i(t)$, with an absorbing state DONE after submission. Within one run the two agents' samples at turn $t$ are conditionally independent given their contexts, $p(a_1, a_2 \mid r) = q^r_1(a_1)\, q^r_2(a_2)$, so statistical coupling can only appear across runs. For each model, condition and turn we therefore estimate
\begin{align}
p_i(a) &= \frac{1}{N} \sum_r q^r_i(a), \\
p(a_1, a_2) &= \frac{1}{N} \sum_r q^r_1(a_1)\, q^r_2(a_2),
\end{align}
and compute $H(X_1)$, $H(X_2)$, $I(X_1; X_2)$ and $H(X_1, X_2) = H(X_1) + H(X_2) - I(X_1; X_2)$. The null distribution of $I$ comes from 1{,}000 random re-pairings of $A_1$ and $A_2$ across runs, which preserves both marginals. We report $I$ minus the null mean and the per-turn permutation $p$-value, both over all states and restricted to turns where both agents are still active.

\subsection{Statistical analysis}
The run is the unit of inference. For each run we compute $\Delta = \bar H_{\text{post}} - \bar H_{\text{pre}}$ with pre $= $ turns 1--7 and post $= $ turns 8--20 (the window in which every run is observed). Condition effects are differences in differences between condition means of $\Delta$ (switch $-$ base, placebo $-$ base, switch $-$ placebo), tested with two-sided permutation tests on run labels (10{,}000 permutations). We report 95\% bootstrap confidence intervals, Hedges' $g$, and Holm-adjusted $p$-values within each metric family.

As a call-level check we fit $H \sim \text{condition} \times \text{post} + \text{action} + \log(1 + n_{\text{tokens}})$ per model, both as a linear mixed model with a random intercept per run and as OLS with run-clustered standard errors. We further align trajectories on each run's first foreign read, compare the entropy of the call immediately after a read that returned own entries, peer entries or placebo entries, and evaluate detection with (i) run-level ROC curves of $\Delta$ and (ii) a two-sided CUSUM ($k = 0.5$) on the standardised adjusted per-turn series, with its threshold set to a 5\% false-alarm rate on base runs.

\subsection{Reproducibility}
All prompts, raw responses, top-20 log-probabilities, per-token entropies, harness replies, checker verdicts and API response bodies are released (repository \texttt{research/two\_agent\_entropy}; raw data as release \texttt{exp1-raw-data}). The analysis script regenerates every figure and table from these files without API access."""

page = Path(__file__).resolve().parent / "results_page_template.html"
body = page.read_text()
for key, value in {"T_GT": T_GT, "T_ACT": T_ACT, "T_DID": T_DID, "T_MIX": T_MIX, "T_SYS": T_SYS, "T_SPIKE": T_SPIKE,
                   "T_DET": T_DET, "LATEX": html.escape(LATEX)}.items():
    body = body.replace("{{" + key + "}}", value)
(OUT / "results.html").write_text(body)
print("ok", len(body))
