# Final report outline

## Results review first

**As a monitoring tool, you're right: it's weak.**
- **After-the-fact detection:** the strong separation for Qwen (AUC 0.85 to 0.96) uses the whole window from turn 8 to 20. That's a review after the run, not an early warning.
- **Live alarm:** with false alarms held at 5%, CUSUM caught Qwen's disrupted runs 15 to 25% of the time at T=1 and 40 to 50% at T=0.5. The 95 to 100% at T=0 isn't trustworthy, because Qwen's base runs there contain only 2 distinct trajectories, which pushes the threshold very low.
- **Other models:** gpt-4o-mini and Llama stay at 26% or below, not far above the 5% false-alarm rate.
- **At fleet scale** (my own illustration, not a measured result): if 1% of runs were disrupted, catching 45% of them with 5% false alarms would mean only about 8% of alarms are real.

**What holds as a finding: entropy does respond to a broken sandbox, without reading any messages or chain of thought.** Five patterns hold up across the data:
1. **Every model used the channel** (179 of 180 switch runs verified), so the differences come from how sensitive each model is.
2. **The direction depends on what you measure (this corrects my earlier claim).** I said entropy never went down after foreign text. It does:
   - Qwen's *decision* entropy goes up.
   - Qwen's *log-writing* entropy goes down: placebo minus base at T=1 is −0.096 bits (Holm p = 0.036), and switch minus placebo at T=0.5 is −0.088 bits (Holm p = 0.020).
   - Likely reading (not yet tested): the agent is less sure what to do next, but writes more predictably, possibly because it repeats the foreign text.
3. **Under sampling, the arrival of text matters more than what it says:** at T=1 and T=0.5, no model reacted more to real messages than to placebo text.
4. **Lower temperature makes the signal cleaner:** only at T=0 did real messages and placebo separate, and only for Qwen.
5. **No coupling between agents:** mutual information stayed within 0.025 bits of chance. In a log that each agent reads when it chooses, communication shows up as a disturbance inside each receiver, not as the agents moving in sync.

**Still untested:** the jump right after a read (own < partner < placebo) appears for gpt-4o-mini and Qwen at every temperature, but so far it's only raw means. It needs a call-level test before it goes in the paper.

**Proposed framing:** this is a first step toward monitoring from the probability layer, not a finished monitor. It shows that entropy picks up a sandbox breach without message logs or chain of thought, and it shows exactly what's still missing: calibration per model, stable decoding, and some way to tell information from noise.

## Paper plan (7 pages, building on the report_writing version)

**Abstract:** problem, testbed, the five patterns, and "an initial step, not a finished monitor".

**1. Introduction**
- In the Hugging Face incident, isolated agents turned a shared resource into a hidden channel, and every such channel ends by putting unsanctioned text into a sandboxed agent's context.
- We wonder if there's a way to create a monitor different from industry standards, one that explores the relationship between entropy and the system.
- Keep the report_writing incident narrative, condensed: the "Agent seeks [filename]" note, the board rebuilt in directory names, early signals that no one acted on, and a collective that looked like one attacker from outside.
- End with the contributions.

**2. Related work** (keeping the report_writing structure)
- **Entropy as a detection primitive:** DDoS detection (Lakhina), where entropy of traffic distributions exposes attacks without reading payloads. This is the direct analogy to our idea.
- **Past work:** Farquhar et al. (2024, Nature) measure entropy on single models, and Zhao and Zhu measure it in agents built to talk to each other.
- **Monitoring standards:** log analysis and chain-of-thought review (Baker, Greenblatt), which depend on readable content; also activation probes (Abdelnabi), which need white-box access.
- **Novelty:** no one has used entropy to watch for the moment isolation breaks between sandboxed agents, with a placebo and verifiable ground truth.

**3. Methods**
- **3.1 Entropy framework (condensed):**
  - Eq. 1: Shannon entropy.
  - Eq. 2: softmax with temperature.
  - Eq. 3: token entropy.
  - One sentence each on predictive vs. semantic entropy, and why we use predictive.
  - Eq. 4: the total-correlation decomposition, reduced to the two-agent mutual information, with X_i correctly defined as the action per turn pooled across runs.
- **3.2 Testbed (the important part):** we rebuilt the incident as a small testbed: two sandboxed agents, each holding one password to a task neither can finish alone, and a shared log that stays closed, opens mid-task (real communication) or delivers foreign noise (placebo), run with three models at temperatures 0, 0.5 and 1.
- **3.3 Walking through the architecture figure,** one short paragraph per element, each tied to the incident:
  - **Task T:** the same deliverable for both agents, unsolvable alone, like the ExploitGym tasks no model had solved.
  - **Agents:** model M plus harness H with a fresh context every turn, like separate evaluation runs.
  - **Passwords and encrypted assets:** legitimately issued credentials. Random values make every leak traceable.
  - **Shared append-only log with author tags:** the package mirror used as a board.
  - **WRITE_LOG and READ_LOG through the filter:** the access control that was supposed to isolate runs.
  - **Switch at turn 8:** the moment the channel opens, which is what a monitor has to catch.
  - **Donor log (placebo):** foreign but useless content, the control that separates "text arrived" from "information arrived".
- **3.4 Protocol:** models and pinned providers, temperatures 0 / 0.5 / 1, how Qwen's log-probabilities were restored, 20 runs per cell, the solvability gate, the deterministic checker, and the analysis (each run compared with itself before and after the switch, permutation tests, CUSUM). Pi gets one sentence as the team's realistic sandbox runtime that this harness strips down.

**4. Results** (organised by pattern, not by model)
- Channel use (Table 1).
- Disruption changes entropy, with direction depending on the measure (disruption figure plus the log-writing finding).
- Text arriving beats content under sampling (switch-minus-placebo figure).
- Temperature and determinism.
- No coupling: disturbance inside the receiver, not synchrony.
- Monitor performance, stated honestly (CUSUM numbers and the precision problem).
- Each part keeps the Observation → Robustness → Interpretation structure.

**5. Discussion:** push the novelty.
- Monitoring from the probability layer is independent of content and channel, so it survives encoding, steganography and chain-of-thought obfuscation, which is exactly what defeated log scans in the incident.
- The architecture lesson: in pull-based channels, look for disturbance in each receiver, not synchrony between agents.
- A path to a better monitor: sibling-run baselines, low-temperature canary runs, and combining the signal with probes.

**6. Limitations and future work**
- **Time:** a weekend sprint; the framing came after the first hypothesis failed.
- **Compute:** $4.18, one task, three models, 20 runs per cell, top-20 log-probabilities only, one provider with noisy values.
- **More experiments:** Pi with local open-weight models, more agents, prompt-injection content, agents that try to evade the monitor, and a trained classifier on entropy trajectories (from report_writing).

**7. Conclusion:** Entropy detects that a sandboxed agent's context was disrupted, for some models and best at low temperature, but not whether the disruption was communication.

## Before writing
1. Run the call-level test for the post-read jump, and double-check the log-writing decrease (T=0 is blank because Qwen's base runs had no log entries in that window). Both use the existing stats only; the raw data stays untouched.
2. Recover the report_writing intro and related-work text as the base (plus its `kramar2026probes` reference, which I'll verify first).
3. Write the paper, compile it to 7 pages, and show you the PDF **before** committing anything.
