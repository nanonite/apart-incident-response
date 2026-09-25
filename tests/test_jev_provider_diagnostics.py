import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from apart_incident_response import behavioral_discovery as bd
from apart_incident_response import jev_choice as jc
from apart_incident_response import jev_coverage_manifest_preregistration_v7 as prv7
from apart_incident_response import jev_ling_writer_v5 as writer_v5
from apart_incident_response import jev_provider_diagnostics as diag
from apart_incident_response import jev_replay_preregistration as pr


REPO_ROOT = Path(__file__).resolve().parents[1]
FAKE_JEV_KEY = "test-jev-key-0123456789abcdef"
FAKE_LING_KEY = "test-openrouter-key-0123456789abcdef"


def _http_error(status, body=b'{"detail":"x"}', headers=None):
    return urllib.error.HTTPError("https://example.invalid/step", status, "error",
                                  headers if headers is not None else {}, io.BytesIO(body))


def _fake_state():
    options = (jc.ChoiceOption("a>a", "a>a"), jc.ChoiceOption("b>b", "b>b"))
    return jc.ChoiceState("probe-instance", "A", "ISO", "q", options,
                          {"family": "planning"}, "instructions", "hash")


class FakeJevClient:
    provider = "jev"
    endpoint = jc.JEV_SYSTEMONE_ENDPOINT

    def __init__(self, *, model=pr.JEV_REPLAY_MODEL, endpoint=jc.JEV_SYSTEMONE_ENDPOINT,
                 max_retries=0, max_physical_requests=1, timeout=60.0, response=None,
                 error=None, calls=None):
        self.model = model
        self.endpoint = endpoint
        self.max_retries = max_retries
        self.max_physical_requests = max_physical_requests
        self.timeout = timeout
        self.physical_attempts = 0
        self.response = response
        self.error = error
        self.calls = calls if calls is not None else []

    def complete(self, request):
        self.calls.append(request)
        self.physical_attempts += 1
        if self.error is not None:
            raise self.error
        return self.response


class FakeLingWriter:
    transport_version = writer_v5.LingWriterClientV5.transport_version

    def __init__(self, *, model, endpoint, api_key, max_retries=0, max_physical_requests=1,
                 timeout=60.0, outcome=None, error=None, calls=None):
        self.model = model
        self.endpoint = endpoint
        self.api_key = api_key
        self.max_retries = max_retries
        self.max_physical_requests = max_physical_requests
        self.timeout = timeout
        self.physical_attempts = 0
        self.logical_calls = 0
        self._outcome = outcome
        self._error = error
        self.calls = calls if calls is not None else []
        self.rate_limit_records = []

    def rate_limit_diagnostics(self):
        return [dict(record) for record in self.rate_limit_records]

    def write_outcome(self, context):
        self.calls.append(context)
        self.logical_calls += 1
        self.physical_attempts += 1
        if self._error is not None:
            raise self._error
        return dict(self._outcome)


def _registration():
    return json.loads((REPO_ROOT / diag.DEFAULT_REGISTRATION).read_text(encoding="utf-8"))


def _valid_outcome(**extra):
    base = {"outcome": "deliberate_silence", "error_class": None, "finish_reason": "stop",
            "input_tokens": 12, "output_tokens": 3, "completion_tokens": 3,
            "diagnostics": [{"status": 200, "retry_after_present": False,
                             "retry_after_valid": False}]}
    base.update(extra)
    return base


#: Committed evidence from the authorized run (278db9d). Never moved, deleted,
#: overwritten or rewritten by any test.
PROBE_REGISTRATION = REPO_ROOT / diag.DEFAULT_REGISTRATION
PROBE_JEV_ARTIFACT = REPO_ROOT / diag.DEFAULT_JEV_PROBE_OUTPUT
PROBE_LING_ARTIFACT = REPO_ROOT / diag.DEFAULT_LING_PROBE_OUTPUT
PROBE_ARTIFACTS = (PROBE_REGISTRATION, PROBE_JEV_ARTIFACT, PROBE_LING_ARTIFACT)
#: sha256 of the probe artifacts as committed in 278db9d. Byte-identity of the
#: evidence is asserted against these, not merely against the start of a run.
COMMITTED_PROBE_SHA256 = {
    str(PROBE_JEV_ARTIFACT.relative_to(REPO_ROOT)):
        "5dc85056ac9525e7303ef9491dc6758f4c12fd2ce03139fa29cb46abb668876e",
    str(PROBE_LING_ARTIFACT.relative_to(REPO_ROOT)):
        "b82f09436f2272d6e392bb38efbcc999e7a2ef48eafbc179c9fde0e4b98eed95",
}


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def diagnostics_snapshot() -> dict:
    """sha256 of every committed diagnostics file (None when absent)."""

    return {str(path.relative_to(REPO_ROOT)): _digest(path) for path in PROBE_ARTIFACTS}


def diagnostics_listing() -> list:
    return sorted(os.listdir(REPO_ROOT / "runs" / "epic-126" / "diagnostics"))


def diagnostics_sandbox(test_case: unittest.TestCase) -> Path:
    """Repo root presenting the checkout at registration-lock time.

    The committed Jev/Ling probe artifacts occupy the registered diagnostic
    output paths, so production freshness checks correctly fail against
    ``REPO_ROOT``. This sandbox isolates those two outputs without touching
    them: ``runs/epic-126/diagnostics`` is materialised as a real directory
    holding only a byte-identical copy of the registration, while every other
    path (``src/``, the replay-v4 pins that ``build_registration`` verifies,
    and all other ``runs/epic-126`` entries) is symlinked back to the real
    checkout so source and provenance hashes verify exactly as in production.
    """

    root = Path(tempfile.mkdtemp(prefix="diag-locktime-"))
    test_case.addCleanup(shutil.rmtree, root, ignore_errors=True)
    (root / "src").symlink_to(REPO_ROOT / "src")
    runs = root / "runs"
    runs.mkdir()
    for entry in sorted(os.listdir(REPO_ROOT / "runs")):
        if entry != "epic-126":
            (runs / entry).symlink_to(REPO_ROOT / "runs" / entry)
    epic = runs / "epic-126"
    epic.mkdir()
    for entry in sorted(os.listdir(REPO_ROOT / "runs" / "epic-126")):
        if entry == "diagnostics":
            continue
        (epic / entry).symlink_to(REPO_ROOT / "runs" / "epic-126" / entry)
    (epic / "diagnostics").mkdir()
    shutil.copy2(PROBE_REGISTRATION, epic / "diagnostics" / PROBE_REGISTRATION.name)
    return root


class DiagnosticsSandboxTestCase(unittest.TestCase):
    """Isolate every test from the committed diagnostics evidence.

    ``setUp`` snapshots the real artifacts and directory listing; ``tearDown``
    asserts both are unchanged, so any test that touched committed evidence
    fails immediately instead of silently destroying it.
    """

    def setUp(self):
        self.artifacts = diagnostics_snapshot()
        self.diagnostics_dir = diagnostics_listing()
        self.sandbox_root = diagnostics_sandbox(self)

    def tearDown(self):
        self.assertEqual(diagnostics_snapshot(), self.artifacts,
                         "a committed diagnostics artifact changed during the test")
        self.assertEqual(diagnostics_listing(), self.diagnostics_dir,
                         "the diagnostics directory gained or lost a file")


class ClassificationTests(DiagnosticsSandboxTestCase):
    def test_exactly_eight_classes(self):
        self.assertEqual(len(diag.ERROR_CLASSES), 8)
        self.assertEqual(len(set(diag.ERROR_CLASSES)), 8)

    def test_every_class_is_reachable(self):
        seen = {
            diag.classify_probe_outcome(credential_ok=False),
            diag.classify_probe_outcome(credential_ok=True, http_status=401),
            diag.classify_probe_outcome(credential_ok=True, http_status=429),
            diag.classify_probe_outcome(credential_ok=True, http_status=404),
            diag.classify_probe_outcome(credential_ok=True, http_status=503),
            diag.classify_probe_outcome(credential_ok=True, transport_error="TimeoutError"),
            diag.classify_probe_outcome(credential_ok=True, parse_error="bad",
                                        response_received=True),
            diag.classify_probe_outcome(credential_ok=True, response_received=True, body_ok=True),
        }
        self.assertEqual(seen, set(diag.ERROR_CLASSES))

    def test_distinct_error_classification(self):
        cases = [
            (dict(credential_ok=False), diag.CLASS_CREDENTIAL_OR_CONFIGURATION),
            (dict(credential_ok=True, transport_error="physical_request_cap_exhausted"),
             diag.CLASS_CREDENTIAL_OR_CONFIGURATION),
            (dict(credential_ok=True, http_status=401), diag.CLASS_AUTH_REJECTED),
            (dict(credential_ok=True, http_status=403), diag.CLASS_AUTH_REJECTED),
            (dict(credential_ok=True, http_status=429), diag.CLASS_RATE_LIMITED),
            (dict(credential_ok=True, http_status=404), diag.CLASS_UNAVAILABLE),
            (dict(credential_ok=True, http_status=408), diag.CLASS_CAPACITY),
            (dict(credential_ok=True, http_status=500), diag.CLASS_CAPACITY),
            (dict(credential_ok=True, http_status=503), diag.CLASS_CAPACITY),
            (dict(credential_ok=True, http_status=529), diag.CLASS_CAPACITY),
            (dict(credential_ok=True, transport_error="TimeoutError"), diag.CLASS_NETWORK),
            (dict(credential_ok=True, transport_error="ConnectionResetError"),
             diag.CLASS_NETWORK),
            (dict(credential_ok=True, parse_error="malformed_json_body",
                  response_received=True), diag.CLASS_MALFORMED),
            (dict(credential_ok=True, response_received=True, body_ok=False),
             diag.CLASS_MALFORMED),
            (dict(credential_ok=True, response_received=True, body_ok=True),
             diag.CLASS_VALID),
            (dict(credential_ok=True, http_status=400),
             diag.CLASS_CREDENTIAL_OR_CONFIGURATION),
        ]
        for kwargs, expected in cases:
            with self.subTest(kwargs=kwargs):
                self.assertEqual(diag.classify_probe_outcome(**kwargs), expected)

    def test_jev_exception_mapping(self):
        cases = [
            (jc.JevCredentialError("missing_or_malformed_credentials"),
             diag.CLASS_CREDENTIAL_OR_CONFIGURATION),
            (jc.JevProviderRejection(401, "auth_error"), diag.CLASS_AUTH_REJECTED),
            (jc.JevProviderRejection(403, "auth_error"), diag.CLASS_AUTH_REJECTED),
            (jc.JevProviderRejection(404, "endpoint_or_model_unavailable"),
             diag.CLASS_UNAVAILABLE),
            (jc.JevTransportError("retry_exhausted_http_429"), diag.CLASS_RATE_LIMITED),
            (jc.JevTransportError("retry_exhausted_http_503"), diag.CLASS_CAPACITY),
            (jc.JevTransportError("retry_exhausted_http_529"), diag.CLASS_CAPACITY),
            (jc.JevTransportError("retry_exhausted_http_408"), diag.CLASS_CAPACITY),
            (jc.JevTransportError("TimeoutError"), diag.CLASS_NETWORK),
            (jc.JevTransportError("physical_request_cap_exhausted"),
             diag.CLASS_CREDENTIAL_OR_CONFIGURATION),
            (jc.JevResponseError("malformed_json_body"), diag.CLASS_MALFORMED),
        ]
        for exc, expected in cases:
            with self.subTest(exc=type(exc).__name__):
                fields = diag._jev_exception_fields(exc)
                self.assertEqual(
                    diag.classify_probe_outcome(
                        credential_ok=fields["credential_ok"],
                        http_status=fields["http_status"],
                        transport_error=fields["transport_error"],
                        parse_error=fields["parse_error"],
                        response_received=fields["parse_error"] is not None),
                    expected)

    def test_ling_error_class_mapping(self):
        cases = [
            (None, diag.CLASS_VALID),
            ("writer_http_401_auth_error", diag.CLASS_AUTH_REJECTED),
            ("writer_http_403_auth_error", diag.CLASS_AUTH_REJECTED),
            ("writer_http_429_rate_limited", diag.CLASS_RATE_LIMITED),
            ("writer_http_404_endpoint_or_model_unavailable", diag.CLASS_UNAVAILABLE),
            ("writer_http_503_server_error", diag.CLASS_CAPACITY),
            ("writer_http_529_server_error", diag.CLASS_CAPACITY),
            ("writer_network_TimeoutError", diag.CLASS_NETWORK),
            ("writer_missing_credentials", diag.CLASS_CREDENTIAL_OR_CONFIGURATION),
        ]
        for error_class, expected in cases:
            with self.subTest(error_class=error_class):
                fields = diag._ling_error_class_fields(error_class)
                self.assertEqual(
                    diag.classify_probe_outcome(
                        credential_ok=fields["credential_ok"],
                        http_status=fields["http_status"],
                        transport_error=fields["transport_error"],
                        parse_error=fields["parse_error"],
                        response_received=(error_class is None),
                        body_ok=(error_class is None)),
                    expected)


class RegistrationTests(DiagnosticsSandboxTestCase):
    def test_registration_is_locked_and_non_authorizing(self):
        registration = _registration()
        self.assertEqual(registration["status"], diag.DIAG_STATUS)
        self.assertIs(registration["live_collection_authorized"], False)
        self.assertIs(registration["probes_authorized"], False)
        self.assertIs(registration["authorizes_replay"], False)
        self.assertIs(registration["lock_is_not_execution_authorization"], True)

    def test_verify_registration_passes(self):
        result = diag.verify_registration(_registration(), repo_root=self.sandbox_root,
                                          approval=None, check_credentials=False,
                                          require_approval=False)
        self.assertTrue(result["ok"], result["failed"])
        self.assertEqual(result["failed"], [])

    def test_approval_required_only_for_live(self):
        offline = diag.verify_registration(_registration(),
                                           repo_root=self.sandbox_root,
                                           approval=None, require_approval=False,
                                           check_credentials=False)
        self.assertTrue(offline["ok"])
        live = diag.verify_registration(_registration(), repo_root=self.sandbox_root,
                                        approval=None, require_approval=True,
                                        check_credentials=False)
        self.assertFalse(live["ok"])
        self.assertIn("approval_present", live["failed"])

    def test_registration_content_drift_fails_closed(self):
        tampered = _registration()
        tampered["live_collection_authorized"] = True
        result = diag.verify_registration(tampered, repo_root=self.sandbox_root,
                                          check_credentials=False)
        self.assertFalse(result["ok"])
        self.assertTrue({"registration_hash_matches", "registration_content_matches"}
                        & set(result["failed"]))

    def test_occupied_probe_output_fails_preflight(self):
        """Occupancy is created inside the sandbox; real evidence is untouched."""

        target = self.sandbox_root / diag.DEFAULT_JEV_PROBE_OUTPUT
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")
        result = diag.verify_registration(_registration(),
                                          repo_root=self.sandbox_root,
                                          check_credentials=False)
        self.assertFalse(result["ok"])
        self.assertIn("jev_probe_path_fresh", result["failed"])
        # no unlink of anything real: the sandbox is discarded by addCleanup
        self.assertEqual(diagnostics_snapshot(), self.artifacts)

    def test_production_preflight_rejects_occupied_probe_paths(self):
        """The real checkout keeps its freshness gate on the committed probes."""

        self.assertTrue(PROBE_JEV_ARTIFACT.is_file())
        self.assertTrue(PROBE_LING_ARTIFACT.is_file())
        result = diag.verify_registration(_registration(), repo_root=REPO_ROOT,
                                          check_credentials=False)
        self.assertFalse(result["ok"])
        self.assertIn("jev_probe_path_fresh", result["failed"])
        self.assertIn("ling_probe_path_fresh", result["failed"])

    def test_sandbox_isolates_the_committed_probe_artifacts(self):
        self.assertFalse((self.sandbox_root / diag.DEFAULT_JEV_PROBE_OUTPUT).exists())
        self.assertFalse((self.sandbox_root / diag.DEFAULT_LING_PROBE_OUTPUT).exists())
        copied = self.sandbox_root / diag.DEFAULT_REGISTRATION
        self.assertTrue(copied.is_file())
        self.assertEqual(copied.read_bytes(), PROBE_REGISTRATION.read_bytes())
        self.assertTrue(PROBE_JEV_ARTIFACT.is_file())
        self.assertTrue(PROBE_LING_ARTIFACT.is_file())

    def test_availability_evidence_is_non_authorizing(self):
        registration = _registration()
        evidence = registration["availability_evidence"]
        self.assertEqual(len(evidence), 2)
        for entry in evidence:
            self.assertIs(entry["authorizes_replay"], False)
            self.assertEqual(entry["scope"], "availability only")
        self.assertEqual(sorted(registration["not_claimed"]),
                         sorted(["key expiry", "model removal", "quota exhaustion"]))

    def test_probe_route_binding(self):
        probes = _registration()["probes"]
        self.assertEqual(probes["jev"]["model"], pr.JEV_REPLAY_MODEL)
        self.assertEqual(probes["jev"]["endpoint"], jc.JEV_SYSTEMONE_ENDPOINT)
        self.assertTrue(probes["jev"]["transport"].endswith("jev_choice.JevChoiceClient"))
        self.assertEqual(probes["ling"]["model"], prv7.PAID_LING_MODEL)
        self.assertEqual(probes["ling"]["endpoint"], pr.LING_ENDPOINT)
        self.assertEqual(probes["ling"]["key_loader"],
                         "apart_incident_response.behavioral_discovery._api_key")
        self.assertIn("LingWriterClientV5.write_outcome",
                      probes["ling"]["prompt_format"])
        self.assertIn("messages[{role: user, content}]",
                      probes["ling"]["prompt_format"])
        self.assertEqual(probes["ling"]["max_physical_attempts"], 1)
        self.assertEqual(probes["jev"]["max_physical_attempts"], 1)


class OfflineCliTests(DiagnosticsSandboxTestCase):
    def test_offline_cli_makes_zero_calls(self):
        def explode(*args, **kwargs):
            raise AssertionError("provider call attempted during offline preflight")

        with patch("urllib.request.urlopen", explode):
            rc = diag.main(["--repo-root", str(self.sandbox_root)])
        self.assertEqual(rc, 0)

    def test_live_without_approval_makes_zero_calls(self):
        def explode(*args, **kwargs):
            raise AssertionError("provider call attempted without approval")

        self.assertFalse((self.sandbox_root / diag.DEFAULT_JEV_PROBE_OUTPUT).exists())
        self.assertFalse((self.sandbox_root / diag.DEFAULT_LING_PROBE_OUTPUT).exists())
        with patch("urllib.request.urlopen", explode):
            rc = diag.main(["--repo-root", str(self.sandbox_root), "--live"])
        self.assertEqual(rc, 2)
        self.assertFalse((self.sandbox_root / diag.DEFAULT_JEV_PROBE_OUTPUT).exists())
        self.assertFalse((self.sandbox_root / diag.DEFAULT_LING_PROBE_OUTPUT).exists())

    def test_failed_preflight_makes_zero_calls(self):
        with tempfile.TemporaryDirectory(prefix="diag-preflight-") as directory:
            root = Path(directory)
            (root / diag.DEFAULT_REGISTRATION).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO_ROOT / diag.DEFAULT_REGISTRATION,
                        root / diag.DEFAULT_REGISTRATION)
            calls = []

            def explode(*args, **kwargs):
                calls.append(1)
                raise AssertionError("provider call attempted after failed preflight")

            with patch("urllib.request.urlopen", explode):
                rc = diag.main(["--repo-root", str(root), "--live", "--approval", "ref"])
            self.assertEqual(rc, 2)
            self.assertEqual(calls, [])
            self.assertFalse((root / diag.DEFAULT_JEV_PROBE_OUTPUT).exists())
            self.assertFalse((root / diag.DEFAULT_LING_PROBE_OUTPUT).exists())

    def test_committed_probe_artifacts_stay_byte_identical(self):
        before = diagnostics_snapshot()
        with patch("urllib.request.urlopen",
                   side_effect=AssertionError("provider call")):
            rc = diag.main(["--repo-root", str(self.sandbox_root)])
        self.assertEqual(rc, 0)
        self.assertEqual(diag.verify_registration(_registration(),
                                                  repo_root=self.sandbox_root,
                                                  check_credentials=False)["failed"],
                         [])
        self.assertEqual(diagnostics_snapshot(), before)
        for relative, digest in COMMITTED_PROBE_SHA256.items():
            self.assertEqual(before[relative], digest,
                             f"committed evidence drifted: {relative}")

    def test_missing_credentials_recorded_with_zero_calls(self):
        registration = _registration()
        with tempfile.TemporaryDirectory(prefix="diag-nocreds-") as directory:
            with patch.object(jc, "load_jev_credentials",
                              return_value=jc.JevCredentials(None, None)):
                record = diag.run_jev_probe(registration=registration, repo_root=Path(directory),
                                            approval="ref", state_builder=_fake_state)
            self.assertEqual(record["provider_calls"], 0)
            self.assertEqual(record["attempt_count"], 0)
            self.assertEqual(record["error_class"], diag.CLASS_CREDENTIAL_OR_CONFIGURATION)


class ProbeCapTests(DiagnosticsSandboxTestCase):
    def test_jev_probe_single_physical_attempt(self):
        registration = _registration()
        calls = []

        def fake_urlopen(*args, **kwargs):
            calls.append(1)
            raise _http_error(429)

        with patch.object(jc, "load_jev_credentials",
                          return_value=jc.JevCredentials(FAKE_JEV_KEY, "test")), \
             patch("urllib.request.urlopen", fake_urlopen):
            with tempfile.TemporaryDirectory(prefix="diag-jev-") as directory:
                record = diag.run_jev_probe(registration=registration,
                                            repo_root=Path(directory), approval="ref",
                                            state_builder=_fake_state)
        self.assertEqual(len(calls), 1)
        self.assertEqual(record["attempt_count"], 1)
        self.assertEqual(record["provider_calls"], 1)
        self.assertEqual(record["error_class"], diag.CLASS_RATE_LIMITED)
        self.assertEqual(record["http_status"], 429)
        self.assertEqual(record["retry_metadata"]["max_retries"], 0)
        self.assertEqual(record["retry_metadata"]["cap"], 1)

    def test_ling_probe_single_physical_attempt(self):
        registration = _registration()
        calls = []

        def fake_urlopen(*args, **kwargs):
            calls.append(1)
            raise _http_error(429)

        with patch.object(bd, "_api_key", return_value=FAKE_LING_KEY), \
             patch("urllib.request.urlopen", fake_urlopen):
            with tempfile.TemporaryDirectory(prefix="diag-ling-") as directory:
                record = diag.run_ling_probe(registration=registration,
                                             repo_root=Path(directory), approval="ref")
        self.assertEqual(len(calls), 1)
        self.assertEqual(record["attempt_count"], 1)
        self.assertEqual(record["provider_calls"], 1)
        self.assertEqual(record["error_class"], diag.CLASS_RATE_LIMITED)
        self.assertEqual(record["http_status"], 429)
        self.assertEqual(record["retry_metadata"]["max_retries"], 0)

    def test_jev_probe_distinct_status_classes_end_to_end(self):
        registration = _registration()
        expectations = [
            (401, diag.CLASS_AUTH_REJECTED),
            (403, diag.CLASS_AUTH_REJECTED),
            (404, diag.CLASS_UNAVAILABLE),
            (429, diag.CLASS_RATE_LIMITED),
            (503, diag.CLASS_CAPACITY),
            (529, diag.CLASS_CAPACITY),
        ]
        for status, expected in expectations:
            with self.subTest(status=status):
                def fake_urlopen(*args, **kwargs):
                    raise _http_error(status)

                with patch.object(jc, "load_jev_credentials",
                                  return_value=jc.JevCredentials(FAKE_JEV_KEY, "test")), \
                     patch("urllib.request.urlopen", fake_urlopen):
                    with tempfile.TemporaryDirectory(prefix="diag-cls-") as directory:
                        record = diag.run_jev_probe(registration=registration,
                                                    repo_root=Path(directory), approval="ref",
                                                    state_builder=_fake_state)
                self.assertEqual(record["error_class"], expected)
                self.assertEqual(record["attempt_count"], 1)

    def test_jev_valid_response_end_to_end(self):
        registration = _registration()
        body = json.dumps({"answers": {"q": {"answer": "a>a"}},
                           "usage": {"prompt_tokens": 9, "completion_tokens": 4}}).encode()

        def fake_urlopen(*args, **kwargs):
            return io.BytesIO(body)

        with patch.object(jc, "load_jev_credentials",
                          return_value=jc.JevCredentials(FAKE_JEV_KEY, "test")), \
             patch("urllib.request.urlopen", fake_urlopen):
            with tempfile.TemporaryDirectory(prefix="diag-ok-") as directory:
                record = diag.run_jev_probe(registration=registration,
                                            repo_root=Path(directory), approval="ref",
                                            state_builder=_fake_state)
        self.assertEqual(record["error_class"], diag.CLASS_VALID)
        self.assertTrue(record["usage_present"])
        self.assertEqual(record["provider_calls"], 1)


class RedactionTests(DiagnosticsSandboxTestCase):
    def test_probe_records_carry_no_secret(self):
        registration = _registration()
        with patch.object(jc, "load_jev_credentials",
                          return_value=jc.JevCredentials(FAKE_JEV_KEY, "test")), \
             patch.object(bd, "_api_key", return_value=FAKE_LING_KEY):
            with tempfile.TemporaryDirectory(prefix="diag-redact-") as directory:
                root = Path(directory)
                jev = diag.run_jev_probe(registration=registration, repo_root=root,
                                         approval="ref", state_builder=_fake_state,
                                         client_factory=lambda **kw: FakeJevClient(
                                             response={"answers": {"q": {"answer": "a"}},
                                                       "usage": {"prompt_tokens": 1}},
                                             **{key: kw[key] for key in
                                                ("model", "endpoint", "max_retries",
                                                 "max_physical_requests", "timeout")
                                                if key in kw}))
                ling = diag.run_ling_probe(registration=registration, repo_root=root,
                                           approval="ref",
                                           writer_factory=lambda **kw: FakeLingWriter(
                                               outcome=_valid_outcome(), **kw))
                text = json.dumps({"jev": jev, "ling": ling}, sort_keys=True)
        self.assertEqual(diag.redaction_violations(text, [FAKE_JEV_KEY, FAKE_LING_KEY]), [])
        for record in (jev, ling):
            self.assertIs(record["raw_response_retained"], False)
            self.assertIs(record["credentials_retained"], False)
            self.assertIs(record["headers_retained"], False)

    def test_redaction_helper_detects_secrets(self):
        self.assertEqual(diag.redaction_violations("Bearer abcdefghijklmn", []),
                         ["bearer_token_present"])
        self.assertEqual(diag.redaction_violations('{"api_key": "x"}', []), [])
        self.assertEqual(
            diag.redaction_violations(f"key {FAKE_JEV_KEY}", [FAKE_JEV_KEY]),
            ["credential_value_present"])
        self.assertEqual(diag.redaction_violations("sk-or-v1-abcdef123456", []),
                         ["sk_token_present"])
        self.assertEqual(diag.redaction_violations("clean text", []), [])

    def test_assert_redacted_refuses_credential_bearing_record(self):
        record = {"provider": "jev", "note": FAKE_JEV_KEY}
        with patch.object(jc, "load_jev_credentials",
                          return_value=jc.JevCredentials(FAKE_JEV_KEY, "test")):
            with self.assertRaises(ValueError):
                diag._assert_redacted(record)


class ExecuteProbesTests(DiagnosticsSandboxTestCase):
    def _summary(self, directory, *, approval="ref", ok=True, provider="both"):
        registration = _registration()
        root = Path(directory)
        return diag.execute_probes(
            registration, repo_root=root, approval=approval,
            verification={"ok": ok, "failed": [] if ok else ["x"]}, provider=provider,
            jev_runner=lambda: diag.run_jev_probe(
                registration=registration, repo_root=root, approval=approval,
                state_builder=_fake_state,
                client_factory=lambda **kw: FakeJevClient(
                    response={"answers": {"q": {"answer": "a"}},
                              "usage": {"prompt_tokens": 1}})),
            ling_runner=lambda: diag.run_ling_probe(
                registration=registration, repo_root=root, approval=approval,
                writer_factory=lambda **kw: FakeLingWriter(outcome=_valid_outcome(), **kw)))

    def test_blocked_without_approval_makes_zero_calls(self):
        with tempfile.TemporaryDirectory(prefix="diag-exec-") as directory:
            summary = diag.execute_probes(_registration(), repo_root=Path(directory),
                                          approval=None, verification={"ok": True},
                                          jev_runner=lambda: self._boom(),
                                          ling_runner=lambda: self._boom())
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["stop_reason"], "missing_approval")
            self.assertEqual(summary["provider_calls"], 0)
            self.assertEqual(list(Path(directory).rglob("*.json")), [])

    def test_blocked_on_failed_preflight_makes_zero_calls(self):
        with tempfile.TemporaryDirectory(prefix="diag-exec-") as directory:
            summary = diag.execute_probes(_registration(), repo_root=Path(directory),
                                          approval="ref", verification={"ok": False},
                                          jev_runner=lambda: self._boom(),
                                          ling_runner=lambda: self._boom())
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["stop_reason"], "preflight_failed")
            self.assertEqual(summary["provider_calls"], 0)
            self.assertEqual(list(Path(directory).rglob("*.json")), [])

    @staticmethod
    def _boom():
        raise AssertionError("probe executed despite a blocked gate")

    def test_probes_write_fresh_diagnostic_artifacts(self):
        with tempfile.TemporaryDirectory(prefix="diag-exec-") as directory:
            summary = self._summary(directory)
            root = Path(directory)
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["provider_calls"], 2)
            jev_path = root / diag.DEFAULT_JEV_PROBE_OUTPUT
            ling_path = root / diag.DEFAULT_LING_PROBE_OUTPUT
            self.assertTrue(jev_path.is_file())
            self.assertTrue(ling_path.is_file())
            jev = json.loads(jev_path.read_text(encoding="utf-8"))
            ling = json.loads(ling_path.read_text(encoding="utf-8"))
            self.assertEqual(jev["error_class"], diag.CLASS_VALID)
            self.assertEqual(ling["error_class"], diag.CLASS_VALID)
            self.assertEqual(jev["attempt_count"], 1)
            self.assertEqual(ling["attempt_count"], 1)
            for record in (jev, ling):
                self.assertIs(record["authorizes_replay"], False)
                self.assertIs(record["availability_only"], True)

    def test_probe_outputs_are_fresh_and_never_overwritten(self):
        with tempfile.TemporaryDirectory(prefix="diag-exec-") as directory:
            self._summary(directory)
            path = Path(directory) / diag.DEFAULT_JEV_PROBE_OUTPUT
            first = path.read_bytes()
            second = diag.execute_probes(
                _registration(), repo_root=Path(directory), approval="ref",
                verification={"ok": True},
                jev_runner=lambda: self._boom(),
                ling_runner=lambda: self._boom())
            self.assertEqual(second["status"], "blocked")
            self.assertEqual(second["stop_reason"], "jev_probe_path_not_fresh")
            self.assertEqual(second["provider_calls"], 0)
            self.assertEqual(path.read_bytes(), first)

    def test_replay_v4_artifacts_untouched_by_probes(self):
        journal = REPO_ROOT / diag.REPLAY_V4_PINS["journal"]["path"]
        report = REPO_ROOT / diag.REPLAY_V4_PINS["report"]["path"]
        before = (journal.read_bytes(), report.read_bytes())
        with tempfile.TemporaryDirectory(prefix="diag-exec-") as directory:
            self._summary(directory)
        self.assertEqual((journal.read_bytes(), report.read_bytes()), before)

    def test_diagnostics_never_write_replay_paths(self):
        self.assertTrue(set(diag.OWNED_PATHS).isdisjoint(
            {pin["path"] for pin in diag.REPLAY_V4_PINS.values()
             if isinstance(pin, dict)}))
        with tempfile.TemporaryDirectory(prefix="diag-exec-") as directory:
            self._summary(directory)
            written = {str(path.relative_to(Path(directory)))
                       for path in Path(directory).rglob("*") if path.is_file()}
        for pin in diag.REPLAY_V4_PINS.values():
            if isinstance(pin, dict):
                self.assertNotIn(pin["path"], written)


class PreservationTests(DiagnosticsSandboxTestCase):
    def test_replay_v4_pins_still_match(self):
        for name, pin in diag.REPLAY_V4_PINS.items():
            if not isinstance(pin, dict):
                continue
            with self.subTest(name=name):
                path = REPO_ROOT / pin["path"]
                self.assertTrue(path.is_file())
                import hashlib
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                                 pin["sha256"])

    def test_build_registration_fails_closed_on_pin_drift(self):
        with tempfile.TemporaryDirectory(prefix="diag-pin-") as directory:
            root = Path(directory)
            for pin in diag.REPLAY_V4_PINS.values():
                if not isinstance(pin, dict):
                    continue
                target = root / pin["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("drifted", encoding="utf-8")
            with self.assertRaises(ValueError):
                diag.build_registration(repo_root=root)


if __name__ == "__main__":
    unittest.main()
