# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- Attach per-turn logprobs and coverage to agent artifacts (#99)
- Capture OpenRouter token probabilities at the Pi provider boundary (#98)
- Add OpenRouter one-shot goal inference with saved logprobs (#96)
- Define shared partial-probability artifacts and entropy calculations (#95)
- Add OpenRouter as an isolated Pi experiment endpoint (#97)
- Persist and organize experiment run logs in workspace (#73)
- Fail fast on uninitialized Pi submodule in Docker build (#75)
- Add local Qwen3-8B logprobs data path for entropy metrics (#72)
- Define neutral agent prompts (#26)
- Implement Task 1 submission (#23)
- Integrate delivered tool service and validate real Pi extension (#59)
- Add append-only board and containment policies (#3)
- Add constrained agent tool interface (#2)
- Run manual two-agent board smoke test (#21)
- Add board contract tests (#20)
- Implement condition policies (#19)
- Implement cursor-based board_read (#18)
- Implement board_append (#17)
- Capture tool-call results (#15)
- Implement tool validation (#14)
- Implement board tools (#13)
- Implement core task tools (#12)
- Add controlled experiment runtime isolation (#1)
- Pin Pi runtime and model configuration (#8)
- Update MVP plan with response-state entropy detection (#50)

### Fixed
- Fix board IPC integration and CLI tool wiring (#58)

### Changed
- Fix planning-high empty outputs (token-budget truncation) before further collection (#168)
- J2 — Implement offline Jev Choice receiver adapter (#155)
- J1 — Freeze finite-task and communication invariants (#154)
- Run preregistered Ling board-necessity screen on corrected generator (#162)
- Fix provider seed range and re-register the smoke protocol (#167)
- Preregister distinct cells, paired inference and missingness before fresh Ling screen (#165)
- Separate structural board need from communication behavior and causal uptake (#164)
- Audit pooled/joint equality and peer necessity before new screens (#161)
- Lock FULL, ORACLE and runner treatment schemas (#163)
- Make clue-consistent feasible sets authoritative for D_idx, I_m and scoring (#166)
- Support genuine two-role Task 1 fixtures and explicit real-anchor swarm sizes (#100, #94)
- Capture Ollama per-turn probability records with stable per-agent sampling seeds (#91)
- Confirm OpenRouter logprob support for a pinned model and route (#93)
- Run single-agent task calibration (#47)
