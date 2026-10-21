# Jev cross-family entropy program — v1 amendment

Status: prospective program direction, 2026-09-29. This document amends the
future work described in [the existing protocol](jev-discovery-confirmation-plan.md)
without changing that hash-pinned document or any completed registration, lock,
journal, or inference artifact. It grants no live authorization.

## Objective and units

Study whether **verified peer communication** reduces Jev's receiver Choice
entropy and whether that reduction accompanies useful uptake across a target of
**seven to eight distinct task families**. This is a breadth target, not a target
of seven to eight prompt forms per family. The existing generator names only
six families: `planning`, `hypothesis`, `legal`, `lexicon`, `poetry`, and
`reference`. One or two additional families would require a prospective,
versioned task design and independent audit; none is counted yet.

For a within-family matched real/placebo comparison, the prompt form remains
the inference unit. The registered two-sided sign-flip floor is `2/2^k`, where
`k` is the number of defensible independent forms in that family. More seeds
within four forms improve measurement of emission, coverage, variability and
guards, but cannot make that family's `.05` sign-flip test attainable. Adding
families also does not increase `k` for any one family. A cross-family claim
requires its **own** prespecified estimand, family-level analysis, missingness
rule and multiplicity/error-control contract; it cannot be obtained by pooling
forms or choosing the best observed family. Exact sign enumeration still
requires defensible form-level exchangeability; hash-distinct prompts alone do
not supply it.

If a future Holm family contains seven or eight simultaneously tested family
hypotheses, its first ordered p-value must be at most `.05/7` or `.05/8`.
Under the current two-sided sign-flip recipe, even `k=8` has a best-case floor
of `.0078125`, above both thresholds; `k=9` has a floor of `.00390625` and is
only **mathematically eligible**, subject to the remaining assumptions and
coverage. This calculation applies only if those seven or eight hypotheses
are actually in the frozen multiplicity set. It is not a demand for nine forms
in every descriptive family, and the historical `planning:low` test is outside
any new confirmation set.

## Starting evidence and honest classifications

* `planning:low`: conditional confirmatory entropy support on six frozen forms
  and the original paid Ling route: equal-form real-minus-placebo mean
  `-0.7775085` bits, exact two-sided `p=0.03125`, 95% form-mean t interval
  `[-1.1722, -0.3828]`, 17/17 complete pairs. Useful-uptake guards passed
  15/17; entropy support is not universal useful uptake. This historical result
  is not a prior or a cross-family finding.
* `hypothesis:low`: four forms (`p` floor `0.125`); discovery stopped on writer
  `truncated_output` before any completed instance or entropy measurement.
  Inconclusive, with no positive or negative entropy result.
* `legal:low`: the completed census proves a closed four-form space for the
  current generator/receiver configuration. Its `p` floor is `0.125`, so #221
  must classify this version as descriptive discovery or no-go. A redesign
  would be a new protocol boundary, not extra seeds added to this four-form
  version. Four forms also share a template; independence is not guaranteed.

The original queue `hypothesis → legal → lexicon → poetry → reference` is frozen
in the earlier P02 artifact. Preserve its historical meaning. A prospective
new queue or expansion must be versioned **before** using new outcomes to
select families; capacity-based prioritization may use only offline structural
facts and must disclose any departure from the frozen order. Do not silently
reorder the active legal chain or retrofit a prior registration.

## Prospective work before further live spend

1. Audit every remaining existing family offline across predeclared eligible
   complexity/regime cells. Enumerate canonical model-visible pre-read forms,
   prove or qualify closure, record per-form capacity and shared-template
   dependence, and report structural B→A need and authoritative information.
   Inventory prior IDs/seeds and inaccessible artifacts. Publish failures and
   descriptive-only classifications, not just promising families.
2. Specify one or two **additional** task families only after an offline design
   review shows substantial, multi-step tasks with distinct objectives,
   objective progress checks, an authentic peer-owned information opportunity,
   a matched inert placebo, and measurable receiver Choice uncertainty on a
   fixed option set. The task must preserve the open-ended work and meaningful
   intermediate artifact or decision; a tiny clue puzzle or synthetic
   microbenchmark does not satisfy the expansion goal. The fixed receiver
   decision can be a registered checkpoint within the larger task, but its
   validity and relationship to end-task success must be audited. Audit new
   families like existing ones before assigning them a place in a prospective
   queue. A paper's benchmark name is not by itself a Jev task family or an
   independent form.
3. Freeze which families and hypotheses enter any new confirmatory set, the
   family-level multiplicity rule (default Holm at `.05` unless a different
   interpretation is registered), attainable adjusted decisions, treatment,
   coverage/missingness thresholds, and stopping rules **before** confirmation
   outcomes. Account for registered failures and unavailable families. A goal
   of seven to eight families is a target for breadth, not a promise that seven
   to eight will yield valid confirmatory tests or positive results.
4. Run discovery and any held-out confirmation one family at a time under a
   fresh reviewed registration and separate scope-bound authorization. Report
   five levels separately: structural need, voluntary emission, verified
   exposure, entropy change, and matched-contrast useful uptake. Retain all
   silences, invalid results, stops and guard failures in the appropriate
   denominators. A detector analysis must be separately defined and validated;
   a lower entropy value alone does not establish detection accuracy or task
   success.

## Relation to the motivating paper

[Park et al., *Scaling Discovery through Test-Time Communication*,
arXiv:2609.21032v1](https://arxiv.org/html/2609.21032v1) compare communicating
teams with equal-resource independent attempts on ARC-AGI-3, polyomino packing,
and MNIST classifier compression. Their shared workspace carries intermediate
results and failures, and objective feedback lets agents verify progress before
adopting an idea. They also report settings where communication is less helpful
when compute or useful feedback is limited. These task and control ideas
motivate heterogeneous, prospectively specified Jev cases and explicit
objective-information/uptake guards. Their performance results are **not** Jev
Choice-entropy measurements, do not validate an entropy detector, and cannot
serve as effect-size priors for this program. Any ARC-like, optimization or
compression adaptation needs its own fixed decision interface and source,
template, treatment and evaluation audit before it becomes a family here.

## Chainlink implementation

* #221 makes the legal four-form attainability decision offline. It cannot
  promote this generator version to confirmatory status or authorize calls.
* #227 is the separate offline cross-family capacity and expansion audit under
  #159. The worker order is #221 → #227 → #222 → #223 → #224; the legal loop
  dispatches one issue at a time and stops before #225. The audit supplies the
  prospective breadth inventory before legal registration work continues. Its
  outcome can demand a new program version, but cannot mutate #221's historical
  census or an eventual L04 lock.
* #218 retains L04–L08's sequential legal gates. #225 remains the explicit
  legal live-authorization pause; the previous hypothesis reference never
  carries forward. A completed legal discovery block is not held-out
  confirmation.
* The scoped offline launcher uses the explicitly free
  `opencode/mimo-v2.6-flash-free` model for worker and reviewer by default.
  This changes only the OpenCode coding-agent route; it does not revise or
  authorize any experimental Ling/Jev route or live collection.
