# Hypothesis:low terminal family decision (P14 / #215)

## Decision

**Inconclusive due to missingness after a registered terminal stop.** The P06
discovery collection stopped at its first planned seed with
`writer_error:truncated_output`. No seed completed and no discovery estimate or
matched contrast exists. This is neither evidence for nor evidence against
entropy reduction. The registered four-form `hypothesis:low` design was a
descriptive pilot in any event: its exact two-sided sign-flip floor is 0.125,
above 0.05. This report uses the terminal-stop exception in
[the protocol](jev-discovery-confirmation-plan.md); it does not complete P06 or
the P07–P13 gates.

The reported failure is a writer-output failure, not a provenance or treatment
integrity finding. All three recorded Ling HTTP attempts returned status 200.
No rate-limit response or Jev request is recorded. The journal retains one
failed seed and all 15 remaining seeds as `not_attempted:truncated_output`.
The stopped registration cannot be resumed, retried, or reused with different
seeds or paths.

## Scope and immutable evidence

| Artifact | SHA-256 |
| --- | --- |
| [P02 scope freeze](../runs/next-phase/jev-p02-scope-freeze.json) | `c254c45c748a33d9f1514f2a497fe6fbc5d96fbb7553eb142d8fe22a4b64c474` |
| [P04 registration](../runs/next-phase/jev-p04-discovery-registration-v1.json) | `78f7cd03c3afc12c94c3ba09839e4ac6ba667a3f68b96871571b274ae7d3ab11` |
| [P05 lock](../runs/next-phase/jev-p05-discovery-lock-v1.json) | `75d12f7b1068c90d464da0145b0ff5f7f4bb20b116efcb5020077140a302c1d2` |
| [Discovery authorization](../runs/next-phase/jev-discovery-authorization-record-v1.json) | `77962311dc723b7bf0eab0bda042078ec5d8a903120dd37b023c7b93d2e6d8eb` |
| [P06 journal](../runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection.jsonl) | `4e8de096f2c30a6a36a94a0f79e5f450c2e196123e3eafe1c310a92c4f334c83` |
| [P06 report](../runs/next-phase/hypothesis/jev-discovery-v1/jev-discovery-collection-report.json) | `3086ceac558ff922bd083db3795f5f1aa5c7127813daba8bfd71ae1fbef09d3c` |
| [Protocol](jev-discovery-confirmation-plan.md) | `501e21b6dea760371b0bf368046d8bacd203f6b92f0af754a7955d1f738677f7` |

The P06 report names registration hash
`6fa6149770b620cd3a026a6415f8e4d97e800e8af5237794de7b29fca6dacfac`,
lock hash `9de4a61f9d46c47b55bbe7b8da9903c677c6461bf4af353007277835ed6a18b3`,
and authorization scope digest
`938da9116805967253417c53709cd85d56d1913ac0142032d0d4732f50c04061`.
The authorization covered this discovery collection and optional exploratory
replay only. It did not authorize held-out P11 collection.

## Denominator and failure accounting

The fixed P04 manifest has 16 distinct instances, four in each of four prompt
forms. The journal has one row for each instance in exactly manifest order,
with no duplicate IDs. The first instance (`hypothesis-00014c0b`, seed 85003,
form `57ee9880…625e88a7b0c9`) was attempted and failed. Its first two Ling
writer calls returned `deliberate_silence`; the third returned
`truncated_output`, so **the instance as a whole is a failure, not an observed
silence or completed emission**. The remaining 15 instances were not
attempted. There were no accepted B-to-A board writes, verified A reads,
information-bearing messages, Jev receiver calls, or replay branches.

| Frozen form (prefix) | Planned | Attempted | Failed | Not attempted | Completed | Real/placebo pairs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `57ee9880` | 4 | 1 | 1 | 3 | 0 | 0 |
| `a0e4ffd0` | 4 | 0 | 0 | 4 | 0 | 0 |
| `a95806c8` | 4 | 0 | 0 | 4 | 0 | 0 |
| `fc05e963` | 4 | 0 | 0 | 4 | 0 | 0 |
| **Total** | **16** | **1** | **1** | **15** | **0** | **0** |

For discovery, emitted, eligible, valid, and complete counts are all zero;
missing complete instances are 16/16 (one failed, 15 not attempted). For
exploratory and held-out replay, the denominator of **executed** branches is
zero; no branch outcome or contrast is defined. The optional exploratory
replay was not run. No imputation, seed replacement, form removal, guard
filtering, or effect estimate is applied. The registered minimum of one
complete instance per form is unmet in all four forms.

There were three paid Ling physical attempts, zero Jev attempts, 534 Ling
input tokens and 2,029 Ling output tokens. Recorded cost was **$0.00039726**,
within the discovery ceiling of $0.20 and the program ceiling of $0.30.
No unused budget authorizes a retry. The observed status-200 responses do not
establish that rate limits caused this stop.

## Five evidence levels

| Level | Observed evidence | Limit |
| --- | --- | --- |
| Structural need | The attempted instance's recorded geometry has `finalizer_needs_peer=true`; the P03/P04 four-form structural census remains the design basis. | Structure is not voluntary communication. Fifteen live instances have no execution evidence. |
| Voluntary emission | Two writer turns inside the failed instance were classified `deliberate_silence`; no completed instance has an emitted claim or a completed silence outcome. | The third writer turn truncated, so no seed-level emission rate can be estimated. |
| Verified exposure | Zero accepted B-to-A writes and zero verified A reads. | No observed delivery or receiver exposure. |
| Entropy reduction | No Jev receiver request or entropy vector. | Reduction is undefined, not zero. |
| Matched-contrast causal uptake | No real/placebo/null replay branch or complete pair. | The registered equal-form estimand, interval and test are unavailable. |

## Task disposition and next-family handoff

#207 remains open as a terminally stopped collection. #208–#214 remain open
with explicit not-run reasons on each issue: there is no completed discovery
screen on which to base P07, no P08–P10 replay registration/authorization, no
P11 held-out collection, and no P12–P13 inference or guard accounting. This
P14 report is the only successor routed around those blockers. Their open
status must not be interpreted as work in progress or a successful gate.

The frozen P02 candidate order after `hypothesis` is **legal, lexicon, poetry,
reference**, subject to the same outcome-blind structural preconditions. The
next action is offline P01–P04-style scoping and form-capacity review for
`legal:low`, without reusing this stopped registration or its live artifacts.
If any later live stage is proposed, it needs a fresh versioned registration,
fresh paths, reviewed lock, and a separate explicit authorization covering its
stage, route, request caps, and cost caps. The P06 authorization does not carry
forward. The `hypothesis` family has no supported causal decision from this
run.
