import copy
import json
import re
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import behavioral_discovery as bd
from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_choice_v2 as jc2
from apart_incident_response import jev_ling_writer_v3 as writer_v3
from apart_incident_response import jev_ling_writer_v5 as writer_v5
from apart_incident_response import jev_writer_exact_bridge_v5 as bridge
from apart_incident_response import jev_writer_ladder_v5 as ladder
from apart_incident_response import jev_replay_preregistration as pr
from apart_incident_response.communication_protocol import BatteryCondition
from apart_incident_response.communication_runner import AgentContext


_ISOLATION_DIR = tempfile.mkdtemp(prefix="bridge-test-")


def setUpModule():
    # Keep the preflight freshness checks independent of any real bridge run
    # artifacts: point the module defaults at a fresh temporary directory.
    bridge.DEFAULT_BRIDGE_JOURNAL = Path(_ISOLATION_DIR) / "bridge.jsonl"
    bridge.DEFAULT_BRIDGE_REPORT = Path(_ISOLATION_DIR) / "bridge-report.json"


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = json.loads((REPO_ROOT / "runs" / "epic-126"
                           / "jev-writer-ladder-preregistration-v5.json").read_text())
PIN = REGISTRATION["preregistration_hash"]
KEY = "openrouter-test-key-0123456789"


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.t += delay


class FakeResponse:
    def __init__(self, content="SILENCE", finish_reason=None):
        body = {"choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3}}
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class FakeReceiverClient:
    provider = "jev"
    endpoint = jc.JEV_SYSTEMONE_ENDPOINT
    max_retries = pr.JEV_REPLAY_MAX_RETRIES

    def __init__(self, *, max_physical_requests=34):
        self.max_physical_requests = max_physical_requests
        self.physical_attempts = 0
        self.calls = 0
        self.requests = []

    def complete(self, request):
        self.physical_attempts += 1
        self.calls += 1
        self.requests.append(request)
        question_id = next(iter(request["questions"]))
        option_ids = list(request["questions"][question_id]["criteria"])
        rest = 0.5 / (len(option_ids) - 1)
        probabilities = {option_id: (0.5 if index == 0 else rest)
                         for index, option_id in enumerate(option_ids)}
        return {"model": jc.JEV_DEFAULT_MODEL,
                "answers": {question_id: {"type": "choice", "choice": option_ids[0],
                                          "probabilities": probabilities, "confidence": 0.5}},
                "usage": {"input_tokens": 10, "output_tokens": 2}}


def _prompt(request):
    return json.loads(request.data)["messages"][0]["content"]


def owned_side_effect(capture=None, reject_agent=None):
    def respond(request, timeout=None):
        prompt = json.loads(_prompt(request))
        if capture is not None:
            capture.append(prompt)
        agent = "A" if prompt.get("is_finalizer") else "B"
        turn = prompt["turn"]
        if reject_agent is not None and agent == reject_agent and turn == 0:
            return FakeResponse("MESSAGE: invented-clue")
        clues = prompt["private_clues"]
        return FakeResponse(f"MESSAGE: {clues[0]}" if clues else "SILENCE")
    return respond


def empty_side_effect(request, timeout=None):
    return FakeResponse("")


def fail_verification():
    return {"ok": False, "failed": ["registration_verifies"], "checks": []}


def build(side_effect, *, writer=None, receiver_cap=None, writer_cap=None, api_key=KEY):
    instances = bridge.bridge_instances()
    plan = bridge.build_bridge_plan(instances, REGISTRATION)
    receiver = jc2.JevChoiceAdapterV2(
        FakeReceiverClient(max_physical_requests=receiver_cap or plan.jev_request_cap),
        model=pr.JEV_REPLAY_MODEL)
    clock = FakeClock()
    used_writer = writer or writer_v5.LingWriterClientV5(
        api_key=api_key, max_physical_requests=writer_cap or plan.ling_request_cap,
        clock=clock.now, sleep_fn=clock.sleep)
    verification = bridge.verify_bridge_preflight(plan, REGISTRATION, receiver, used_writer,
                                                  repo_root=REPO_ROOT, pinned_hash=PIN,
                                                  ling_key_present=True)
    return instances, receiver, plan, used_writer, verification, side_effect


def run(side_effect, *, approval="test", **kwargs):
    instances, receiver, plan, writer, verification, se = build(side_effect, **kwargs)
    with patch.object(writer_v5.urllib.request, "urlopen", side_effect=se):
        report = bridge.execute_bridge(plan, receiver, writer, verification, instances,
                                       approval=approval, pinned_hash=PIN, sleep_fn=lambda _: None)
    return report, receiver, writer, plan, verification


class PreflightTests(unittest.TestCase):
    def test_preflight_ok_named_checks(self):
        instances, receiver, plan, writer, verification, se = build(owned_side_effect())
        self.assertTrue(verification["ok"], verification["failed"])
        names = {c["check"] for c in verification["checks"]}
        for required in ("registration_verifies", "status_locked", "live_collection_not_authorized",
                         "source_hash_wellformed", "treatment_hash_wellformed", "manifest_seventeen",
                         "forms_six", "receiver_partition_matches_bridge",
                         "writer_partition_matches_bridge", "writer_parser_version_matches",
                         "seed_algorithm_matches", "token_budget_matches", "bridge_caps_frozen",
                         "combined_partition_non_overlapping", "combined_partition_within_total",
                         "journal_path_fresh", "report_path_fresh", "jev_credentials_present",
                         "ling_credentials_present", "prior_v1_v4_artifacts_present"):
            self.assertIn(required, names)
        self.assertEqual(receiver.client.max_physical_requests, plan.jev_request_cap)
        self.assertEqual(writer.max_physical_requests, plan.ling_request_cap)

    def test_tampered_registration_fails_before_calls(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["exact_bridge"]["token_budget"] = 96
        instances = bridge.bridge_instances()
        plan = bridge.build_bridge_plan(instances, tampered)
        receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(max_physical_requests=plan.jev_request_cap),
                                          model=pr.JEV_REPLAY_MODEL)
        writer = writer_v5.LingWriterClientV5(api_key=KEY, max_physical_requests=plan.ling_request_cap)
        verification = bridge.verify_bridge_preflight(plan, tampered, receiver, writer,
                                                      repo_root=REPO_ROOT, pinned_hash=PIN,
                                                      ling_key_present=True)
        self.assertFalse(verification["ok"])
        report = bridge.execute_bridge(plan, receiver, writer, verification, instances, approval="x")
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(writer.physical_attempts, 0)

    def test_wrong_source_and_treatment_hash_fail_before_calls(self):
        for mutate in (lambda d: d["generator"].__setitem__("source_files_hash", "0" * 64),
                       lambda d: d["generator"].__setitem__("treatment_hash", "0" * 64)):
            tampered = copy.deepcopy(REGISTRATION)
            mutate(tampered)
            instances = bridge.bridge_instances()
            plan = bridge.build_bridge_plan(instances, tampered)
            receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(max_physical_requests=plan.jev_request_cap),
                                              model=pr.JEV_REPLAY_MODEL)
            writer = writer_v5.LingWriterClientV5(api_key=KEY, max_physical_requests=plan.ling_request_cap)
            verification = bridge.verify_bridge_preflight(plan, tampered, receiver, writer,
                                                          repo_root=REPO_ROOT, pinned_hash=PIN,
                                                          ling_key_present=True)
            self.assertFalse(verification["ok"])

    def test_wrong_model_endpoint_protocol_parser_seed_budget_fail(self):
        # model/endpoint/protocol drift in the registration
        for mutate in (lambda d: d["model_and_protocol"].__setitem__("model", "jev-0.0.0"),
                       lambda d: d["model_and_protocol"].__setitem__("endpoint", "https://x.invalid"),
                       lambda d: d["model_and_protocol"].__setitem__("protocol_key", "jev-choice-wire-v2|dead"),
                       lambda d: d["exact_bridge"].__setitem__("seed_algorithm", "none"),
                       lambda d: d["exact_bridge"].__setitem__("token_budget", 96)):
            tampered = copy.deepcopy(REGISTRATION)
            mutate(tampered)
            instances = bridge.bridge_instances()
            plan = bridge.build_bridge_plan(instances, tampered)
            receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(max_physical_requests=plan.jev_request_cap),
                                              model=pr.JEV_REPLAY_MODEL)
            writer = writer_v5.LingWriterClientV5(api_key=KEY, max_physical_requests=plan.ling_request_cap)
            verification = bridge.verify_bridge_preflight(plan, tampered, receiver, writer,
                                                          repo_root=REPO_ROOT, pinned_hash=PIN,
                                                          ling_key_present=True)
            self.assertFalse(verification["ok"])

    def test_wrong_writer_parser_version_fails(self):
        instances, receiver, plan, writer, verification, se = build(owned_side_effect())
        writer.writer_parser_version = "ling-writer-parser-vX"
        verification = bridge.verify_bridge_preflight(plan, REGISTRATION, receiver, writer,
                                                      repo_root=REPO_ROOT, pinned_hash=PIN,
                                                      ling_key_present=True)
        self.assertIn("writer_parser_version_matches", verification["failed"])

    def test_missing_credentials_fail_before_calls(self):
        instances, receiver, plan, writer, verification, se = build(owned_side_effect())
        verification = bridge.verify_bridge_preflight(plan, REGISTRATION, receiver, writer,
                                                      repo_root=REPO_ROOT, pinned_hash=PIN,
                                                      ling_key_present=False)
        self.assertIn("ling_credentials_present", verification["failed"])
        report = bridge.execute_bridge(plan, receiver, writer, verification, instances, approval="x")
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(receiver.client.calls, 0)

    def test_existing_outputs_fail_before_calls(self):
        instances, receiver, plan, writer, verification, se = build(owned_side_effect())
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "b.jsonl"
            report_path = Path(directory) / "r.json"
            journal.write_text("{}")
            blocked = bridge.execute_bridge(plan, receiver, writer, verification, instances,
                                            approval="x", journal_path=journal, report_path=report_path)
            self.assertEqual(blocked["stop_reason"], "output_exists")
            journal.unlink()
            report_path.write_text("{}")
            blocked = bridge.execute_bridge(plan, receiver, writer, verification, instances,
                                            approval="x", journal_path=journal, report_path=report_path)
            self.assertEqual(blocked["stop_reason"], "report_exists")
            self.assertEqual(receiver.client.calls, 0)


class RuntimeCapTests(unittest.TestCase):
    def test_cli_main_construction_uses_registered_bridge_caps(self):
        captured = {}

        def fake_execute(plan, receiver, writer, verification, instances, **kwargs):
            captured["jev"] = receiver.client.max_physical_requests
            captured["ling"] = writer.max_physical_requests
            captured["plan"] = plan.to_dict()
            return {"mode": bridge.BRIDGE_VERSION, "status": "blocked", "stop_reason": "test"}

        with patch.object(bridge, "execute_bridge", side_effect=fake_execute):
            rc = bridge.main(["--live", "--approval", "reviewer-test"])
        self.assertEqual(rc, 1)
        self.assertEqual(captured["jev"], REGISTRATION["exact_bridge"]["jev_partition"])
        self.assertEqual(captured["ling"], REGISTRATION["exact_bridge"]["ling_partition"])
        self.assertEqual(captured["jev"], 34)
        self.assertEqual(captured["ling"], 80)

    def test_runtime_caps_read_from_registration(self):
        receiver, writer, plan = bridge.construct_bridge_runtime(REGISTRATION)
        self.assertEqual(receiver.client.max_physical_requests, 34)
        self.assertEqual(writer.max_physical_requests, 80)
        self.assertEqual(plan.jev_request_cap + plan.ling_request_cap, plan.request_cap)
        self.assertEqual(plan.request_cap, 114)

    def test_partition_mismatch_blocks(self):
        instances, receiver, plan, writer, verification, se = build(owned_side_effect())
        writer.max_physical_requests = 10
        report = bridge.execute_bridge(plan, receiver, writer, {"ok": True}, instances, approval="x")
        self.assertEqual(report["stop_reason"], "writer_partition_not_enforced")
        self.assertEqual(receiver.client.calls, 0)

    def test_combined_allocations_do_not_exceed_250_300(self):
        caps = REGISTRATION["caps"]
        self.assertEqual(caps["ladder_partition"]["jev"] + caps["bridge_partition"]["jev"], 250)
        self.assertEqual(caps["ladder_partition"]["ling"] + caps["bridge_partition"]["ling"], 300)
        self.assertLessEqual(caps["planned_by_provider"]["jev"], 250)
        self.assertLessEqual(caps["planned_by_provider"]["ling"], 300)

    def test_cost_cap_stops_before_calls(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["exact_bridge"]["cost_cap_usd"] = 0.0
        instances = bridge.bridge_instances()
        plan = bridge.build_bridge_plan(instances, tampered)
        receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(max_physical_requests=plan.jev_request_cap),
                                          model=pr.JEV_REPLAY_MODEL)
        writer = writer_v5.LingWriterClientV5(api_key=KEY, max_physical_requests=plan.ling_request_cap,
                                              clock=FakeClock().now, sleep_fn=lambda _: None)
        verification = {"ok": True, "checks": [], "failed": []}
        report = bridge.execute_bridge(plan, receiver, writer, verification, instances, approval="x")
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "cost_cap")
        self.assertEqual(writer.physical_attempts, 0)


class PromptEquivalenceTests(unittest.TestCase):
    def _original_prompt(self, instance, agent, turn, board, run_id):
        view = {**instance.agent_view(agent, "COMM"), "is_finalizer": agent == bd.FINALIZER_AGENT,
                "finalizing_agent": bd.FINALIZER_AGENT}
        visible = tuple(dict(row) for row in board if row["author"] != agent)
        context = AgentContext(run_id, instance.instance_id, agent, BatteryCondition.COMM, turn, view,
                               visible, bd.PROMPT_SCHEMA_VERSION, ladder.EXACT_BRIDGE_TOKEN_BUDGET)
        return json.dumps(bd.treatment_prompt(context), sort_keys=True)

    def test_prompts_match_original_path_byte_for_byte(self):
        instance = bridge.bridge_instances()[0]
        board = [{"message_id": "m", "author": "A", "receiver": "B", "text": "precedes=x",
                  "status": "accepted", "delta_i_bits": 1.0, "message_tokens": 1}]
        for turn in range(ladder.EXACT_BRIDGE_TURNS):
            for agent in ladder.EXACT_BRIDGE_AGENTS:
                _, generated = bridge.agent_context_and_prompt(instance, agent, turn, board, "r")
                self.assertEqual(generated, self._original_prompt(instance, agent, turn, board, "r"))


class VisibilityTests(unittest.TestCase):
    def test_peer_only_visibility_and_row_schema(self):
        captured = []
        report, receiver, writer, plan, verification = run(owned_side_effect(capture=captured))
        self.assertEqual(report["status"], "completed")
        by_key = {(row["turn"], ("A" if row["is_finalizer"] else "B")): row for row in captured}
        for row in captured:
            authors = {visible["author"] for visible in row["visible_messages"]}
            self.assertNotIn("A" if row["is_finalizer"] else "B", authors, row)
            for visible in row["visible_messages"]:
                self.assertEqual(set(visible), {"message_id", "author", "receiver", "text", "status",
                                                "delta_i_bits", "message_tokens"})
        self.assertEqual(by_key[(0, "A")]["visible_messages"], [])
        # B's turn 0 sees A's turn 0 write; later turns see prior peer-only writes
        self.assertTrue(any(v["author"] == "A" for v in by_key[(0, "B")]["visible_messages"]))
        self.assertTrue(any(v["author"] == "B" for v in by_key[(1, "A")]["visible_messages"]))

    def test_jev_receiver_gets_only_b_authored_accepted_claims(self):
        report, receiver, writer, plan, verification = run(owned_side_effect())
        self.assertTrue(receiver.client.requests)
        for request in receiver.client.requests:
            visible = request["state"]["visible_messages"]
            for message in visible:
                self.assertTrue(message["text"].startswith("peer_clue: "))
            # A's own claims are never exposed back as received evidence
            self.assertNotIn("message-A", json.dumps(request["state"]))
        # rows persisted expose only B-authored accepted claims for the receiver
        row = report["cases"][0]
        b_claims = [r["text"] for r in row["board"] if r["author"] == "B" and r["status"] == "accepted"]
        self.assertEqual(sum(len(case["board"]) for case in report["cases"]), report["board_messages"])
        self.assertTrue(all(r["receiver"] == "A" for r in row["board"] if r["author"] == "B"))
        self.assertTrue(b_claims)

    def test_rejected_writes_never_visible(self):
        captured = []
        report, receiver, writer, plan, verification = run(
            owned_side_effect(capture=captured, reject_agent="A"))
        self.assertEqual(report["rejected_writes"], 17)
        for row in captured:
            for visible in row["visible_messages"]:
                self.assertNotIn("invented-clue", visible["text"])
        self.assertTrue(all(r["text"] != "invented-clue" for r in report["cases"][0]["board"]))


class ReceiverEvidenceTests(unittest.TestCase):
    def test_valid_receiver_evidence_persisted(self):
        report, receiver, writer, plan, verification = run(owned_side_effect())
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["receiver_valid_cases"], 17)
        self.assertEqual(report["attempted_cases"], 17)
        row = report["cases"][0]
        for field in ("request_hash", "state_hash", "protocol_key", "resolved_model", "option_ids",
                      "target_id", "selected_option_id", "probabilities", "raw_probabilities",
                      "probability_diagnostics", "normalization_tier", "confidence", "usage",
                      "writer_outcomes", "board_log", "provider_attempts", "receiver_valid"):
            self.assertIn(field, row)
        self.assertTrue(row["receiver_valid"])
        self.assertEqual(row["protocol_key"], plan.protocol_key)
        self.assertEqual(set(row["option_ids"]), set(row["probabilities"]))
        self.assertAlmostEqual(sum(row["probabilities"].values()), 1.0, places=9)
        self.assertEqual(row["writer_outcomes"][0]["seed_sent"] is not None, True)
        self.assertFalse(row["raw_response_retained"])
        self.assertFalse(row["credentials_retained"])

    def test_invalid_jev_result_is_durable_and_stops(self):
        class BadAdapter(jc2.JevChoiceAdapterV2):
            def complete_with_raw(self, state):
                response, raw = super().complete_with_raw(state)
                from dataclasses import replace
                return replace(response, status="invalid", error_class="model_drift"), raw

        instances = bridge.bridge_instances()
        plan = bridge.build_bridge_plan(instances, REGISTRATION)
        receiver = BadAdapter(FakeReceiverClient(max_physical_requests=plan.jev_request_cap),
                              model=pr.JEV_REPLAY_MODEL)
        writer = writer_v5.LingWriterClientV5(api_key=KEY, max_physical_requests=plan.ling_request_cap,
                                              clock=FakeClock().now, sleep_fn=lambda _: None)
        verification = bridge.verify_bridge_preflight(plan, REGISTRATION, receiver, writer,
                                                      repo_root=REPO_ROOT, pinned_hash=PIN,
                                                      ling_key_present=True)
        with patch.object(writer_v5.urllib.request, "urlopen", side_effect=owned_side_effect()):
            report = bridge.execute_bridge(plan, receiver, writer, verification, instances,
                                           approval="test", pinned_hash=PIN, sleep_fn=lambda _: None)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "model_drift")
        self.assertEqual(report["receiver_invalid_cases"], 1)
        self.assertEqual(len(report["cases"]), 1)
        self.assertFalse(report["cases"][0]["receiver_valid"])

    def test_no_credentials_or_raw_bodies(self):
        report, receiver, writer, plan, verification = run(owned_side_effect())
        serialized = json.dumps(report, allow_nan=False)
        self.assertNotIn(KEY, serialized)
        self.assertFalse(report["raw_response_retained"])
        self.assertFalse(report["credentials_retained"])

    def test_writer_empty_output_stops_before_receiver(self):
        report, receiver, writer, plan, verification = run(empty_side_effect)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "empty_output")
        self.assertEqual(receiver.client.calls, 0)
        self.assertEqual(report["receiver_unattempted_cases"], 1)


class FakeBigWriter:
    model = pr.LING_MODEL
    endpoint = pr.LING_ENDPOINT
    transport_version = writer_v3.LING_WRITER_TRANSPORT_VERSION

    def __init__(self, cap):
        self.max_physical_requests = cap
        self.physical_attempts = 0

    def write_outcome(self, context):
        self.physical_attempts += 1
        clues = list(context.get("private_clues", ()))
        claim = clues[0] if clues else "x"
        return {"outcome": "message_candidate", "claim": claim, "error_class": None,
                "input_tokens": 8192, "output_tokens": 2, "finish_reason": None, "content_length": 10,
                "answer": None, "seed_sent": 1, "max_tokens": 1024,
                "physical_attempts": self.physical_attempts}


class ExposureProvenanceTests(unittest.TestCase):
    def test_every_b_message_has_a_jev_finalizer_read(self):
        report, receiver, writer, plan, verification = run(owned_side_effect())
        self.assertEqual(report["status"], "completed")
        saw_finalizer = False
        for case in report["cases"]:
            reads = [event for event in case["board_log"]
                     if event["kind"] == "peer_read_exposure" and event["agent_id"] == "A"]
            read_ids = {event["message_id"] for event in reads}
            b_rows = [row for row in case["board"] if row["author"] == "B" and row["status"] == "accepted"]
            self.assertTrue(b_rows)
            for row in b_rows:
                self.assertIn(row["message_id"], read_ids)
            final_b = [row for row in b_rows if row["message_id"].endswith("-1")]
            self.assertTrue(final_b)
            read = next(event for event in reads if event["message_id"] == final_b[-1]["message_id"]
                        and event["payload"].get("exposure_id") == bridge.JEV_FINALIZER_EXPOSURE_ID)
            saw_finalizer = True
            if case["eligible_exposure"]:
                self.assertTrue(b_rows)
        self.assertTrue(saw_finalizer)


class ProviderCounterTests(unittest.TestCase):
    def test_per_case_counters_are_cumulative_through_the_case(self):
        report, receiver, writer, plan, verification = run(owned_side_effect())
        first = report["cases"][0]["provider_attempts"]
        self.assertEqual((first["jev"], first["ling"], first["combined"]), (1, 4, 5))
        last = report["cases"][-1]["provider_attempts"]
        self.assertEqual((last["jev"], last["ling"]), (17, 68))
        self.assertEqual(report["cases"][0]["receiver_attempted"], True)


class MissingnessTests(unittest.TestCase):
    def _runtime(self, adapter_cls, writer=None):
        instances = bridge.bridge_instances()
        plan = bridge.build_bridge_plan(instances, REGISTRATION)
        receiver = adapter_cls(FakeReceiverClient(max_physical_requests=plan.jev_request_cap),
                               model=pr.JEV_REPLAY_MODEL)
        used_writer = writer or writer_v5.LingWriterClientV5(
            api_key=KEY, max_physical_requests=plan.ling_request_cap,
            clock=FakeClock().now, sleep_fn=lambda _: None)
        return instances, receiver, plan, used_writer

    def test_receiver_transport_exception_is_attempted_invalid(self):
        class RaisingAdapter(jc2.JevChoiceAdapterV2):
            def complete_with_raw(self, state):
                raise OSError("boom")

        instances, receiver, plan, writer = self._runtime(RaisingAdapter)
        verification = {"ok": True, "checks": [], "failed": []}
        with patch.object(writer_v5.urllib.request, "urlopen", side_effect=owned_side_effect()):
            report = bridge.execute_bridge(plan, receiver, writer, verification, instances,
                                           approval="test", pinned_hash=PIN, sleep_fn=lambda _: None)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "jev_OSError")
        row = report["cases"][0]
        self.assertTrue(row["receiver_attempted"])
        self.assertFalse(row["receiver_valid"])
        self.assertEqual(row["receiver_error_class"], "jev_OSError")
        self.assertEqual(report["receiver_invalid_cases"], 1)
        self.assertEqual(report["receiver_unattempted_cases"], 0)

    def test_receiver_cost_guard_is_unattempted(self):
        tampered = copy.deepcopy(REGISTRATION)
        tampered["exact_bridge"]["cost_cap_usd"] = 0.0043
        instances = bridge.bridge_instances()
        plan = bridge.build_bridge_plan(instances, tampered)
        receiver = jc2.JevChoiceAdapterV2(FakeReceiverClient(max_physical_requests=plan.jev_request_cap),
                                          model=pr.JEV_REPLAY_MODEL)
        writer = FakeBigWriter(plan.ling_request_cap)
        report = bridge.execute_bridge(plan, receiver, writer, {"ok": True}, instances, approval="test",
                                       pinned_hash=PIN, sleep_fn=lambda _: None)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["stop_reason"], "cost_cap")
        row = report["cases"][0]
        self.assertFalse(row["receiver_attempted"])
        self.assertFalse(row["receiver_valid"])
        self.assertEqual(row["receiver_error_class"], "cost_cap")
        self.assertEqual(report["receiver_unattempted_cases"], 1)
        self.assertEqual(report["receiver_invalid_cases"], 0)
        self.assertEqual(receiver.client.calls, 0)


if __name__ == "__main__":
    unittest.main()
