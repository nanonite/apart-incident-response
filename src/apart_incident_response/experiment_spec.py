"""Declarative experiment definitions: one shared task, per-agent context.

An experiment is a directory. Its specification names the single task statement
that every agent receives verbatim, and the private context injected into each
agent's isolated task directory. The structure makes the shared part shared by
construction: there is one statement field, so no agent can be handed a
different task, and ``statement_for`` returns the same text for every agent.

The validated invariants are the ones that keep a run interpretable:

* No agent's private context alone satisfies the task's acceptance terms, so
  task success cannot be reached without the other agents' context.
* Each agent's canary appears in that agent's context and in no other, so a
  canary observed elsewhere is evidence of transfer rather than coincidence.
* Neither the statement nor the injected context names the experimental
  condition or the cross-agent channel, so the agent cannot infer its arm.

Nothing here talks to a model, reads the board, or knows about conditions
beyond their names: it only describes an experiment and writes files.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping, Sequence

from .capabilities import get_capability_profile
from .runtime import Condition

DIR_MODE = 0o700
FILE_MODE = 0o600
SPEC_FILENAME = "experiment.json"

_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_STATEMENT_LEAKS = (
    r"\bboards?\b",
    r"\bblackboards?\b",
    r"\bpeers?\b",
    r"\b(?:other|another|second|third)\s+agents?\b",
    r"\bteammates?\b",
    r"collaborat\w*",
    r"coordinat\w*",
    r"\bswarms?\b",
    r"\bconditions?\b",
    r"\bc[012]\b",
)
_CONTEXT_LEAKS = (
    r"\bboards?\b",
    r"\bblackboards?\b",
    r"\bc[012]\b",
)


class ExperimentSpecError(ValueError):
    """Raised when an experiment definition violates a design invariant."""


def _escapes_task_dir(path: str) -> bool:
    """Reject anything that could write outside the agent's own task root."""

    return path.startswith("/") or "\\" in path or ".." in PurePosixPath(path).parts


def _leaks(text: str, patterns: Sequence[str]) -> tuple[str, ...]:
    lowered = text.casefold()
    return tuple(
        pattern for pattern in patterns if re.search(pattern, lowered) is not None
    )


@dataclass(frozen=True)
class ContextFile:
    """One file injected into a single agent's isolated task directory."""

    path: str
    content: str

    def violations(self) -> tuple[str, ...]:
        found: list[str] = []
        if not isinstance(self.path, str) or not self.path:
            found.append("context path must be a non-empty string")
            return tuple(found)
        if _escapes_task_dir(self.path):
            found.append(f"context path must be relative and contained: {self.path!r}")
        if not isinstance(self.content, str) or not self.content.strip():
            found.append(f"context file has no content: {self.path!r}")
        return tuple(found)

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "content": self.content}


@dataclass(frozen=True)
class TaskSpec:
    """The task every agent in the experiment receives, identically."""

    task_id: str
    statement: str
    acceptance_terms: tuple[str, ...] = ()

    def violations(self) -> tuple[str, ...]:
        found: list[str] = []
        if not isinstance(self.task_id, str) or not _IDENTIFIER.match(self.task_id):
            found.append(f"task_id must be a lowercase identifier: {self.task_id!r}")
        if not isinstance(self.statement, str) or not self.statement.strip():
            found.append("task statement must be non-empty")
            return tuple(found)
        leaked = _leaks(self.statement, _STATEMENT_LEAKS)
        if leaked:
            found.append(f"task statement names the arm or the channel: {leaked}")
        for term in self.acceptance_terms:
            if not isinstance(term, str) or not term.strip():
                found.append("acceptance terms must be non-empty strings")
                break
        return tuple(found)

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "statement": self.statement,
            "acceptance_terms": list(self.acceptance_terms),
        }


@dataclass(frozen=True)
class AgentSpec:
    """One agent: a capability profile plus the context injected into it."""

    agent_id: str
    capability_profile: str
    context: tuple[ContextFile, ...] = ()
    canary: str | None = None

    @property
    def context_text(self) -> str:
        return "\n".join(item.content for item in self.context)

    def violations(self) -> tuple[str, ...]:
        found: list[str] = []
        if not isinstance(self.agent_id, str) or not _IDENTIFIER.match(self.agent_id):
            found.append(f"agent_id must be a lowercase identifier: {self.agent_id!r}")
        try:
            get_capability_profile(self.capability_profile)
        except ValueError as exc:
            found.append(str(exc))
        seen: set[str] = set()
        for item in self.context:
            found.extend(item.violations())
            if item.path in seen:
                found.append(f"duplicate context path for {self.agent_id}: {item.path!r}")
            seen.add(item.path)
        leaked = _leaks(self.context_text, _CONTEXT_LEAKS)
        if leaked:
            found.append(f"injected context names the arm or the channel: {leaked}")
        if self.canary is not None:
            if not isinstance(self.canary, str) or not self.canary.strip():
                found.append(f"canary must be a non-empty string for {self.agent_id}")
            elif self.canary not in self.context_text:
                found.append(
                    f"canary {self.canary!r} is absent from its own agent's context"
                )
        return tuple(found)

    def to_dict(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "capability_profile": self.capability_profile,
            "context": [item.to_dict() for item in self.context],
            "canary": self.canary,
        }


@dataclass(frozen=True)
class ExperimentSpec:
    """A whole experiment: one shared task, n agents, and their own folder."""

    experiment_id: str
    task: TaskSpec
    agents: tuple[AgentSpec, ...]
    conditions: tuple[Condition, ...] = (Condition.C0, Condition.C1, Condition.C2)
    seeds: tuple[int, ...] = (1,)

    def __post_init__(self) -> None:
        # ``Condition`` is a string enum, so a plain "C0" would compare equal to
        # the member and pass validation, then fail later where the member API
        # is used. Coerce once here, so the rest of the module may assume
        # members, and reject an unknown name as a specification error.
        try:
            object.__setattr__(
                self,
                "conditions",
                tuple(Condition(condition) for condition in self.conditions),
            )
        except (TypeError, ValueError) as exc:
            raise ExperimentSpecError(f"unknown condition: {exc}") from exc
        violations = self._violations()
        if violations:
            joined = "; ".join(violations)
            raise ExperimentSpecError(f"invalid experiment specification: {joined}")

    def _violations(self) -> tuple[str, ...]:
        found: list[str] = []
        if not isinstance(self.experiment_id, str) or not _IDENTIFIER.match(
            self.experiment_id
        ):
            found.append(
                f"experiment_id must be a lowercase identifier: {self.experiment_id!r}"
            )
        found.extend(self.task.violations())
        if len(self.agents) < 2:
            found.append("an experiment needs at least two agents")
        identifiers = [agent.agent_id for agent in self.agents]
        if len(set(identifiers)) != len(identifiers):
            found.append("agent_id values must be unique")
        for agent in self.agents:
            found.extend(agent.violations())
        found.extend(self._insufficiency_violations())
        found.extend(self._canary_violations())
        if not self.conditions:
            found.append("an experiment needs at least one condition")
        ordered = tuple(
            condition
            for condition in (Condition.C0, Condition.C1, Condition.C2)
            if condition in self.conditions
        )
        if tuple(self.conditions) != ordered:
            found.append("conditions must be unique and ordered C0, C1, C2")
        if not self.seeds:
            found.append("an experiment needs at least one seed")
        for seed in self.seeds:
            if isinstance(seed, bool) or not isinstance(seed, int) or seed < 1:
                found.append(f"seeds must be positive integers: {seed!r}")
                break
        if len(set(self.seeds)) != len(self.seeds):
            found.append("seeds must be unique")
        return tuple(found)

    def _insufficiency_violations(self) -> tuple[str, ...]:
        terms = tuple(term.casefold() for term in self.task.acceptance_terms)
        if not terms:
            return ()
        found: list[str] = []
        for agent in self.agents:
            lowered = agent.context_text.casefold()
            if all(term in lowered for term in terms):
                found.append(
                    f"{agent.agent_id} can satisfy every acceptance term from its own "
                    "context, so task success would not require the other agents"
                )
        return tuple(found)

    def _canary_violations(self) -> tuple[str, ...]:
        found: list[str] = []
        canaries = [agent.canary for agent in self.agents if agent.canary]
        if len(set(canaries)) != len(canaries):
            found.append("canaries must be unique across agents")
        for agent in self.agents:
            if not agent.canary:
                continue
            for other in self.agents:
                if other.agent_id == agent.agent_id:
                    continue
                if agent.canary in other.context_text:
                    found.append(
                        f"canary {agent.canary!r} also appears in {other.agent_id}'s "
                        "context, so its transfer would be unattributable"
                    )
        return tuple(found)

    def agent(self, agent_id: str) -> AgentSpec:
        """Resolve one agent and fail closed for unknown identifiers."""

        for agent in self.agents:
            if agent.agent_id == agent_id:
                return agent
        raise ExperimentSpecError(f"unknown agent for this experiment: {agent_id!r}")

    def statement_for(self, agent_id: str) -> str:
        """Return the shared task statement; identical for every agent."""

        self.agent(agent_id)
        return self.task.statement

    def canaries(self) -> tuple[str, ...]:
        """Canaries in agent order, for provenance-backed uptake detection."""

        return tuple(agent.canary for agent in self.agents if agent.canary)

    def to_dict(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "task": self.task.to_dict(),
            "agents": [agent.to_dict() for agent in self.agents],
            "conditions": [condition.value for condition in self.conditions],
            "seeds": list(self.seeds),
        }

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ExperimentSpec":
        """Build a specification from parsed JSON, failing closed on shape."""

        if not isinstance(raw, Mapping):
            raise ExperimentSpecError("experiment specification must be a mapping")
        task_raw = raw.get("task")
        if not isinstance(task_raw, Mapping):
            raise ExperimentSpecError("experiment specification requires a task")
        agents_raw = raw.get("agents")
        if not isinstance(agents_raw, Sequence) or isinstance(agents_raw, (str, bytes)):
            raise ExperimentSpecError("experiment specification requires an agent list")
        task = TaskSpec(
            task_id=task_raw.get("task_id", ""),
            statement=task_raw.get("statement", ""),
            acceptance_terms=tuple(task_raw.get("acceptance_terms", ()) or ()),
        )
        agents: list[AgentSpec] = []
        for agent_raw in agents_raw:
            if not isinstance(agent_raw, Mapping):
                raise ExperimentSpecError("each agent must be a mapping")
            context_raw = agent_raw.get("context", ()) or ()
            if isinstance(context_raw, (str, bytes)) or not isinstance(
                context_raw, Sequence
            ):
                raise ExperimentSpecError("agent context must be a list of files")
            agents.append(
                AgentSpec(
                    agent_id=agent_raw.get("agent_id", ""),
                    capability_profile=agent_raw.get("capability_profile", ""),
                    context=tuple(
                        ContextFile(
                            path=item.get("path", ""), content=item.get("content", "")
                        )
                        for item in context_raw
                        if isinstance(item, Mapping)
                    ),
                    canary=agent_raw.get("canary"),
                )
            )
        conditions_raw = raw.get("conditions", ["C0", "C1", "C2"])
        try:
            conditions = tuple(Condition(value) for value in conditions_raw)
        except ValueError as exc:
            raise ExperimentSpecError(f"unknown condition: {exc}") from exc
        return cls(
            experiment_id=raw.get("experiment_id", ""),
            task=task,
            agents=tuple(agents),
            conditions=conditions,
            seeds=tuple(raw.get("seeds", (1,)) or (1,)),
        )


def experiment_root(root: Path | str, experiment_id: str) -> Path:
    """Return the directory that owns one experiment's definition and runs."""

    return Path(root).expanduser() / experiment_id


def write_experiment(spec: ExperimentSpec, root: Path | str) -> Path:
    """Create the experiment's own folder, idempotently for the same digest."""

    destination = experiment_root(root, spec.experiment_id)
    spec_path = destination / SPEC_FILENAME
    if spec_path.exists():
        existing = load_experiment(destination)
        if existing.sha256 != spec.sha256:
            raise ExperimentSpecError(
                f"{spec_path} already holds a different experiment definition"
            )
        return destination
    destination.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    (destination / "runs").mkdir(mode=DIR_MODE, exist_ok=True)
    agents_dir = destination / "agents"
    agents_dir.mkdir(mode=DIR_MODE, exist_ok=True)
    for agent in spec.agents:
        context_dir = agents_dir / agent.agent_id / "context"
        context_dir.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
        for item in agent.context:
            _write_text(context_dir / item.path, item.content)
    _write_text(spec_path, spec.canonical_json() + "\n")
    _write_text(destination / "digest.txt", spec.sha256 + "\n")
    return destination


def load_experiment(path: Path | str) -> ExperimentSpec:
    """Load a specification from an experiment directory or its JSON file."""

    candidate = Path(path).expanduser()
    if candidate.is_dir():
        candidate = candidate / SPEC_FILENAME
    if not candidate.is_file():
        raise ExperimentSpecError(f"no experiment specification at {candidate}")
    return ExperimentSpec.from_mapping(json.loads(candidate.read_text(encoding="utf-8")))


def materialize_agent_context(
    spec: ExperimentSpec, task_dir: Path | str, agent_id: str
) -> tuple[Path, ...]:
    """Write only ``agent_id``'s injected context into its isolated task root."""

    agent = spec.agent(agent_id)
    destination = Path(task_dir).expanduser()
    destination.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    written: list[Path] = []
    for item in agent.context:
        target = destination / item.path
        _write_text(target, item.content)
        written.append(target)
    return tuple(written)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(FILE_MODE)


__all__ = [
    "AgentSpec",
    "ContextFile",
    "ExperimentSpec",
    "ExperimentSpecError",
    "SPEC_FILENAME",
    "TaskSpec",
    "experiment_root",
    "load_experiment",
    "materialize_agent_context",
    "write_experiment",
]
