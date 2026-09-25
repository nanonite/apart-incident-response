import unittest
from pathlib import Path

from apart_incident_response import jev_openrouter_catalog as catalog


def synthetic_catalog(*, target_present=True, free_present=False,
                      prompt="0.00000006", completion="0.00000018"):
    entries = {
        catalog.PAID_LING_MODEL: ({"present": True, "prompt_usd_per_tok": prompt,
                                   "completion_usd_per_tok": completion,
                                   "context_length": 262144} if target_present else
                                  {"present": False}),
        catalog.FREE_LING_MODEL: {"present": True} if free_present else {"present": False},
    }
    return {"catalog_version": catalog.CATALOG_VERSION, "catalog_url": catalog.CATALOG_URL,
            "model_count": 460, "entries": entries,
            "requested_slugs": [catalog.PAID_LING_MODEL, catalog.FREE_LING_MODEL]}


class CatalogGateTests(unittest.TestCase):
    def test_gate_passes_for_present_paid_sku_with_pricing(self):
        gate = catalog.catalog_availability_gate(catalog.PAID_LING_MODEL,
                                                 catalog=synthetic_catalog())
        self.assertTrue(gate["ok"], gate["failed"])
        names = {check["check"] for check in gate["checks"]}
        self.assertEqual(names, {"catalog_reachable", "target_sku_present",
                                 "target_pricing_present"})
        self.assertFalse(gate["diagnostics"]["free_sku_present_in_routable_catalog"])
        self.assertIn("consistent with the observed HTTP 404",
                      gate["diagnostics"]["free_sku_note"])

    def test_gate_fails_when_target_absent(self):
        gate = catalog.catalog_availability_gate(catalog.PAID_LING_MODEL,
                                                 catalog=synthetic_catalog(target_present=False))
        self.assertFalse(gate["ok"])
        self.assertIn("target_sku_present", gate["failed"])

    def test_gate_fails_on_missing_or_zero_pricing(self):
        gate = catalog.catalog_availability_gate(
            catalog.PAID_LING_MODEL,
            catalog=synthetic_catalog(prompt="0", completion="0.00000018"))
        self.assertFalse(gate["ok"])
        self.assertIn("target_pricing_present", gate["failed"])

    def test_free_sku_presence_is_diagnostic_only(self):
        gate = catalog.catalog_availability_gate(catalog.PAID_LING_MODEL,
                                                 catalog=synthetic_catalog(free_present=True))
        self.assertTrue(gate["ok"], gate["failed"])
        self.assertTrue(gate["diagnostics"]["free_sku_present_in_routable_catalog"])

    def test_gate_is_read_only_and_credential_free(self):
        gate = catalog.catalog_availability_gate(catalog.PAID_LING_MODEL,
                                                 catalog=synthetic_catalog())
        self.assertIn("no completion and no credential used", gate["gate_note"])
        source = Path(catalog.__file__).read_text(encoding="utf-8")
        self.assertNotIn("api_key", source)
        self.assertNotIn("Authorization", source)

    def test_record_gate_shape(self):
        fetched = synthetic_catalog()
        gate = catalog.catalog_availability_gate(catalog.PAID_LING_MODEL, catalog=fetched)
        record = catalog.record_gate(fetched, gate)
        self.assertEqual(record["catalog_version"], catalog.CATALOG_VERSION)
        self.assertEqual(record["model_count"], 460)
        self.assertIn(catalog.PAID_LING_MODEL, record["entries"])
        self.assertTrue(record["gate"]["ok"])


class PositiveRateTests(unittest.TestCase):
    def test_valid_rates_parse(self):
        self.assertEqual(catalog.positive_rate("0.00000006"), 6e-08)
        self.assertEqual(catalog.positive_rate("1"), 1.0)

    def test_malformed_rates_return_none_without_raising(self):
        for value in (None, 0.06, 6e-08, 0, -1, True, [], {}, "abc", "", "  ",
                      "NaN", "nan", "inf", "-inf", "Infinity", "0", "0.0", "-0.1",
                      "-1e-9", "1e999", "not-a-number", b"0.06"):
            with self.subTest(value=value):
                self.assertIsNone(catalog.positive_rate(value))


class AdversarialCatalogGateTests(unittest.TestCase):
    """Malformed external payloads must surface as named failed checks only."""

    def _gate(self, payload, *, target=catalog.PAID_LING_MODEL):
        return catalog.catalog_availability_gate(target, catalog=payload)

    def _assert_failed_closed(self, result, expected_failed):
        self.assertFalse(result["ok"])
        for name in expected_failed:
            self.assertIn(name, result["failed"])
        produced = {check["check"] for check in result["checks"]}
        self.assertTrue(produced.issubset(
            {"catalog_reachable", "target_sku_present", "target_pricing_present"}))

    def test_non_mapping_catalog_payloads(self):
        for payload in (None, [], "catalog", 42, 3.14, True,
                        {"entries": {catalog.PAID_LING_MODEL: {"present": True,
                                                               "prompt_usd_per_tok": "0.00000006",
                                                               "completion_usd_per_tok": "0.00000018"}}}):
            with self.subTest(payload=payload):
                result = self._gate(payload)
                self._assert_failed_closed(result, ["catalog_reachable"])

    def test_malformed_model_count(self):
        base = lambda count: {"model_count": count,
                              "entries": synthetic_catalog()["entries"]}
        for count in ("460", 12.5, None, True, False, 0, -5, [], {}, float("nan"), "abc"):
            with self.subTest(model_count=count):
                result = self._gate(base(count))
                self._assert_failed_closed(result, ["catalog_reachable"])

    def test_malformed_entries(self):
        good_count = {"model_count": 460}
        for entries in (None, [], "entries", 42, {"inclusionai/ling-3.0-flash-vl": "x"},
                        {catalog.PAID_LING_MODEL: None},
                        {catalog.PAID_LING_MODEL: ["present"]},
                        {catalog.PAID_LING_MODEL: {"present": 1}},
                        {catalog.PAID_LING_MODEL: {"present": "true"}},
                        {catalog.PAID_LING_MODEL: {}}):
            with self.subTest(entries=entries):
                payload = dict(good_count, entries=entries)
                result = self._gate(payload)
                self._assert_failed_closed(result, ["target_sku_present"])

    def test_missing_pricing_fields(self):
        for target in ({"present": True},
                       {"present": True, "prompt_usd_per_tok": "0.00000006"},
                       {"present": True, "completion_usd_per_tok": "0.00000018"}):
            with self.subTest(target=target):
                payload = {"model_count": 460,
                           "entries": {catalog.PAID_LING_MODEL: target}}
                result = self._gate(payload)
                self._assert_failed_closed(result, ["target_pricing_present"])

    def test_nonstring_nonnumeric_nan_inf_and_nonpositive_pricing(self):
        bad_rates = (None, 0.06, 6e-08, 0, -1, True, [], {}, "abc", "", "  ",
                     "NaN", "nan", "inf", "-inf", "Infinity", "0", "0.0", "-0.1",
                     "-1e-9", "1e999")
        for bad in bad_rates:
            with self.subTest(prompt=bad):
                payload = {"model_count": 460,
                           "entries": {catalog.PAID_LING_MODEL: {
                               "present": True,
                               "prompt_usd_per_tok": bad,
                               "completion_usd_per_tok": "0.00000018"}}}
                result = self._gate(payload)
                self._assert_failed_closed(result, ["target_pricing_present"])
            with self.subTest(completion=bad):
                payload = {"model_count": 460,
                           "entries": {catalog.PAID_LING_MODEL: {
                               "present": True,
                               "prompt_usd_per_tok": "0.00000006",
                               "completion_usd_per_tok": bad}}}
                result = self._gate(payload)
                self._assert_failed_closed(result, ["target_pricing_present"])

    def test_malformed_free_entry_never_raises(self):
        payload = {"model_count": 460,
                   "entries": {catalog.PAID_LING_MODEL: {
                       "present": True, "prompt_usd_per_tok": "0.00000006",
                       "completion_usd_per_tok": "0.00000018"},
                       catalog.FREE_LING_MODEL: ["broken"]}}
        result = self._gate(payload)
        self.assertTrue(result["ok"], result["failed"])
        self.assertFalse(result["diagnostics"]["free_sku_present_in_routable_catalog"])

    def test_unhashable_target_slug_never_raises(self):
        payload = synthetic_catalog()
        result = self._gate(payload, target=["not-a-slug"])
        self.assertFalse(result["ok"])

    def test_gate_never_raises_on_any_adversarial_payload(self):
        adversarial = [None, [], "x", 42, True, {"model_count": "1", "entries": []},
                       {"model_count": [1], "entries": {}},
                       {"model_count": 460, "entries": []},
                       {"model_count": 460, "entries": "x"},
                       {"model_count": 460},
                       {"model_count": 460, "entries": {catalog.PAID_LING_MODEL: 7}},
                       {"model_count": 460, "entries": {catalog.PAID_LING_MODEL:
                                                        {"present": True,
                                                         "prompt_usd_per_tok": object(),
                                                         "completion_usd_per_tok": "1"}}}]
        for payload in adversarial:
            with self.subTest(payload=payload):
                result = catalog.catalog_availability_gate(catalog.PAID_LING_MODEL,
                                                           catalog=payload)
                self.assertFalse(result["ok"])
                self.assertTrue(result["checks"])
                self.assertEqual(result["failed"],
                                 [c["check"] for c in result["checks"] if not c["ok"]])

    def test_exact_paid_sku_and_frozen_pricing_not_loosened(self):
        self.assertEqual(catalog.PAID_LING_MODEL, "inclusionai/ling-3.0-flash-vl")
        self.assertEqual(catalog.FREE_LING_MODEL, "inclusionai/ling-3.0-flash-vl:free")
        gate = catalog.catalog_availability_gate(catalog.PAID_LING_MODEL,
                                                 catalog=synthetic_catalog())
        self.assertTrue(gate["ok"])
        detail = next(c for c in gate["checks"]
                      if c["check"] == "target_pricing_present")["detail"]
        self.assertEqual(detail, {"prompt_usd_per_tok": 6e-08,
                                  "completion_usd_per_tok": 1.8e-07})


if __name__ == "__main__":
    unittest.main()
