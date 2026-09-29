# L01 — Legal baseline reconciliation and P06 truncation diagnosis

Task: Chainlink **#219** under **#218** under **#159**. Family `legal:low`,
milestone **L01**, predecessor **#215** (the closed terminal hypothesis:low
report), successor **#220 (L02)**. Protocol:
[hypotheses and sequential discovery/confirmation plan](jev-discovery-confirmation-plan.md).
Machine-readable evidence index:
[`runs/next-phase/legal/jev-legal-p01-evidence-v1.json`](../runs/next-phase/legal/jev-legal-p01-evidence-v1.json).

This is an offline reconciliation and diagnosis. No provider call, no probe, no
live journal, no authorization inference and no modification of frozen
hypothesis artifacts: every input below was read-only, and a process-wide audit
hook observed **zero network events** while the index was assembled. Nothing
here approves a legal:low route, budget, registration or collection.

## 1. Evidence index (recomputed, fail closed on drift)

Every digest was recomputed from the file on disk for this task; the prefixes in
the #219 task text were used as pins and never as the hash itself. A mismatch
fails the task closed.

| Input | Role | sha256 (recomputed) |
| --- | --- | --- |
| `docs/jev-hypothesis-low-terminal-decision.md` | #215 terminal family report (pin `89ef2aaf`) | `89ef2aafb5e28f12d0db707499c583d89cdcc490d105c23c3c56b39e11818d0b` |
| `runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection.jsonl` | #207 P06 discovery journal, 16 rows (pin `4e8de096`) | `4e8de096f2c30a6a36a94a0f79e5f450c2e196123e3eafe1c310a92c4f334c83` |
| `runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection-report.json` | #207 P06 collection report (pin `3086ceac`) | `3086ceac558ff922bd083db3795f5f1aa5c7127813daba8bfd71ae1fbef09d3c` |
| `runs/epic-126/replication/jev-replication-form-audit-v1.json` | #200 frozen form-capacity audit (pin `cb529cd6`) | `cb529cd61e0e662bfa19fc4998e89fa59a0bf0d63e14f77498035466d6bce89d` |
| `docs/jev-discovery-confirmation-plan.md` | protocol for the discovery/confirmation chain (pin `501e21b6`) | `501e21b6dea760371b0bf368046d8bacd203f6b92f0af754a7955d1f738677f7` |

Supporting inputs, also recomputed and pinned by this task:

| Input | Role | sha256 |
| --- | --- | --- |
| `runs/next-phase/jev-p04-discovery-registration-v1.json` | registered design, manifest, treatment, route, budgets | `78f7cd03c3afc12c94c3ba09839e4ac6ba667a3f68b96871571b274ae7d3ab11` |
| `runs/next-phase/jev-p05-discovery-lock-v1.json` | discovery lock | `75d12f7b1068c90d464da0145b0ff5f7f4bb20b116efcb5020077140a302c1d2` |
| `runs/next-phase/jev-discovery-authorization-record-v1.json` | historical hypothesis:low authorization record | `77962311dc723b7bf0eab0bda042078ec5d8a903120dd37b023c7b93d2e6d8eb` |
| `src/apart_incident_response/jev_ling_writer_v5.py` | writer-v5 `finish_reason` / output-cap classification source | `7ad131ab533dfbd2e3dcdbb23fefee57519226e79ba1d7b24733819560be944b` |
| `src/apart_incident_response/jev_p06_discovery_runner.py` | P06 runner: request identity, token ceilings, terminal stops | `bd93ae420c5fc9abdaca731b7d8020daba18f95dc124cac7d55d22cdc69616e2` |

Content pins recomputed rather than accepted from text: registration content
hash `6fa6149770b620cd3a026a6415f8e4d97e800e8af5237794de7b29fca6dacfac`,
lock content hash `9de4a61f9d46c47b55bbe7b8da9903c677c6461bf4af353007277835ed6a18b3`,
authorization scope digest
`938da9116805967253417c53709cd85d56d1913ac0142032d0d4732f50c04061`. The #215
scope table cites the recomputed journal, report and protocol digests verbatim,
so the terminal report is internally consistent with the bytes on disk. All
frozen #200 and terminal #207/#215 files are byte-identical before and after
this task.

## 2. Recomputation of the recorded stop

Recomputed from the 16 journal rows and cross-checked against the run report:

| Quantity | Recomputed | Report |
| --- | ---: | ---: |
| Planned / journaled rows | 16 | 16 planned, 16 journaled |
| Rows in registered manifest order, unique ids | 16/16 | seed list matches |
| Attempted / failed | 1 / 1 | counts.failed = 1 |
| Not attempted | 15 | counts.not_attempted = 15 |
| Completed (`ok`) / silences | 0 / 0 | counts.ok = 0, counts.silence = 0 |
| Ling physical calls | 3 | physical_used.ling = 3 |
| Jev physical calls | 0 | physical_used.jev = 0 |
| Provider calls total | 3 | provider_calls = 3 |
| Ling tokens in / out | 534 / 2029 | — (journal only) |
| Recorded cost | $0.00039726 | caps.cost_usd = $0.00039726 |

Cost recomputes exactly from the registered rates: (534 × $0.06 + 2029 ×
$0.18) / 1e6 = **$0.00039726**, inside the $0.20 collection ceiling and the
$0.30 program ceiling. Usage is 3/192 Ling physical requests and 0/48 Jev; no
unused budget authorizes a retry.

The stopped row is `hypothesis-00014c0b` (seed 85003, form `57ee9880…625e88a7b0c9`),
`failure_reason: writer_error:truncated_output`; the other 15 rows are
`not_attempted:truncated_output`, in manifest order, all seeds inside the
registered 85000–85511 primary window. Writer outcomes, in call order:
`deliberate_silence` (A, turn 0, ling-call-1), `deliberate_silence` (B, turn 0,
ling-call-2), `truncated_output` (A, turn 1, ling-call-3).

## 3. HTTP 200 `truncated_output` is not rate limiting

All three recorded attempts returned **status 200** with `error_class: null`,
`retry_ordinal: 0` (one physical attempt per logical call), no `retry-after` or
`retry-after-ms` header (`retry_after_present: false`,
`retry_after_ms_present: false`), and delays sourced only from client pacing
(`none`, `none`, `min_interval`).

A rate-limit stop under this writer would look different: HTTP 429 with
`error_class: writer_http_429_rate_limited`, a parsed retry-after header and
`retry_ordinal > 0`, because 429 is in the registered retryable statuses and
`rate-limited` is a registered writer terminal stop. None of those signals is
present, so the stop is an HTTP 200 writer output-cap classification, not rate
limiting. The distinction covers only the three recorded attempts; it is not
proof that no provider-side throttling existed elsewhere.

## 4. writer-v5 `finish_reason` / output-cap trace (offline)

Traced against the pinned source `src/apart_incident_response/jev_ling_writer_v5.py`
and confirmed by an offline probe grid (2 grammars × 4 `finish_reason` values ×
7 synthetic contents, no provider contact):

- `classify_writer_completion` returns `truncated_output` **only** when
  `finish_reason == "length"` on non-empty content (`empty_output` is checked
  first), and `length` on non-empty content always yields `truncated_output`.
- The P06 runner maps `truncated_output` into `WRITER_TERMINAL_OUTCOMES`, which
  stops the run; that is exactly the recorded `stop_reason`.
- The 1024-token budget is pinned three ways: the request identity check
  rejects `max_tokens != 1024` (`writer_request_identity_drift`), the offline
  preflight requires `writer_contract token_budget == 1024` and
  `ling_output_token_ceiling == 1024`, and the journal records `max_tokens:
  1024` on every attempt.

**Can be inferred about the 1024-token budget**

1. Every recorded request was sent with `max_tokens` 1024 (identity gate plus
   recorded request identity).
2. The third attempt returned non-empty content with `finish_reason: length`,
   so generation ended at the output cap rather than naturally — the registered
   1024-token budget was the binding constraint on that call.
3. `truncated_output` is the registered terminal outcome for that condition, so
   the stop and the 15 `not_attempted` rows follow the registered stop rule.
4. The truncated call cannot have exceeded the 1024 output-token ceiling
   (over-ceiling usage would be rewritten to `writer_token_budget_exceeded`),
   so the two `deliberate_silence` calls together produced **at least 1005** of
   the 2029 recorded output tokens and the truncated call at most 1024.

**Cannot be inferred**

1. `finish_reason`, `content_length` and per-call `completion_tokens` are not
   persisted in the journal or report; the `length` field is a code-level
   inference from the pinned writer-v5 source, not an observed value in the
   artifact.
2. The truncated call's exact token count is unknown: only row totals (534 in /
   2029 out) are recorded, so only the bound above is derivable.
3. Raw response bodies are never retained (`raw_response_retained: false`), so
   the truncated text cannot be re-examined or re-classified offline.
4. No counterfactual exists: nothing here shows what a larger budget would have
   produced, and one truncated call from one attempted seed cannot show that
   1024 tokens is systematically too small.
5. No scientific interpretation follows: the registered ladder rule treats
   `truncated_output` as an instrumentation/token-budget repair item before
   interpretation, and the run completed zero instances.

## 5. Historical facts: original L4X treatment and route

Recorded as history only — **not a new approval**:

- **Original L4X treatment** (registered for hypothesis:low, mode
  `exact-original-comm-bridge`): two agents × two turns, `provider_seed`,
  1024 max tokens, temperature 0.0, evolving visible-message state, original
  `ANSWER: <label> + optional MESSAGE: <claim>` grammar with answer-only
  silence; 4 Ling + 1 Jev logical call per seed (64 Ling + 16 Jev planned).
- **Route used by the stopped run**: paid OpenRouter SKU
  `https://openrouter.ai/api/v1/chat/completions` with
  `inclusionai/ling-3.0-flash-vl`, and Jev `https://api.typesafe.ai/v1/systemone`
  with `jev-1.13.0` on `jev-choice-wire-v2`.
- `authorization_carried_into_legal_family: false`. The legal family has no
  registered or authorized route: L04 must register one and L07 must supply a
  separate scope-bound user authorization before any provider call. OpenCode Go
  has no interchangeable Ling route in the current registration
  ([legal task sequence](jev-legal-task-sequence.md)).

## 6. Limitations

- Offline only; no provider call, probe, live journal or network event occurred
  or was authorized.
- Frozen #200 and terminal #207/#215 files are read-only inputs and were
  preserved byte-identically.
- The #215 report digest is pinned by an 8-character prefix in the task text;
  the full digest recomputed here matches that prefix and is recorded above.
- `finish_reason` is inferred through pinned source, not observed in the
  artifact; per-call token usage is not journaled.
- The truncation diagnosis has n = 1 attempted seed and no counterfactual retry.
- A failed or stopped predecessor never authorizes its successor: nothing here
  approves legal:low collection, a route, a budget or any provider call.

## 7. Checks (all offline, zero network events)

19/19 named checks pass in
`runs/next-phase/legal/jev-legal-p01-evidence-v1.json`, including:
`pinned_input_sha256_prefixes_match`,
`registration_and_lock_content_hashes_recompute`,
`journal_matches_registered_manifest`, `journal_status_counts`,
`provider_call_accounting`, `cost_recomputes_from_registered_rates`,
`report_cross_checks_journal`, `no_rate_limit_signal_on_any_attempt`,
`truncated_output_requires_finish_reason_length`,
`max_tokens_1024_pinned_by_gates_and_request_identity`,
`frozen_inputs_byte_identical_after_build`,
`zero_network_events_under_audit_hook` (`network_audit.events: 0`,
`provider_calls: 0`), and `no_approval_recorded_for_legal_family`.

Focused validation: `tests/test_jev_legal_p01_baseline.py` recomputes every
number above independently of the module, re-derives the `finish_reason`
classification offline, and runs the whole build under an audit hook with
`urllib.request.urlopen` replaced by a raising stub; the test fails if any
`socket.*`, `urllib.*`, `http.client.*` or `ftplib.*` event fires or if any
frozen input changes byte-for-byte.

## 8. Handoff to L02 (#220)

L01 closes with evidence paths, hashes, checks, limitations and this handoff.
L02 (`#220`) receives: the pinned baseline above, the recomputed stop
accounting, and the diagnosis that the hypothesis run stopped on an HTTP 200
writer output cap rather than rate limiting. L02 must derive legal form count,
independence, closure and fresh seed windows as findings — not inherit them from
the hypothesis family audit — and must not reuse the hypothesis 85000–87511
windows, instance ids or output paths. `#220` stays blocked until the plugin
records `#219` closed after reviewer approval; issue creation, this document and
any credential imply no authority. A failed predecessor never authorizes its
successor, and no provider call is authorized until the separate L07 gate.
