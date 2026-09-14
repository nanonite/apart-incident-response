"""Dependency-ordered controller for isolated C0/C1/C2 swarms."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .board_storage import BoardStore
from .capabilities import CAPABILITY_PROFILES, get_capability_profile
from .runtime import AgentIdentity, AgentRun, Condition, ExitStatus, RuntimeConfig, RuntimeConfigError, SystemBudget, create_isolated_workspace, probe_ollama
from .task_one import TaskOneInstance, task_one_bundle_for_agent, task_one_instance, materialize_task_one_bundle
from .task_tools import TaskCatalog, TaskDefinition, TaskToolService
from .tool_service import BoardToolService, ConstrainedToolService
from .telemetry import JsonlEventLog, write_derived_artifacts
from .run_artifacts import artifact_links_for_run, write_condition_index
from .run_paths import RunDirectory, RunPathError, create_run_directory


PROTOCOL_VERSION = "controlled-n-agent-c0-c1-c2-v1"
FACTOR_LEVELS: Mapping[str, tuple[str, ...]] = {
    "agent_count": ("2", "3", "4"),
    "capability_profile": tuple(CAPABILITY_PROFILES),
    "difficulty": ("easy", "anchor", "hard"),
    "transformation_cadence": ("per_turn", "every_2_turns", "every_4_turns"),
    "model": ("configured", "verified_second_tier"),
}


@dataclass(frozen=True)
class ExperimentProtocol:
    """Predeclared protocol shared by all controller runs."""

    version: str = PROTOCOL_VERSION
    anchor_agent_count: int = 3
    supported_agent_counts: tuple[int, ...] = (2, 3, 4)
    conditions: tuple[Condition, ...] = (Condition.C0, Condition.C1, Condition.C2)
    anchor_task: str = "task-1"
    anchor_difficulty: str = "anchor"
    anchor_seeds: tuple[int, ...] = (1, 2, 3, 4, 5)
    default_capability_profile: str = "task-diagnostic-v1"
    transformation_windows: Mapping[str, int] = field(default_factory=lambda: {"per_turn": 1, "every_2_turns": 2, "every_4_turns": 4})
    factor_levels: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: FACTOR_LEVELS)

    def __post_init__(self) -> None:
        if self.version != PROTOCOL_VERSION:
            raise RuntimeConfigError("unsupported experiment protocol version")
        if self.anchor_agent_count not in self.supported_agent_counts:
            raise RuntimeConfigError("anchor agent count must be a supported n level")
        if self.conditions != (Condition.C0, Condition.C1, Condition.C2):
            raise RuntimeConfigError("protocol conditions must be ordered C0, C1, C2")
        if self.anchor_task != "task-1":
            raise RuntimeConfigError("the anchor protocol task must be task-1")
        if self.anchor_difficulty not in {"easy", "anchor", "hard"}:
            raise RuntimeConfigError("unknown anchor difficulty")
        for count in self.supported_agent_counts:
            if isinstance(count, bool) or not isinstance(count, int) or count < 2:
                raise RuntimeConfigError("supported agent counts must be integers >= 2")
        for profile in (self.default_capability_profile, *self.factor_levels.get("capability_profile", ())):
            get_capability_profile(profile)

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.version,
            "run_unit": "one isolated swarm, one condition, one task instance and one aggregate budget",
            "conditions": [condition.value for condition in self.conditions],
            "condition_summary": {
                "C0": {"board_access": "none", "peer_visibility": "none"},
                "C1": {"board_access": "append_and_read", "peer_visibility": "all_peer_messages"},
                "C2": {"board_access": "append_and_read", "peer_visibility": "own_messages_only"},
            },
            "primary_contrast": "C1 versus C2",
            "secondary_contrasts": ["C1 versus C0", "C2 versus C0"],
            "condition_order": "deterministic seed-rotated counterbalance; analysis returns C0/C1/C2 order",
            "anchor": {
                "task_id": self.anchor_task,
                "difficulty": self.anchor_difficulty,
                "agent_count": self.anchor_agent_count,
                "seeds": list(self.anchor_seeds),
            },
            "supported_agent_counts": list(self.supported_agent_counts),
            "default_capability_profile": self.default_capability_profile,
            "factor_levels": {key: list(value) for key, value in self.factor_levels.items()},
            "transformation_windows": dict(self.transformation_windows or {}),
            "matched_within_triplet": [
                "task fixture and seed", "prompt", "agent count", "model", "capability profile",
                "aggregate token/tool-call ceilings", "per-agent envelope", "timeout", "validator",
            ],
            "failure_policy": {
                "record_and_exclude_from_success_denominator": ["launch_error", "timed_out", "budget_exhausted", "failed"],
                "never_silently_drop": True,
                "do_not_impute_missing_model_data": True,
            },
            "inference_scope": "five-seed cells are descriptive pilot evidence; no unsupported causal or statistical claim",
        }


@dataclass(frozen=True)
class SwarmRun:
    run_id: str
    triplet_id: str
    condition: Condition
    seed: int
    artifact_root: Path
    results: tuple[Mapping[str, Any], ...]
    metrics: Mapping[str, Any]


def _safe_component(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in value):
        raise RuntimeConfigError(f"{label} must be a safe identifier")
    return value


def _safe_level(value: Any) -> str:
    text = str(value)
    return "".join(character if character in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" else "_" for character in text)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


class ExperimentController:
    """Run one condition or a matched C0/C1/C2 triplet without manual launch orchestration."""

    def __init__(
        self,
        config: RuntimeConfig,
        artifact_root: Path | str,
        *,
        invocation: RunDirectory | None = None,
        extension: Path | None = None,
        protocol: ExperimentProtocol | None = None,
        run_class: str = "experimental",
        verified_models: Sequence[str] = (),
    ) -> None:
        self.config = config
        self.protocol = protocol or ExperimentProtocol()
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self.invocation = invocation
        if invocation is not None and invocation.path != self.artifact_root:
            raise RuntimeConfigError("invocation path must match artifact_root")
        self.extension = extension.expanduser().resolve() if extension is not None else None
        if self.extension is not None and not self.extension.is_file():
            raise RuntimeConfigError(f"experiment extension does not exist: {self.extension}")
        if run_class not in {"experimental", "harness_check", "calibration"}:
            raise RuntimeConfigError("run_class must be experimental, harness_check, or calibration")
        self.run_class = run_class
        self.verified_models = frozenset(verified_models)

    @property
    def run_uuid(self) -> str | None:
        return self.invocation.run_uuid if self.invocation is not None else None

    @property
    def output_base(self) -> Path:
        return self.invocation.base_dir if self.invocation is not None else self.artifact_root

    def _config_for_n(self, agent_count: int, model: str | None = None) -> RuntimeConfig:
        if agent_count not in self.protocol.supported_agent_counts:
            raise RuntimeConfigError(f"agent count {agent_count} is not predeclared")
        # Per-agent envelope is pinned by config and held constant across swarm
        # sizes so that varying agent_count studies coordination, not a shrinking
        # per-agent budget. The aggregate ceiling scales up with agent_count instead.
        token_budget = self.config.per_agent_token_budget
        tool_budget = self.config.per_agent_tool_call_budget
        if token_budget <= 0 or tool_budget <= 0:
            raise RuntimeConfigError("aggregate budget cannot provide a positive envelope to every agent")
        selected_config = self.config if model is None else self.config.for_model(model)
        return replace(
            selected_config,
            agent_count=agent_count,
            per_agent_token_budget=token_budget,
            per_agent_tool_call_budget=tool_budget,
            aggregate_token_budget=token_budget * agent_count,
            aggregate_tool_call_budget=tool_budget * agent_count,
        )

    def _run_manifest(
        self,
        *,
        run_id: str,
        triplet_id: str,
        condition: Condition,
        seed: int,
        run_config: RuntimeConfig,
        instance: TaskOneInstance,
        capability_profile: str,
        observation_window_turns: int,
        ollama_probe: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        assignments = []
        for number in range(1, run_config.agent_count + 1):
            bundle = task_one_bundle_for_agent(instance, number)
            assignments.append({
                "agent_id": f"agent-{number}",
                "agent_number": number,
                "evidence_role": bundle.agent_id,
                "path": Path(bundle.relative_path).name,
                "bundle_sha256": hashlib.sha256(bundle.content.encode("utf-8")).hexdigest(),
            })
        task_manifest = instance.manifest()
        task_provenance = task_manifest.get("token_provenance")
        if not isinstance(task_provenance, Mapping):
            raise RuntimeConfigError("Task 1 manifest is missing token provenance")
        owner_roles_by_token = task_provenance.get(
            "private_token_owner_roles",
            task_provenance.get("private_token_owners", {}),
        )
        if not isinstance(owner_roles_by_token, Mapping):
            raise RuntimeConfigError("Task 1 manifest has invalid private owner roles")
        owner_agent_ids_by_token: dict[str, list[str]] = {}
        for token, roles in owner_roles_by_token.items():
            if not isinstance(token, str) or not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
                raise RuntimeConfigError("Task 1 manifest has invalid private owner roles")
            owner_agent_ids_by_token[token] = sorted({
                item["agent_id"]
                for item in assignments
                if item["evidence_role"] in roles
            })
            if not owner_agent_ids_by_token[token]:
                raise RuntimeConfigError(f"Task 1 private owner roles do not resolve for {token}")
        task_manifest["token_provenance"] = {
            **task_provenance,
            "private_token_owner_roles": {
                token: list(roles) for token, roles in owner_roles_by_token.items()
            },
            "private_token_owner_agent_ids": owner_agent_ids_by_token,
            "repeated_evidence_roles_expand_owners": True,
        }
        return {
            "schema_version": 1,
            "run_class": self.run_class,
            "protocol": self.protocol.to_dict(),
            "run_id": run_id,
            **({
                "invocation_run_id": self.invocation.run_id,
                "run_uuid": self.invocation.run_uuid,
                "model": run_config.model,
            } if self.invocation is not None else {}),
            "triplet_id": triplet_id,
            "condition": condition.value,
            "seed": seed,
            "task": task_manifest,
            "factor_assignment": {
                "agent_count": run_config.agent_count,
                "capability_profile": get_capability_profile(capability_profile).to_dict(),
                "difficulty": instance.difficulty,
                "transformation_cadence": self._cadence_name(observation_window_turns),
                "observation_window_turns": observation_window_turns,
                "model": run_config.model,
            },
            "runtime": run_config.to_dict(),
            **({"ollama_probe": dict(ollama_probe)} if ollama_probe is not None else {}),
            "prompt": run_config.prompt_for(instance.task_id, seed),
            "prompt_sha256": hashlib.sha256(run_config.prompt_for(instance.task_id, seed).encode("utf-8")).hexdigest(),
            "budget": {
                "aggregate_token_budget": run_config.aggregate_token_budget,
                "aggregate_tool_call_budget": run_config.aggregate_tool_call_budget,
                "per_agent_token_budget": run_config.per_agent_token_budget,
                "per_agent_tool_call_budget": run_config.per_agent_tool_call_budget,
            },
            "assignment": assignments,
            "launch": {
                "agent_ids": [item["agent_id"] for item in assignments],
                "synchronization": "threaded controller start; actual per-agent offsets are recorded in results",
                "manual_orchestration": False,
            },
            "cadence_contract": {
                "boundary": "controller board-read visibility",
                "observation_window_turns": observation_window_turns,
                "schedule": "first board-read attempt and then every Nth attempt per agent",
                "skipped_slots_are_recorded": True,
            },
            "provenance": {
                "primary_outcome": "seeded token in a source board message, cross-agent board read, then later recipient event",
                "token_overlap_alone_is_not_uptake": True,
                "task_success_is_separate_from_uptake": True,
            },
            "artifact_contract": {
                "agent_timeline_pattern": "agents/{agent_id}/artifacts/timeline.json",
                "agent_probability_pattern": "agents/{agent_id}/artifacts/probability_artifacts.json",
                "probability_schema": "agent-turn-probability-v1 / partial-token-probability-v1",
            },
        }

    @staticmethod
    def _cadence_name(window: int) -> str:
        return {1: "per_turn", 2: "every_2_turns", 4: "every_4_turns"}.get(window, f"window_{window}")

    def run_condition(
        self,
        condition: Condition | str,
        *,
        seed: int,
        triplet_id: str | None = None,
        run_id: str | None = None,
        agent_count: int | None = None,
        capability_profile: str | None = None,
        difficulty: str = "anchor",
        observation_window_turns: int = 1,
        model: str | None = None,
        condition_order: Sequence[Condition] | None = None,
        _ollama_probe: Mapping[str, Any] | None = None,
    ) -> SwarmRun:
        selected_condition = Condition(condition)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise RuntimeConfigError("seed must be an integer")
        if isinstance(observation_window_turns, bool) or not isinstance(observation_window_turns, int) or observation_window_turns < 1:
            raise RuntimeConfigError("observation_window_turns must be a positive integer")
        count = self.protocol.anchor_agent_count if agent_count is None else agent_count
        profile_name = self.protocol.default_capability_profile if capability_profile is None else capability_profile
        get_capability_profile(profile_name)
        instance = task_one_instance(seed, difficulty, count)
        run_config = self._config_for_n(count, model)
        if self.invocation is not None and run_config.model != self.invocation.model:
            raise RuntimeConfigError(
                "a model-scoped invocation cannot contain a different model; create a new invocation"
            )
        selected_ollama_probe = _ollama_probe
        if selected_ollama_probe is None:
            selected_ollama_probe = probe_ollama(run_config)
        triplet = _safe_component(triplet_id or f"task1-seed-{seed}", "triplet_id")
        identifier = _safe_component(run_id or f"{triplet}-{selected_condition.value}", "run_id")
        if self.invocation is None:
            run_root = self.artifact_root / identifier
            if run_root.exists():
                raise RuntimeConfigError(f"experiment run already exists: {run_root}")
            run_root.mkdir(mode=0o700, parents=True)
        else:
            # The invocation UUID is allocated once by the launcher. Seed and
            # condition remain visible below it, while the condition label is
            # retained as the runtime identity used by the board and agents.
            run_root = self.artifact_root / triplet / selected_condition.value
            try:
                run_root.mkdir(mode=0o700, parents=True, exist_ok=False)
            except FileExistsError as exc:
                raise RuntimeConfigError(f"experiment condition already exists: {run_root}") from exc
        (run_root / "artifacts").mkdir(mode=0o700)
        (run_root / "artifacts" / "board_events.jsonl").touch(mode=0o600)
        prompt = run_config.prompt_for(instance.task_id, seed)
        manifest = self._run_manifest(
            run_id=identifier,
            triplet_id=triplet,
            condition=selected_condition,
            seed=seed,
            run_config=run_config,
            instance=instance,
            capability_profile=profile_name,
            observation_window_turns=observation_window_turns,
            ollama_probe=selected_ollama_probe,
        )
        selected_order = tuple(condition_order or (selected_condition,))
        manifest["condition_order"] = [item.value for item in selected_order]
        manifest["execution_order_index"] = selected_order.index(selected_condition) if selected_condition in selected_order else 0
        _write_json(run_root / "manifest.json", manifest)
        board_log = JsonlEventLog(run_root / "artifacts" / "board_events.jsonl")
        board_store: BoardStore | None = None
        board_service: BoardToolService | None = None
        workspaces = []
        identities = []
        services = []
        try:
            for number in range(1, run_config.agent_count + 1):
                identity = AgentIdentity(
                    run_id=identifier,
                    agent_id=f"agent-{number}",
                    condition=selected_condition,
                    task_id=instance.task_id,
                    seed=seed,
                    capability_profile=profile_name,
                )
                workspace = create_isolated_workspace(
                    self.artifact_root if self.invocation is None else run_root,
                    identity,
                    run_root=None if self.invocation is None else run_root,
                )
                bundle = task_one_bundle_for_agent(instance, number)
                materialize_task_one_bundle(workspace.task_dir, bundle.agent_id, instance)
                workspaces.append(workspace)
                identities.append(identity)
            if selected_condition is not Condition.C0:
                board_store = BoardStore.initialize(
                    run_root / "board.sqlite3",
                    agent_workspace_roots=tuple(workspace.root for workspace in workspaces),
                )
                board_service = BoardToolService(board_store)
            for identity, workspace in zip(identities, workspaces):
                catalog = TaskCatalog({
                    instance.task_id: TaskDefinition(
                        instance.task_id,
                        workspace.task_dir,
                        allowed_paths=(Path(task_one_bundle_for_agent(instance, int(identity.agent_id.split("-")[-1])).relative_path).name,),
                        answer_validator=instance.validate_answer,
                    )
                })
                services.append(ConstrainedToolService(
                    TaskToolService(catalog),
                    board_service,
                    artifact_root=run_root,
                    telemetry=board_log.record,
                    board_read_interval=observation_window_turns,
                ))
            budget = SystemBudget(run_config.aggregate_token_budget, run_config.aggregate_tool_call_budget)
            results: list[Mapping[str, Any]] = []
            errors: list[Mapping[str, Any]] = []

            def execute(index: int) -> Mapping[str, Any]:
                result = AgentRun(
                    run_config,
                    identities[index],
                    workspaces[index],
                    budget,
                    services[index],
                ).run(prompt, self.extension)
                return result.to_dict()

            with ThreadPoolExecutor(max_workers=run_config.agent_count, thread_name_prefix="apart-agent") as executor:
                futures = [executor.submit(execute, index) for index in range(run_config.agent_count)]
                for future in as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        errors.append({"type": type(exc).__name__, "message": str(exc)})
            results.sort(key=lambda result: str(result.get("identity", {}).get("agent_id", "")))
            budget_snapshot = budget.snapshot()
            _write_json(run_root / "budget.json", budget_snapshot)
            _write_json(run_root / "results.json", {"schema_version": 1, "results": results, "controller_errors": errors})
            metrics = write_derived_artifacts(run_root, (instance.token,), observation_window_turns=observation_window_turns)
            _write_json(run_root / "manifest.json", {**manifest, "budget_final": budget_snapshot, "result_count": len(results), "controller_errors": errors})
            write_condition_index(run_root)
            return SwarmRun(identifier, triplet, selected_condition, seed, run_root, tuple(results), metrics)
        except Exception as exc:
            controller_failure = {
                "schema_version": 1,
                "run_id": identifier,
                **({"run_uuid": self.invocation.run_uuid, "model": self.invocation.model} if self.invocation is not None else {}),
                "status": "controller_failure",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            _write_json(run_root / "controller_failure.json", controller_failure)
            write_condition_index(run_root, controller_failure=controller_failure)
            raise
        finally:
            if board_store is not None:
                board_store.close()

    def run_triplet(
        self,
        *,
        seed: int,
        triplet_id: str | None = None,
        agent_count: int | None = None,
        capability_profile: str | None = None,
        difficulty: str = "anchor",
        observation_window_turns: int = 1,
        model: str | None = None,
    ) -> tuple[SwarmRun, ...]:
        """Run one matched C0/C1/C2 triplet and attach baseline overhead fields."""

        resolved_agent_count = self.protocol.anchor_agent_count if agent_count is None else agent_count
        triplet = _safe_component(triplet_id or f"task1-seed-{seed}", "triplet_id")
        selected_config = self.config if model is None else self.config.for_model(model)
        ollama_probe_result = probe_ollama(selected_config)
        execution_order = tuple(
            self.protocol.conditions[(seed - 1 + index) % len(self.protocol.conditions)]
            for index in range(len(self.protocol.conditions))
        )
        execution_runs = tuple(
            self.run_condition(
                condition,
                seed=seed,
                triplet_id=triplet,
                agent_count=agent_count,
                capability_profile=capability_profile,
                difficulty=difficulty,
                observation_window_turns=observation_window_turns,
                model=model,
                condition_order=execution_order,
                _ollama_probe=ollama_probe_result,
            )
            for condition in execution_order
        )
        runs = tuple(
            next(run for run in execution_runs if run.condition is condition)
            for condition in self.protocol.conditions
        )
        baseline = runs[0].metrics
        updated_runs: list[SwarmRun] = [runs[0]]
        for run in runs[1:]:
            metrics = write_derived_artifacts(
                run.artifact_root,
                (task_one_instance(seed, difficulty, resolved_agent_count).token,),
                observation_window_turns=observation_window_turns,
                baseline=baseline,
            )
            updated_runs.append(replace(run, metrics=metrics))
        runs = tuple(updated_runs)
        _write_json(self.artifact_root / f"{triplet}.json", {
            "schema_version": 1,
            "run_class": self.run_class,
            **({"run_id": self.invocation.run_id} if self.invocation is not None else {}),
            **({"run_uuid": self.invocation.run_uuid, "model": self.invocation.model} if self.invocation is not None else {}),
            "triplet_id": triplet,
            "matched_seed": seed,
            "conditions": [run.condition.value for run in runs],
            "run_ids": [run.run_id for run in runs],
            "primary_contrast": "C1 versus C2",
            "metrics": {run.condition.value: run.metrics for run in runs},
            "artifacts": {
                "conditions": {
                    run.condition.value: {
                        "run_id": run.run_id,
                        **artifact_links_for_run(run.artifact_root, self.artifact_root),
                    }
                    for run in runs
                },
            },
            "pilot_claim_scope": "descriptive only",
        })
        return runs

    def run_anchor_matrix(self, seeds: Sequence[int] | None = None) -> list[tuple[SwarmRun, ...]]:
        selected = self.protocol.anchor_seeds if seeds is None else tuple(seeds)
        return [
            self.run_triplet(seed=seed, triplet_id=f"s{seed:04d}")
            for seed in selected
        ]

    def run_factor_pilot(
        self,
        factor: str,
        levels: Sequence[Any],
        *,
        seeds: Sequence[int] = (1,),
    ) -> list[tuple[SwarmRun, ...]]:
        """Run one predeclared factor at a time, keeping it fixed in each triplet."""

        if factor not in self.protocol.factor_levels:
            raise RuntimeConfigError(f"factor is not predeclared: {factor}")
        output: list[tuple[SwarmRun, ...]] = []
        for level in levels:
            for seed in seeds:
                kwargs: dict[str, Any] = {}
                if factor == "agent_count":
                    kwargs["agent_count"] = int(level)
                elif factor == "capability_profile":
                    kwargs["capability_profile"] = str(level)
                elif factor == "difficulty":
                    kwargs["difficulty"] = str(level)
                elif factor == "transformation_cadence":
                    windows = self.protocol.transformation_windows or {}
                    if str(level) not in windows:
                        raise RuntimeConfigError(f"unknown transformation cadence: {level}")
                    kwargs["observation_window_turns"] = windows[str(level)]
                elif factor == "model":
                    if str(level) == "configured":
                        kwargs["model"] = self.config.model
                    else:
                        if self.run_class == "experimental" and str(level) not in self.verified_models:
                            raise RuntimeConfigError(
                                f"model tier {level!r} has not passed live access validation"
                            )
                        kwargs["model"] = str(level)
                selected_controller = self
                selected_model = kwargs.get("model")
                if (
                    factor == "model"
                    and self.invocation is not None
                    and isinstance(selected_model, str)
                    and selected_model != self.config.model
                ):
                    try:
                        invocation = create_run_directory(
                            self.output_base,
                            selected_model,
                            run_id=f"factor-model-{_safe_level(selected_model)}-seed-{seed}",
                        )
                    except RunPathError as exc:
                        raise RuntimeConfigError(str(exc)) from exc
                    invocation.write_metadata({
                        "run_class": self.run_class,
                        "factor": factor,
                        "factor_level": str(level),
                    })
                    selected_controller = ExperimentController(
                        self.config.for_model(selected_model),
                        invocation.path,
                        invocation=invocation,
                        extension=self.extension,
                        protocol=self.protocol,
                        run_class=self.run_class,
                        verified_models=self.verified_models,
                    )
                    kwargs.pop("model", None)
                output.append(selected_controller.run_triplet(
                    seed=seed,
                    triplet_id=f"factor-{_safe_level(factor)}-{_safe_level(level)}-seed-{seed}",
                    **kwargs,
                ))
        return output


__all__ = [
    "ExperimentController",
    "ExperimentProtocol",
    "FACTOR_LEVELS",
    "PROTOCOL_VERSION",
    "SwarmRun",
]
