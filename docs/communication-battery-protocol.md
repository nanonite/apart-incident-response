# Communication Battery Protocol

`two-agent-iso-full-comm-v1` is an additive experimental contract. It does
not rename or reinterpret legacy C0/C1/C2 or Exp1 artifacts.

## Conditions

- `ISO`: each agent sees private information and has no peer channel.
- `FULL`: each agent receives the joint information directly; communication is
  not needed.
- `COMM`: each agent sees private information and may use an optional board.

Instances are generated independently by seed. The three condition runs for a
seed share an instance ID and pair ID. The controller keeps answer sets and
keys out of agent-visible manifests.

## Measurements

For receiver-specific feasible sets, the exact message value is

`Delta I_m = log2(|S_before|) - log2(|S_after|)` bits.

For example, a receiver set changing from 8 to 2 candidates carries
`log2(8)-log2(2) = 2` bits. A duplicate claim has exactly zero gain.

An ambiguous or unvalidated natural-language message has unknown information,
not zero information. A contradictory validated claim is invalid. Duplicate
claims have zero gain. R/H/N is assigned after measuring normalized feasible-set
reduction; generator labels are retained only for calibration diagnostics.

`C_need` is `P(success|FULL)-P(success|ISO)`. Communication efficiency is
post-read correlated bits divided by communication tokens. `phi` is fitted from
checker-supported correlation outcomes and experimental factors, excluding message volume.

## Provenance and entropy gate

Board write, peer read, first subsequent model output, and checker-supported post-read correlation
are separate events. Output logprob entropy is attached to the first model
output after actual message exposure. Read-event entropy is never used. The
turn-8 intervention and matched placebo belong to the separately gated entropy
extension. Missing logprob coverage and invalid runs remain in denominators.

The staged plan is offline fixtures, provider capability smoke, bounded pilot,
then an explicit budget/power decision. The proposed full battery is not
authorized by implementation completion alone. The current bounded-pilot
candidate is DeepSeek V4.1 Flash with a hard `$20` ceiling; no API call is
authorized until the offline and capability gates pass.
