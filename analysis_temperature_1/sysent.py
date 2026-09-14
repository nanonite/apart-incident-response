"""System-level entropy estimators, reverse-engineered from tables_full/system_entropy.csv (verified in s02).

For one (model, condition, turn):
  * paired runs  = seeds where both A1 and A2 have a non-error row (action not null; `done` rows count, q_DONE=1).
  * soft marginals p_i = mean over paired runs of q_i,r (6 action classes incl. DONE; missing q -> 0).
  * soft joint    P(x1,x2) = mean_r q1_r(x1) q2_r(x2)   (mixture of per-run product distributions)
  * I = H(p1)+H(p2)-H(P); H_system = H(P).
    Because each run contributes a product, I is the dependence induced by the run index (both agents
    shifting together across runs), not a within-run coupling.
  * I_shuffled: same, with the joint averaged over all ordered cross-seed pairs (r != s), computed exactly.
  * hard_*: plug-in on realised action classes over paired runs; Miller-Madow:
    I_MM = I_plugin + [(K1-1)+(K2-1)-(K12-1)] / (2 n ln 2), K = number of non-empty bins.
  * tokH_Ai_mean: mean over runs of mean_H_renorm_bits for rows with tokens; tokS: same for surprisal.
"""
import numpy as np
import pandas as pd

from common import ACTION_CLASSES, Q_COLS, entropy_bits


def H(p) -> float:
    return float(entropy_bits(np.asarray(p, float).ravel()))


def soft_I(q1: np.ndarray, q2: np.ndarray) -> tuple[float, float, float, float, float]:
    n = len(q1)
    p1, p2 = q1.mean(0), q2.mean(0)
    J = np.einsum("ri,rj->ij", q1, q2) / n
    h1, h2, hj = H(p1), H(p2), H(J)
    I = h1 + h2 - hj
    if n > 1:
        Js = (np.outer(q1.sum(0), q2.sum(0)) - n * J) / (n * (n - 1))
        Ish = h1 + h2 - H(Js)
    else:
        Ish = np.nan
    return h1, h2, I, hj, Ish


def hard_I(a1: np.ndarray, a2: np.ndarray):
    n = len(a1)
    idx = {k: i for i, k in enumerate(ACTION_CLASSES)}
    ct = np.zeros((len(ACTION_CLASSES), len(ACTION_CLASSES)))
    for x, y in zip(a1, a2):
        ct[idx[x], idx[y]] += 1
    P = ct / n
    m1, m2 = P.sum(1), P.sum(0)
    h1, h2, hj = H(m1), H(m2), H(P)
    I = h1 + h2 - hj
    k1, k2, kj = (m1 > 0).sum(), (m2 > 0).sum(), (P > 0).sum()
    mm = I + ((k1 - 1) + (k2 - 1) - (kj - 1)) / (2 * n * np.log(2))
    return h1, h2, I, mm, hj


def paired_arrays(g: pd.DataFrame):
    """g: calls rows of one model x condition x turn. Returns seeds, q1, q2, a1, a2."""
    ok = g[g.action.notna()]
    q = ok.set_index(["seed", "agent"])[Q_COLS].fillna(0.0)
    a = ok.set_index(["seed", "agent"])["action_class"]
    s1 = set(ok.loc[ok.agent == "A1", "seed"])
    s2 = set(ok.loc[ok.agent == "A2", "seed"])
    seeds = np.array(sorted(s1 & s2))
    if len(seeds) == 0:
        return seeds, None, None, None, None
    q1 = q.xs("A1", level="agent").loc[seeds].to_numpy()
    q2 = q.xs("A2", level="agent").loc[seeds].to_numpy()
    a1 = a.xs("A1", level="agent").loc[seeds].to_numpy()
    a2 = a.xs("A2", level="agent").loc[seeds].to_numpy()
    return seeds, q1, q2, a1, a2


def turn_stats(g: pd.DataFrame) -> dict:
    seeds, q1, q2, a1, a2 = paired_arrays(g)
    out = dict(runs_present=g.seed.nunique(), runs_paired=len(seeds))
    if len(seeds) >= 2:  # the reference table leaves every paired statistic NaN when runs_paired < 2
        h1, h2, I, hj, Ish = soft_I(q1, q2)
        out.update(H1_bits=h1, H2_bits=h2, sum_H_bits=h1 + h2, I_bits=I, H_system_bits=hj,
                   I_shuffled_bits=Ish, I_minus_shuffled_bits=I - Ish)
        hh1, hh2, hI, hmm, hhj = hard_I(a1, a2)
        out.update(hard_H1_bits=hh1, hard_H2_bits=hh2, hard_I_bits=hI, hard_I_miller_madow_bits=hmm,
                   hard_H_system_bits=hhj)
        for i, qq in ((1, q1), (2, q2)):
            for k, v in zip(ACTION_CLASSES, qq.mean(0)):
                out[f"p{i}_{k}"] = v
    for ag in ("A1", "A2"):
        t = g[(g.agent == ag) & g.has_tokens]
        out[f"tokH_{ag}_mean"] = t.mean_H_renorm_bits.mean() if len(t) else np.nan
        out[f"tokS_{ag}_mean"] = t.mean_surprisal_bits.mean() if len(t) else np.nan
        out[f"tokH_{ag}_n"] = len(t)
    return out


def system_table(calls: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (m, c, t), g in calls.groupby(["model", "condition", "turn"]):
        rows.append(dict(model=m, condition=c, turn=t, **turn_stats(g)))
    return pd.DataFrame(rows)
