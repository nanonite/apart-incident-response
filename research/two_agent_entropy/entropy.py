"""Entropy calculations, from raw API logprobs up to the two-agent system.

Level 1  token      token_metrics(entry)
Level 2  call       call_metrics(tokens), action_distribution(tokens)
Level 3  system     system_entropy(q1_runs, q2_runs)   (article eq. H(X1,X2) = H(X1)+H(X2)-I)

Conventions
-----------
* All entropies in bits. The API returns natural-log probabilities.
* OpenAI marks an unknown logprob with -9999; such values are never used as
  probabilities (the position is counted as a placeholder).
* ``H_lower``  = -sum_{top-k} p log2 p with p under the full vocabulary: a
  guaranteed lower bound on the full-vocabulary entropy.
* ``H_renorm`` = entropy of the top-k renormalised to sum to 1: the article's
  definition (softmax over the k visible alternatives).
* ``coverage`` = sum_{top-k} p ; 1 - coverage is the unseen tail.
"""

from __future__ import annotations

import math
import random
from typing import Iterable, Mapping, Sequence

PLACEHOLDER = -9999.0
ACTIONS = ("READ", "WRITE", "DECRYPT", "SUBMIT", "OTHER")
DONE = "DONE"
_ACTION_PREFIXES = {"READ": "READLOG", "WRITE": "WRITELOG", "DECRYPT": "DECRYPT", "SUBMIT": "SUBMITREPORT"}
LN2 = math.log(2.0)


# --------------------------------------------------------------------------- level 1: token

def _valid(logprob) -> bool:
    return isinstance(logprob, (int, float)) and math.isfinite(logprob) and logprob > PLACEHOLDER + 1


def token_metrics(entry: Mapping) -> dict:
    """Metrics for one generated token from its logprob entry."""

    sampled = entry.get("logprob")
    alternatives = [a for a in (entry.get("top_logprobs") or []) if _valid(a.get("logprob"))]
    probs = [math.exp(float(a["logprob"])) for a in alternatives]
    chosen_in_topk = any(a.get("token") == entry.get("token") for a in alternatives)
    if _valid(sampled) and not chosen_in_topk:
        probs.append(math.exp(float(sampled)))  # a distinct vocabulary item with a known probability
    coverage = min(sum(probs), 1.0)
    h_lower = -sum(p * math.log2(p) for p in probs if p > 0)
    h_renorm = (-sum((p / coverage) * math.log2(p / coverage) for p in probs if p > 0)
                if coverage > 0 else None)
    return {
        "token": entry.get("token"),
        "placeholder": not _valid(sampled),
        "sampled_logprob": float(sampled) if _valid(sampled) else None,
        "sampled_prob": math.exp(float(sampled)) if _valid(sampled) else None,
        "surprisal_bits": -float(sampled) / LN2 if _valid(sampled) else None,
        "k": len(alternatives),
        "chosen_in_topk": chosen_in_topk,
        "coverage": coverage,
        "H_lower_bits": h_lower,
        "H_renorm_bits": h_renorm,
    }


def restore_temperature(tokens: Sequence[Mapping], temperature: float) -> list[dict]:
    """Undo provider-side temperature scaling of returned logprobs (top-k only).

    Some providers return log p_T = z/T - logsumexp(z/T). Multiplying by T gives z - T*logsumexp(z/T),
    i.e. the model logits up to a per-position constant, so renormalising over the returned top-k
    recovers the model's own (T=1) distribution restricted to those k tokens. The unseen tail mass
    cannot be recovered, so restored positions have coverage 1 by construction. Placeholders stay.
    """

    if temperature <= 0:
        raise ValueError("temperature must be > 0 to restore logprobs")
    restored = []
    for entry in tokens:
        alts = [a for a in (entry.get("top_logprobs") or []) if _valid(a.get("logprob"))]
        scaled = {id(a): float(a["logprob"]) * temperature for a in alts}
        values = list(scaled.values())
        sampled = entry.get("logprob")
        in_topk = any(a.get("token") == entry.get("token") for a in alts)
        if _valid(sampled) and not in_topk:
            values.append(float(sampled) * temperature)
        if not values:
            restored.append(dict(entry))
            continue
        top = max(values)
        log_z = top + math.log(sum(math.exp(v - top) for v in values))
        new_alts = []
        for a in entry.get("top_logprobs") or []:
            b = dict(a)
            if id(a) in scaled:
                b["logprob"] = scaled[id(a)] - log_z
            new_alts.append(b)
        new = dict(entry)
        new["top_logprobs"] = new_alts
        if _valid(sampled):
            new["logprob"] = float(sampled) * temperature - log_z
        restored.append(new)
    return restored


# --------------------------------------------------------------------------- level 2: call

def _mean(values: Iterable[float | None]) -> float | None:
    real = [v for v in values if v is not None]
    return sum(real) / len(real) if real else None


def call_metrics(tokens: Sequence[Mapping]) -> dict:
    """Per-call summary over every generated token."""

    rows = [token_metrics(t) for t in tokens]
    usable = [r for r in rows if not r["placeholder"]]
    return {
        "n_tokens": len(rows),
        "n_placeholders": len(rows) - len(usable),
        "mean_H_lower_bits": _mean(r["H_lower_bits"] for r in usable),
        "mean_H_renorm_bits": _mean(r["H_renorm_bits"] for r in usable),
        "sum_H_lower_bits": sum(r["H_lower_bits"] for r in usable),
        "mean_surprisal_bits": _mean(r["surprisal_bits"] for r in usable),
        "sum_surprisal_bits": sum(r["surprisal_bits"] for r in usable),
        "mean_coverage": _mean(r["coverage"] for r in usable),
    }


def _alpha_upper(text: str) -> str:
    return "".join(ch for ch in (text or "") if ch.isalpha()).upper()


def classify_action_token(token: str) -> str:
    letters = _alpha_upper(token)
    if not letters:
        return "OTHER"
    for action, spelled in _ACTION_PREFIXES.items():
        if spelled.startswith(letters) or letters.startswith(spelled):
            return action
    return "OTHER"


def action_distribution(tokens: Sequence[Mapping]) -> dict:
    """Distribution over the next action, read at the first token carrying letters.

    Leading whitespace / markdown tokens are skipped. Each top-k alternative is
    mapped to the action whose name it spells a prefix of (R->READ, W->WRITE,
    D->DECRYPT, S->SUBMIT), anything else to OTHER; unseen tail mass goes to OTHER.
    """

    for pos, entry in enumerate(tokens):
        if not _alpha_upper(entry.get("token", "")):
            continue
        q = {a: 0.0 for a in ACTIONS}
        seen = False
        for alt in entry.get("top_logprobs") or []:
            if _valid(alt.get("logprob")):
                q[classify_action_token(alt.get("token", ""))] += math.exp(float(alt["logprob"]))
                seen = True
        if not seen:
            return {"q": None, "position": pos, "token": entry.get("token"), "reason": "no usable top_logprobs"}
        total = sum(q.values())
        if total < 1.0:
            q["OTHER"] += 1.0 - total
        norm = sum(q.values())
        return {"q": {a: v / norm for a, v in q.items()}, "position": pos, "token": entry.get("token"),
                "sampled_class": classify_action_token(entry.get("token", ""))}
    return {"q": None, "position": None, "token": None, "reason": "no token with letters"}


# --------------------------------------------------------------------------- level 3: system

def entropy_bits(p: Mapping[str, float]) -> float:
    return -sum(v * math.log2(v) for v in p.values() if v > 0)


def _states(qs: Sequence[Mapping[str, float]]) -> list[str]:
    keys: list[str] = []
    for q in qs:
        for k in q:
            if k not in keys:
                keys.append(k)
    return keys


def mixture_mi(q1_runs: Sequence[Mapping[str, float]], q2_runs: Sequence[Mapping[str, float]]) -> dict:
    """Soft (logprob-based) decomposition at one turn across N paired runs.

    Within a run the two agents are sampled independently given their contexts,
    so p(a1,a2 | run r) = q1_r(a1) q2_r(a2). Across runs:
        p1 = mean_r q1_r,  p2 = mean_r q2_r,  p12 = mean_r q1_r (x) q2_r
    Dependence (I > 0) can only come from runs whose contexts co-vary.
    """

    n = len(q1_runs)
    if n == 0 or n != len(q2_runs):
        raise ValueError("need the same, non-zero number of runs for both agents")
    s1, s2 = _states(q1_runs), _states(q2_runs)
    p1 = {a: sum(q.get(a, 0.0) for q in q1_runs) / n for a in s1}
    p2 = {b: sum(q.get(b, 0.0) for q in q2_runs) / n for b in s2}
    joint = {(a, b): sum(q1.get(a, 0.0) * q2.get(b, 0.0) for q1, q2 in zip(q1_runs, q2_runs)) / n
             for a in s1 for b in s2}
    return _decompose(p1, p2, joint, n)


def shuffled_mi(q1_runs: Sequence[Mapping[str, float]], q2_runs: Sequence[Mapping[str, float]]) -> dict:
    """Same decomposition with A1 of run r paired with A2 of every run r' != r (exact average)."""

    n = len(q1_runs)
    if n < 2:
        raise ValueError("shuffled pairing needs at least two runs")
    s1, s2 = _states(q1_runs), _states(q2_runs)
    sum1 = {a: sum(q.get(a, 0.0) for q in q1_runs) for a in s1}
    sum2 = {b: sum(q.get(b, 0.0) for q in q2_runs) for b in s2}
    diag = {(a, b): sum(q1.get(a, 0.0) * q2.get(b, 0.0) for q1, q2 in zip(q1_runs, q2_runs))
            for a in s1 for b in s2}
    joint = {(a, b): (sum1[a] * sum2[b] - diag[(a, b)]) / (n * (n - 1)) for a in s1 for b in s2}
    p1 = {a: sum(joint[(a, b)] for b in s2) for a in s1}
    p2 = {b: sum(joint[(a, b)] for a in s1) for b in s2}
    return _decompose(p1, p2, joint, n)


def hard_mi(actions1: Sequence[str], actions2: Sequence[str]) -> dict:
    """Plug-in decomposition on realised actions (counts), with Miller-Madow bias correction."""

    n = len(actions1)
    if n == 0 or n != len(actions2):
        raise ValueError("need the same, non-zero number of runs for both agents")
    c1: dict[str, int] = {}
    c2: dict[str, int] = {}
    c12: dict[tuple[str, str], int] = {}
    for a, b in zip(actions1, actions2):
        c1[a] = c1.get(a, 0) + 1
        c2[b] = c2.get(b, 0) + 1
        c12[(a, b)] = c12.get((a, b), 0) + 1
    p1 = {k: v / n for k, v in c1.items()}
    p2 = {k: v / n for k, v in c2.items()}
    joint = {k: v / n for k, v in c12.items()}
    out = _decompose(p1, p2, joint, n)
    correction = (len(c12) - len(c1) - len(c2) + 1) / (2 * n * LN2)
    out["I_miller_madow_bits"] = out["I_bits"] - correction
    return out


def _decompose(p1: Mapping, p2: Mapping, joint: Mapping, n: int) -> dict:
    h1, h2 = entropy_bits(p1), entropy_bits(p2)
    h12 = -sum(v * math.log2(v) for v in joint.values() if v > 0)
    mi = sum(v * math.log2(v / (p1[a] * p2[b])) for (a, b), v in joint.items()
             if v > 0 and p1[a] > 0 and p2[b] > 0)
    return {
        "n_runs": n,
        "H1_bits": h1,
        "H2_bits": h2,
        "sum_H_bits": h1 + h2,
        "I_bits": max(mi, 0.0),
        "H_system_bits": h1 + h2 - max(mi, 0.0),
        "H_joint_direct_bits": h12,
        "p1": dict(p1),
        "p2": dict(p2),
    }


def bootstrap(stat, paired: Sequence[tuple], *, resamples: int = 1000, seed: int = 0,
              keys: Sequence[str] = ("I_bits", "H_system_bits", "H1_bits", "H2_bits")) -> dict:
    """Percentile 95% CI by resampling runs (pairs stay together)."""

    rng = random.Random(seed)
    n = len(paired)
    samples: dict[str, list[float]] = {k: [] for k in keys}
    for _ in range(resamples):
        pick = [paired[rng.randrange(n)] for _ in range(n)]
        try:
            result = stat([p[0] for p in pick], [p[1] for p in pick])
        except ValueError:
            continue
        for k in keys:
            samples[k].append(result[k])
    ci = {}
    for k, values in samples.items():
        values.sort()
        if len(values) < 20:
            ci[k] = (None, None)
            continue
        ci[k] = (values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1])
    return ci


def point_mass(state: str) -> dict[str, float]:
    return {state: 1.0}
