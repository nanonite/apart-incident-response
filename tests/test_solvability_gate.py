import unittest

from apart_incident_response.communication_protocol import ReasoningComplexity
from apart_incident_response.solvability_gate import (
    MIN_VALID_RUNS_FOR_VIABLE,
    FullOnlyResult,
    SolvabilityGate,
)


def _result(*, valid: bool, success: bool) -> FullOnlyResult:
    return FullOnlyResult(
        instance_id="hypothesis-1",
        family="hypothesis",
        seed=1,
        model="ling",
        task_success=success,
        valid=valid,
        parse_ok=success,
    )


class TestSolvabilityGateMinimum(unittest.TestCase):
    def setUp(self):
        self.gate = SolvabilityGate(lambda _: None)

    def test_single_valid_success_is_insufficient(self):
        self.assertEqual(
            self.gate._compute_verdict([_result(valid=True, success=True)]),
            "insufficient",
        )

    def test_two_valid_successes_can_be_viable(self):
        results = [_result(valid=True, success=True) for _ in range(MIN_VALID_RUNS_FOR_VIABLE)]
        self.assertEqual(self.gate._compute_verdict(results), "viable")

    def test_stratum_with_one_valid_run_is_not_viable(self):
        stratum = self.gate._build_stratum_result(
            "hypothesis", ReasoningComplexity.LOW, "ling",
            [_result(valid=True, success=True)],
        )
        self.assertEqual(stratum.verdict, "insufficient")
        self.assertIsNone(stratum.success_rate)

    def test_overall_gate_blocks_when_any_stratum_is_insufficient(self):
        stratum = self.gate._build_stratum_result(
            "hypothesis", ReasoningComplexity.LOW, "ling",
            [_result(valid=True, success=True)],
        )
        verdict = self.gate.gate_verdict([stratum])
        self.assertEqual(verdict["recommendation"], "extend_pilot_insufficient_strata")
        self.assertEqual(verdict["insufficient_count"], 1)


if __name__ == "__main__":
    unittest.main()
