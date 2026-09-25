"""OpenRouter model catalog / availability gate (nonexperimental, read-only).

Fetches OpenRouter's public model catalog (no credentials, no completions)
and verifies that an experimental model SKU is routable before any
experimental collection is authorized. This exists because OpenRouter's
public model page can advertise a free SKU that is absent from the routable
catalog (observed 2026-09-24 for ``inclusionai/ling-3.0-flash-vl:free``,
which returned HTTP 404 during the authorized v6 run).

The gate is invoked by the v7 transport probe and by the v7 live preflight.
Offline verification uses recorded probe/catalog evidence instead of a
network fetch; this module never runs implicitly.
"""

from __future__ import annotations

import json
import math
import urllib.request
from collections.abc import Mapping
from typing import Any, Iterable


CATALOG_URL = "https://openrouter.ai/api/v1/models"
CATALOG_VERSION = "openrouter-catalog-gate-v1"
DEFAULT_TIMEOUT_SECONDS = 30.0

#: Slugs inspected by the v7 probe/gate.
PAID_LING_MODEL = "inclusionai/ling-3.0-flash-vl"
FREE_LING_MODEL = "inclusionai/ling-3.0-flash-vl:free"
INSPECTED_SLUGS = (PAID_LING_MODEL, FREE_LING_MODEL)


def fetch_model_catalog(*, timeout: float = DEFAULT_TIMEOUT_SECONDS,
                        slugs: Iterable[str] = INSPECTED_SLUGS) -> dict[str, Any]:
    """GET the public OpenRouter catalog (one request, no credentials).

    Only the requested slugs' sanitized entries are retained; the full
    catalog and any transport details are discarded.
    """

    wanted = tuple(slugs)
    request = urllib.request.Request(CATALOG_URL, method="GET",
                                     headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    models = payload.get("data")
    if not isinstance(models, list):
        raise ValueError("openrouter catalog payload missing model list")
    by_id = {str(model.get("id")): model for model in models if isinstance(model, dict)}
    entries: dict[str, dict[str, Any]] = {}
    for slug in wanted:
        model = by_id.get(slug)
        if model is None:
            entries[slug] = {"present": False}
            continue
        pricing = model.get("pricing") or {}
        entries[slug] = {
            "present": True,
            "prompt_usd_per_tok": pricing.get("prompt"),
            "completion_usd_per_tok": pricing.get("completion"),
            "context_length": model.get("context_length"),
        }
    return {"catalog_version": CATALOG_VERSION, "catalog_url": CATALOG_URL,
            "model_count": len(by_id), "entries": entries, "requested_slugs": list(wanted)}


def positive_rate(value: Any) -> float | None:
    """Parse a catalog price string; None for anything malformed.

    Strict by contract: only finite, positive ``str`` rates are accepted.
    Non-strings, non-numeric text, NaN, infinities, zero and negatives all
    yield None so callers fail closed instead of raising.
    """

    if not isinstance(value, str):
        return None
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(rate) or rate <= 0.0:
        return None
    return rate


def catalog_availability_gate(target_slug: str, *, catalog: Mapping[str, Any],
                              free_slug: str | None = FREE_LING_MODEL) -> dict[str, Any]:
    """Named-check gate: the target SKU must be routable with usable pricing.

    Fail-closed by contract: malformed external catalog payloads (bad
    ``model_count``, missing/non-string/non-numeric/non-finite/non-positive
    pricing, malformed ``entries``) can never escape as ``ValueError``,
    ``TypeError`` or any other exception — they surface only as named failed
    checks (``catalog_reachable``, ``target_sku_present``,
    ``target_pricing_present``) so the live preflight blocks before any
    completion call. ``free_slug`` presence is diagnostic only.
    """

    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    def failed_result(detail: str) -> dict[str, Any]:
        present = {item["check"] for item in checks}
        for name in ("catalog_reachable", "target_sku_present", "target_pricing_present"):
            if name not in present:
                check(name, False, detail)
        return {"ok": False, "checks": checks,
                "failed": [item["check"] for item in checks if not item["ok"]],
                "target_slug": target_slug,
                "diagnostics": {"free_sku_present_in_routable_catalog": False,
                                "free_sku_note": "malformed catalog payload",
                                "target_entry": {}},
                "gate_note": ("malformed catalog payload failed closed; read-only check; "
                              "no completion and no credential used")}

    try:
        if not isinstance(catalog, Mapping):
            return failed_result("catalog payload is not a mapping")
        count = catalog.get("model_count")
        count_ok = isinstance(count, int) and not isinstance(count, bool) and count > 0
        check("catalog_reachable", count_ok,
              count if count_ok else f"malformed model_count: {type(count).__name__}")
        entries = catalog.get("entries")
        entries_ok = isinstance(entries, Mapping)
        target = entries.get(target_slug) if entries_ok else None
        target_ok = isinstance(target, Mapping) and target.get("present") is True
        check("target_sku_present", target_ok, target_slug)
        prompt_rate = completion_rate = None
        if target_ok:
            prompt_rate = positive_rate(target.get("prompt_usd_per_tok"))
            completion_rate = positive_rate(target.get("completion_usd_per_tok"))
        pricing_ok = target_ok and prompt_rate is not None and completion_rate is not None
        check("target_pricing_present", pricing_ok,
              {"prompt_usd_per_tok": prompt_rate, "completion_usd_per_tok": completion_rate})
        free = entries.get(free_slug) if (entries_ok and free_slug is not None) else None
        free_present = isinstance(free, Mapping) and free.get("present") is True
        target_entry = dict(target) if isinstance(target, Mapping) else {}
    except Exception as exc:  # absolute belt: no exception may escape the gate
        return failed_result(f"gate_error: {type(exc).__name__}")

    return {"ok": all(item["ok"] for item in checks), "checks": checks,
            "failed": [item["check"] for item in checks if not item["ok"]],
            "target_slug": target_slug,
            "diagnostics": {
                "free_sku_present_in_routable_catalog": free_present,
                "free_sku_note": ("absence of the free SKU from the routable catalog is "
                                  "consistent with the observed HTTP 404 in the v6 run; "
                                  "presence is informational only"),
                "target_entry": target_entry},
            "gate_note": "read-only catalog lookup; no completion and no credential used"}


def record_gate(catalog: Mapping[str, Any], gate: Mapping[str, Any]) -> dict[str, Any]:
    """Sanitized catalog+gate record for probe artifacts and registrations."""

    return {"catalog_version": catalog.get("catalog_version"),
            "catalog_url": catalog.get("catalog_url"),
            "model_count": catalog.get("model_count"),
            "entries": dict(catalog.get("entries") or {}),
            "gate": dict(gate)}


__all__ = [
    "CATALOG_URL", "CATALOG_VERSION", "DEFAULT_TIMEOUT_SECONDS", "PAID_LING_MODEL",
    "FREE_LING_MODEL", "INSPECTED_SLUGS", "fetch_model_catalog", "positive_rate",
    "catalog_availability_gate", "record_gate",
]
