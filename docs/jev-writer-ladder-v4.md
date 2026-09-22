# J5d — writer observability repair and planning-low prompt ladder (#187)

Status: offline implementation and registration lock for review. **No live
calls, no v3 rerun, no family sweep, no #159 execution, no push/merge.** The
locked v4 registration carries `live_collection_authorized: false`; offline
locking is not live authorization. #159 remains blocked.

## 1. Why

The paced v3 pilot (commit `e6d9630`) completed all 102 planned calls with no
rate limit but produced 17/17 COMM silence and zero verified exposure, while the
earlier Ling-only treatment produced board use on 14/17 planning-low instances.
The v3 standalone writer is **not treatment-equivalent**: it gives the writer
only private clues plus an explicit silence token, whereas the original solver
saw the full task schema. Jev is the receiver and runs after the write decision,
so the all-silence result cannot be attributed to Jev.

## 2. Phase A — writer observability

`src/apart_incident_response/jev_ling_writer_v4.py` replaces the ambiguous
message-or-None parse with mutually exclusive outcomes:

- `deliberate_silence` — only an exact registered `SILENCE` response (or, for
  the original-grammar rung, a valid `ANSWER:` with no `MESSAGE:` line);
- `message_candidate` — a parsed `MESSAGE:` whose claim is one of the writer's
  private clues;
- `empty_output` — empty or whitespace-only content;
- `truncated_output` — `finish_reason == "length"`;
- `unparsed_output` — nonempty content matching neither grammar;
- `non_owned_claim` — a parsed `MESSAGE:` not in the writer's clues;
- `writer_error` — provider/transport/cap failure.

An empty or truncated completion is **never** recorded as silence. Each outcome
persists sanitized `finish_reason`, input/output/completion tokens when
supplied, content length, parser classification and physical-attempt provenance.
`raw_response_retained` stays false; credentials, complete headers, raw response
bodies and provider envelopes are never retained. The v3 Ling pacing, retry,
cap, redaction and physical-attempt accounting are inherited unchanged.

## 3. Phase B — treatment-equivalence audit

`src/apart_incident_response/jev_writer_treatment_audit.py` produces a
code-grounded field diff (artifact:
`runs/epic-126/jev-writer-treatment-audit-v4.json`). Divergent fields:
objective/instruction, candidates, family and complexity, condition and turn,
agent/finalizer role, joint clues, visible messages, seed behavior, token budget
and output grammar. Only private clues and temperature are equivalent (plus the
model family/endpoint). Conclusions: the v3 writer is not treatment-equivalent;
the writing difference is a property of the writer treatment, not Jev.

## 4. Frozen ladder

`src/apart_incident_response/jev_writer_ladder_v4.py` freezes six rungs over the
same 17 instances and six prompt forms, holding the Jev receiver, option set,
ownership rule, pacing and exposure instrumentation fixed:

| rung | writer-visible context | grammar |
|---|---|---|
| L0 | private clues only (current v3 writer) | explicit `MESSAGE:`/`SILENCE` |
| L1 | L0 + task instruction | explicit |
| L2 | L1 + candidate labels | explicit |
| L3 | L2 + condition, turn, role | explicit |
| L4 | exact original Ling schema (`treatment_prompt` fields) | original `ANSWER:` + optional `message:` |
| L5 | required exact-owned-claim positive control, **INDUCED**, excluded from voluntary-COMM inference | explicit, silence not allowed |

COMM_CONTROL remains turn-matched and never manufactures a message. Seed
behavior and token budget deviations from the original treatment are recorded and
bound into the successor protocol (the standalone writer sends no seed and uses
64 rather than 96 max tokens).

### Frozen interpretation rules

- **L4 or L5 writes while L0 stays silent** → emission is prompt/role dependent;
  register the reproducing rung before replay.
- **All voluntary rungs return deliberate silence** → demote planning-low.
- **Any empty/truncated/unparsed outcomes** → repair instrumentation or budget
  before scientific interpretation.
- **L5 fails** → transport/parser validation failed; the ladder is not
  interpretable.
- **No post-hoc rung selection** as a confirmatory claim; emission, exposure,
  post-read correlation and causal uptake stay separate; the three gates
  (structural necessity, owned informative inducement, causal uptake via matched
  real/placebo/null replay) still apply.

## 5. Successor registration

- Version: `stage2-jev-writer-ladder-v4`
- Status: `locked_for_jev_writer_ladder_v4`, `live_collection_authorized: false`
- Hash: `d2c40b2d4b437c3c25bcd83ad28a998294625c94cecb9ff093c94842521335bc`
- Paths: `runs/epic-126/jev-writer-ladder-preregistration-v4.json`,
  `jev-writer-ladder-v4.jsonl`, `jev-writer-ladder-report-v4.json`,
  `jev-writer-treatment-audit-v4.json`
- Caps: planned **408** requests; combined cap **500**; Jev **250**, Ling **250**
  (per physical attempt, retries included); cost cap **$1** (worst case
  `$0.172032`).
- Jev codec/protocol unchanged: `jev-choice-wire-v2|75190e25…`.
- Repository-backed verifier rejects old v1/v2/v3 output paths, v1 protocol keys,
  and ladder, timing, retry, model, endpoint, manifest, cap or hash drift.

## 6. Preflight and tests

Offline preflight: **ok true, 29/29 checks**, zero provider calls. Failed
preflight or absent approval makes zero calls. Focused v4 suites pass; the full
offline suite passes apart from the known environment-only bubblewrap failures
(`bwrap` not on `PATH`).

## 7. Future live command (NOT RUN; requires separate authorization)

```
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src \
  python -m apart_incident_response.jev_writer_ladder_pilot_v4 \
  --live --approval "<ref>"
```

#159 remains blocked until a ladder run yields verified eligible exposure and a
reviewer explicitly approves replay.
