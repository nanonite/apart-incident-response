"""E3 — prompt-form paired continuous inference for Jev Choice replay (#184).

Offline. Aggregates complete real/placebo pairs within each prompt form, then
weights distinct forms equally: the primary estimate is the equal-form mean, with
a form-mean t interval (df = k-1) and an exhaustive two-sided cluster sign-flip
p-value. The existing binary McNemar/Newcombe functions are untouched. The J3
ISO-FULL regression is an offline method demonstration, not causal evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from typing import Any, Mapping, Sequence

from . import jev_replay as jr


CONTRAST_VERSION = "jev-replay-contrast-v1"

#: Two-sided 95% Student-t critical values for small df.
T_CRITICAL_975 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
    9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074,
    23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045,
    30: 2.042,
}


def t_critical_975(df: int) -> float:
    return T_CRITICAL_975.get(df, 1.960)


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _sd(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def sign_flip_two_sided(values: Sequence[float]) -> dict[str, Any]:
    """Exhaustive two-sided cluster sign-flip test on k form means."""

    k = len(values)
    if k == 0:
        return {"k": 0, "observed": None, "p_value": None, "min_p_value": None, "permutations": 0}
    observed = sum(values) / k
    count = 0
    for mask in range(1 << k):
        signed = sum((1 if (mask >> index) & 1 else -1) * values[index] for index in range(k)) / k
        if abs(signed) >= abs(observed) - 1e-12:
            count += 1
    permutations = 1 << k
    return {"k": k, "observed": observed, "p_value": count / permutations,
            "min_p_value": 2 / permutations, "permutations": permutations}


def _bootstrap_form_ci(form_means: Sequence[float], *, iterations: int, seed: int) -> list[float] | None:
    if len(form_means) < 2:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(iterations):
        sample = [form_means[rng.randrange(len(form_means))] for _ in form_means]
        means.append(sum(sample) / len(sample))
    means.sort()
    return [means[int(0.025 * iterations)], means[int(0.975 * iterations) - 1]]


def _sign_test(form_means: Sequence[float]) -> dict[str, Any]:
    non_zero = [value for value in form_means if value != 0]
    if not non_zero:
        return {"non_zero_forms": 0, "positive": 0, "two_sided_p": None}
    positive = sum(1 for value in non_zero if value > 0)
    n = len(non_zero)
    tail = sum(math.comb(n, index) for index in range(min(positive, n - positive) + 1)) / (2 ** n)
    return {"non_zero_forms": n, "positive": positive, "two_sided_p": min(1.0, 2 * tail)}


def paired_continuous_contrast(events: Sequence[Mapping[str, Any]], *, outcome: str = "entropy_bits",
                               left: str = "real", right: str = "placebo", min_pairs_per_form: int = 1,
                               bootstrap_iterations: int = 2000, seed: int = 157,
                               required_forms: int | Sequence[str] | None = None,
                               fail_on_invalid: bool = True) -> dict[str, Any]:
    """Equal-form paired continuous contrast over complete (left, right) pairs.

    Fails closed on duplicate events, mixed protocols, or (by default) any event
    that fails schema validation. ``required_forms`` may be an exact collection of
    frozen form IDs, in which case the analyzed forms must match it exactly.
    Guards are *not* used to filter this estimate; see :func:`guard_evaluation`.
    """

    if events:
        jr.assert_no_duplicate_events(events)
        jr.assert_single_protocol(events)
    invalid_events = []
    for event in events:
        problems = jr.validate_event(event)
        if problems:
            invalid_events.append({"event_id": event.get("event_id"), "problems": sorted(set(problems))})
    if invalid_events and fail_on_invalid:
        raise ValueError(f"invalid_replay_events: {invalid_events}")

    form_values: dict[str, list[float]] = defaultdict(list)
    form_instances: dict[str, list[str]] = defaultdict(list)
    missingness = {"events": len(events), "usable_pairs": 0, "invalid_events": len(invalid_events),
                   "incomplete_pairs": 0, "forms_below_min_pairs": 0, "invalid": invalid_events}
    invalid_ids = {item["event_id"] for item in invalid_events}
    for event in events:
        if event.get("event_id") in invalid_ids:
            continue
        branches = event.get("branches", {})
        left_branch, right_branch = branches.get(left), branches.get(right)
        if not left_branch or not right_branch or left_branch.get("status") != "complete" \
                or right_branch.get("status") != "complete":
            missingness["incomplete_pairs"] += 1
            continue
        value_left, value_right = left_branch.get(outcome), right_branch.get(outcome)
        if value_left is None or value_right is None:
            missingness["incomplete_pairs"] += 1
            continue
        form = str(event.get("prompt_form_id"))
        form_values[form].append(float(value_left) - float(value_right))
        form_instances[form].append(str(event.get("instance_id")))
        missingness["usable_pairs"] += 1

    form_effects: dict[str, dict[str, Any]] = {}
    form_means: list[float] = []
    instance_weights: list[float] = []
    for form, values in sorted(form_values.items()):
        if len(values) < min_pairs_per_form:
            missingness["forms_below_min_pairs"] += 1
            continue
        mean = _mean(values)
        form_means.append(mean)
        form_effects[form] = {"n_pairs": len(values), "d_f": mean, "sd": _sd(values),
                              "instance_ids": sorted(set(form_instances[form]))}
        instance_weights.append(float(len(values)))

    k = len(form_means)
    form_mean = _mean(form_means)
    df = k - 1
    if k >= 2 and form_mean is not None:
        sd = _sd(form_means)
        half = t_critical_975(df) * (sd / math.sqrt(k))
        t_interval = [form_mean - half, form_mean + half]
    else:
        t_interval = None
    sign_flip = sign_flip_two_sided(form_means)
    weighted = None
    if form_means and sum(instance_weights) > 0:
        weighted = sum(mean * weight for mean, weight in zip(form_means, instance_weights)) / sum(instance_weights)
    if required_forms is None:
        complete_forms, missing_forms, extra_forms = True, [], []
    elif isinstance(required_forms, int):
        complete_forms = k >= required_forms
        missing_forms, extra_forms = [], []
    else:
        allowed = set(required_forms)
        observed = set(form_effects)
        missing_forms = sorted(allowed - observed)
        extra_forms = sorted(observed - allowed)
        complete_forms = not missing_forms and not extra_forms
    return {
        "contrast_version": CONTRAST_VERSION,
        "outcome": outcome,
        "left": left,
        "right": right,
        "k_forms": k,
        "required_forms": list(required_forms) if isinstance(required_forms, (list, tuple, set))
        else required_forms,
        "complete_forms": complete_forms,
        "missing_forms": missing_forms,
        "extra_forms": extra_forms,
        "form_effects": form_effects,
        "form_mean": form_mean,
        "df": df,
        "t_interval_975": t_interval,
        "sign_flip": sign_flip,
        "minimum_two_sided_p": sign_flip["min_p_value"],
        "two_sided_only": True,
        "negative_effect": form_mean is not None and form_mean < 0,
        "directional_claim": bool(k >= 2 and form_mean is not None and form_mean < 0
                                  and sign_flip["p_value"] is not None and sign_flip["p_value"] < 0.05
                                  and complete_forms),
        "missingness": missingness,
        "sensitivities": {
            "label": "secondary; not the primary inference",
            "form_cluster_bootstrap_ci": _bootstrap_form_ci(form_means, iterations=bootstrap_iterations,
                                                            seed=seed),
            "sign_test_on_form_means": _sign_test(form_means),
            "instance_weighted_mean": weighted,
        },
        "assumptions": [
            "unit is the prompt form; repeated queries within a form are averaged, not independent",
            "complete real/placebo pairs only; guards are evaluated separately and never filter this estimate",
            f"small k ({k}) gives a minimum two-sided sign-flip p of 2/2^k",
            "if a form is lost the result is incomplete",
        ],
    }


def guard_evaluation(events: Sequence[Mapping[str, Any]], *, delta: float = 0.0,
                     epsilon: float = 0.01) -> dict[str, Any]:
    """Useful-information guards, evaluated separately from the primary contrast.

    Never used to filter the entropy estimate: every pre-eligible, valid
    real/placebo pair enters the primary analysis, and guard violations are
    reported alongside it.
    """

    rows: list[dict[str, Any]] = []
    per_form: dict[str, dict[str, int]] = defaultdict(lambda: {"events": 0, "target_ok": 0, "mass_ok": 0,
                                                               "useful_info": 0})
    for event in events:
        if jr.validate_event(event):
            continue
        branches = event.get("branches", {})
        real, placebo = branches.get("real"), branches.get("placebo")
        if not real or not placebo or real.get("status") != "complete" or placebo.get("status") != "complete":
            continue
        entropy_diff = float(real["entropy_bits"]) - float(placebo["entropy_bits"])
        p_target_diff = float(real["p_target"]) - float(placebo["p_target"])
        mass_diff = float(real["feasible_mass"]) - float(placebo["feasible_mass"])
        target_ok = p_target_diff >= delta
        mass_ok = mass_diff >= -epsilon
        useful = entropy_diff < 0 and target_ok and mass_ok
        form = str(event.get("prompt_form_id"))
        counters = per_form[form]
        counters["events"] += 1
        counters["target_ok"] += int(target_ok)
        counters["mass_ok"] += int(mass_ok)
        counters["useful_info"] += int(useful)
        rows.append({"event_id": event.get("event_id"), "form": form, "entropy_diff": entropy_diff,
                     "p_target_diff": p_target_diff, "feasible_mass_diff": mass_diff,
                     "target_guard_ok": target_ok, "mass_guard_ok": mass_ok, "useful_info": useful})
    return {
        "delta": delta,
        "epsilon": epsilon,
        "filtering": "never used to filter the primary estimate",
        "events": rows,
        "per_form": dict(sorted(per_form.items())),
        "target_violations": sum(1 for row in rows if not row["target_guard_ok"]),
        "mass_violations": sum(1 for row in rows if not row["mass_guard_ok"]),
        "useful_info_events": sum(1 for row in rows if row["useful_info"]),
        "note": "an entropy drop with no target-probability improvement is not useful uptake",
    }


def j3_iso_full_regression(journal: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Offline method demonstration: J3 ISO-minus-FULL entropy per form.

    Not causal replay evidence and not a real-placebo power estimate.
    """

    by_instance: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in journal:
        if row.get("status") != "complete":
            continue
        by_instance[str(row.get("instance_id"))][str(row.get("condition"))] = row
    form_deltas: dict[str, list[float]] = defaultdict(list)
    for instance_id, conditions in by_instance.items():
        iso, full = conditions.get("ISO"), conditions.get("FULL")
        if not iso or not full:
            continue
        form = str(iso.get("request_hash"))
        form_deltas[form].append(jr.entropy_bits(iso["probabilities"]) - jr.entropy_bits(full["probabilities"]))
    form_means = [_mean(values) for _, values in sorted(form_deltas.items())]
    form_means = [value for value in form_means if value is not None]
    k = len(form_means)
    form_mean = _mean(form_means)
    interval = None
    if k >= 2 and form_mean is not None:
        half = t_critical_975(k - 1) * (_sd(form_means) / math.sqrt(k))
        interval = [form_mean - half, form_mean + half]
    return {
        "label": "offline method regression on J3 ISO-FULL; not causal replay evidence",
        "k_forms": k,
        "form_means": form_means,
        "form_mean": form_mean,
        "t_interval_975": interval,
        "sign_flip": sign_flip_two_sided(form_means),
    }


def contrast_manifest_hash(contrast: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(contrast, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()


__all__ = [
    "CONTRAST_VERSION", "T_CRITICAL_975", "t_critical_975", "sign_flip_two_sided",
    "paired_continuous_contrast", "guard_evaluation", "j3_iso_full_regression", "contrast_manifest_hash",
]
