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
- Confirm OpenRouter logprob support for a pinned model and route (#93, main)
- Enforce board engagement as a hard gate on task_submit for C1/C2 (#99)
- Inject redundant clean tool schema to work around Ollama's Qwen3 tools-field templating bug (#97)
- Single-sweep before/after comparisons can't isolate small-lever effects from seed variance (#98)
- Task 1's evidence-role rotation is incompatible with agent_count < 3 for 1-in-3 seeds (#96)
- Add condition-scoped system-prompt guidance via --append-system-prompt (#95)
- Expose --agent-count on the real-anchor CLI to exercise swarm-size variation (#94)
- Reveal permitted filenames in task_read/task_query/task_submit permission errors (#93)
- Inject explicit tool-usage guidance into the agent task prompt (#92)
- Pin Ollama sampling seed/temperature to reduce qwen3 run-to-run variance (#91)
- Run single-agent task calibration (#47)
