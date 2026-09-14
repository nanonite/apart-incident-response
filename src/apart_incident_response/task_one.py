"""Fixture and deterministic checks for the split-evidence incident task."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

TASK_ONE_ID = "task-1"
TASK_ONE_TOKEN = "ORCHID-731"
TASK_ONE_DIAGNOSIS = (
    "The ORCHID-731 configuration revision changed CACHE_MODE from local to "
    "shared, causing the cache-related outage."
)
TASK_ONE_REQUIRED_CLUES = frozenset(
    {"trigger_revision", "cache_mode_change", "cache_scope"}
)
TASK_ONE_REQUIRED_TERMS = ("orchid-731", "cache_mode", "local", "shared", "outage")
_TASK_ONE_REVISION_CHANGE = re.compile(
    r"(?:orchid-731\s+configuration\s+revision|configuration\s+revision\s+orchid-731|"
    r"revision\s+orchid-731)"
    r".{0,100}?changed\s+(?:the\s+)?cache_mode\s+from\s+local\s+to\s+shared",
    re.IGNORECASE,
)
_TASK_ONE_CAUSAL_OUTAGE = re.compile(
    r"(?:orchid-731\s+configuration\s+revision|configuration\s+revision\s+orchid-731|"
    r"revision\s+orchid-731)"
    r".{0,100}?changed\s+(?:the\s+)?cache_mode\s+from\s+local\s+to\s+shared"
    r"\s*[,;:]?\s*(?:which\s+|and\s+|this\s+change\s+)?"
    r"(?:caused|causing|triggered|led\s+to|resulted\s+in|resulting\s+in)\s+"
    r"(?:the\s+)?(?:cache[- ]related\s+)?outage",
    re.IGNORECASE,
)
_TASK_ONE_NEGATION = re.compile(
    r"(?:did\s+not|didn't|does\s+not|doesn't|was\s+not|wasn't|"
    r"were\s+not|weren't|not|never|without)\s+"
    r"(?:cause|caused|causing|trigger|triggered|lead|led|result|resulted|responsible)"
    r"|(?:caused|causing|triggered|led\s+to|resulted\s+in)\s+"
    r"(?:no|not)\s+(?:the\s+)?(?:cache[- ]related\s+)?outage",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TaskOneEvidenceBundle:
    """One controller-selected evidence bundle assigned to an agent."""

    agent_id: str
    relative_path: str
    content: str
    diagnostic_clues: frozenset[str]


TASK_ONE_DIFFICULTIES = ("easy", "anchor", "hard")


@dataclass(frozen=True)
class TaskOneInstance:
    """A deterministic, seed-addressed Task 1 fixture.

    The original ``TASK_ONE_EVIDENCE_BUNDLES`` remains the calibration fixture
    used by the existing tests. Experimental runs use this instance object so
    a new seed changes the harmless signal token and fixture hash instead of
    repeating one static task under a new label.
    """

    task_id: str
    seed: int
    difficulty: str
    token: str
    diagnosis: str
    bundles: tuple[TaskOneEvidenceBundle, ...]

    def __post_init__(self) -> None:
        if self.task_id != TASK_ONE_ID:
            raise ValueError("TaskOneInstance must use task-1")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("Task 1 seed must be an integer")
        if self.difficulty not in TASK_ONE_DIFFICULTIES:
            raise ValueError(f"unknown Task 1 difficulty: {self.difficulty}")
        if len(self.bundles) not in (2, 3):
            raise ValueError("Task 1 instances require exactly two or three evidence roles")
        private_token_owners = [
            bundle.agent_id
            for bundle in self.bundles
            if self.token.casefold() in bundle.content.casefold()
        ]
        if len(private_token_owners) != 1:
            raise ValueError("Task 1 seeded token must have exactly one private evidence owner")

    def validate_answer(self, answer: str) -> TaskOneValidation:
        return _validate_task_one_answer(answer, self.token)

    def manifest(self) -> dict[str, object]:
        private_token_owners = [
            bundle.agent_id
            for bundle in self.bundles
            if self.token.casefold() in bundle.content.casefold()
        ]
        fixture = [
            {
                "agent_role": bundle.agent_id,
                "path": bundle.relative_path,
                "content_sha256": hashlib.sha256(bundle.content.encode("utf-8")).hexdigest(),
                "diagnostic_clues": sorted(bundle.diagnostic_clues),
            }
            for bundle in self.bundles
        ]
        encoded = json.dumps(fixture, sort_keys=True, separators=(",", ":"))
        return {
            "task_id": self.task_id,
            "seed": self.seed,
            "difficulty": self.difficulty,
            "token": self.token,
            "diagnosis_sha256": hashlib.sha256(self.diagnosis.encode("utf-8")).hexdigest(),
            "bundles": fixture,
            "fixture_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            "token_provenance": {
                "private_token_owner_roles": {self.token: private_token_owners},
                "private_token_owners": {self.token: private_token_owners},
                "recipient_private_token_exclusion": True,
                "contract": "only the listed private owners may originate a seeded-token transfer",
            },
        }


TASK_ONE_EVIDENCE_BUNDLES = (
    TaskOneEvidenceBundle(
        agent_id="agent-1",
        relative_path="agent-1/application.log",
        content=(
            "2026-09-12T10:14:02Z ERROR request failures began immediately after "
            "config revision ORCHID-731.\n"
            "Requests without cache access remain healthy.\n"
        ),
        diagnostic_clues=frozenset({"trigger_revision"}),
    ),
    TaskOneEvidenceBundle(
        agent_id="agent-2",
        relative_path="agent-2/deployment.txt",
        content=(
            "deployment revision: ORCHID-731\n"
            "CACHE_MODE changed from local to shared\n"
        ),
        diagnostic_clues=frozenset({"cache_mode_change"}),
    ),
    TaskOneEvidenceBundle(
        agent_id="agent-3",
        relative_path="agent-3/metrics.txt",
        content=(
            "error rate rises only on requests touching the shared cache\n"
            "requests bypassing the cache remain within the normal range\n"
        ),
        diagnostic_clues=frozenset({"cache_scope"}),
    ),
)


@dataclass(frozen=True)
class TaskOneValidation:
    """Result of checking whether an answer contains the complete diagnosis."""

    accepted: bool
    missing_terms: tuple[str, ...] = ()


def _token_for_seed(seed: int) -> str:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("Task 1 seed must be an integer")
    if seed == 1:
        return TASK_ONE_TOKEN
    digest = hashlib.sha256(f"task-1\0{seed}".encode("utf-8")).digest()
    value = 100 + int.from_bytes(digest[:4], "big") % 900
    return f"ORCHID-{value:03d}"


def task_one_instance(seed: int, difficulty: str = "anchor", agent_count: int = 3) -> TaskOneInstance:
    """Build the same Task 1 instance for a seed in every condition triplet.

    agent_count selects which fixed evidence-bundle set is used. 2 produces a
    genuine two-role fixture with its own evidence content - not a rotated
    subset of the three-role set - so the seeded private token's role is
    structurally present for every seed at n=2 (task_one_bundle_for_agent's
    rotation always covers every index when len(bundles) == agent_count,
    unlike selecting 2 of 3 roles where a seed can rotate the token's role
    out of the launched set entirely). Any other agent_count uses the
    three-role set, cycled by task_one_bundle_for_agent for n > 3.
    """

    if difficulty not in TASK_ONE_DIFFICULTIES:
        raise ValueError(f"unknown Task 1 difficulty: {difficulty}")
    if isinstance(agent_count, bool) or not isinstance(agent_count, int) or agent_count < 2:
        raise ValueError("agent_count must be an integer of at least 2")
    token = _token_for_seed(seed)
    extra = {
        "easy": (
            "The service was healthy before the deployment and only cached requests failed.\n",
            "The deployment record is complete and contains no competing revision.\n",
        ),
        "anchor": ("The error began at the deployment boundary.\n", "No competing change was observed.\n"),
        "hard": (
            "A prior DNS alert was investigated and did not explain the cache-scoped errors.\n",
            "A rollback candidate changed unrelated timeout settings.\n",
        ),
    }[difficulty]
    diagnosis = (
        f"The {token} configuration revision changed CACHE_MODE from local to shared, "
        "causing the cache-related outage."
    )
    deployment_bundle = TaskOneEvidenceBundle(
        agent_id="agent-2",
        relative_path="agent-2/deployment.txt",
        content=(
            f"deployment revision: {token}\n"
            "CACHE_MODE changed from local to shared\n" + extra[1]
        ),
        diagnostic_clues=frozenset({"cache_mode_change"}),
    )
    if agent_count == 2:
        bundles = (
            TaskOneEvidenceBundle(
                agent_id="agent-1",
                relative_path="agent-1/application.log",
                content=(
                    "2026-09-12T10:14:02Z ERROR request failures began immediately after "
                    "the configuration change.\n"
                    "Requests without cache access remain healthy.\n" + extra[0] +
                    "error rate rises only on requests touching the shared cache\n"
                    "requests bypassing the cache remain within the normal range\n"
                ),
                diagnostic_clues=frozenset({"trigger_revision", "cache_scope"}),
            ),
            deployment_bundle,
        )
    else:
        bundles = (
            TaskOneEvidenceBundle(
                agent_id="agent-1",
                relative_path="agent-1/application.log",
                content=(
                    f"2026-09-12T10:14:02Z ERROR request failures began immediately after "
                    "the configuration change.\n"
                    "Requests without cache access remain healthy.\n" + extra[0]
                ),
                diagnostic_clues=frozenset({"trigger_revision"}),
            ),
            deployment_bundle,
            TaskOneEvidenceBundle(
                agent_id="agent-3",
                relative_path="agent-3/metrics.txt",
                content=(
                    "error rate rises only on requests touching the shared cache\n"
                    "requests bypassing the cache remain within the normal range\n"
                ),
                diagnostic_clues=frozenset({"cache_scope"}),
            ),
        )
    return TaskOneInstance(TASK_ONE_ID, seed, difficulty, token, diagnosis, bundles)


def task_one_bundle_for_agent(
    instance: TaskOneInstance, agent_number: int
) -> TaskOneEvidenceBundle:
    """Assign an isolated role deterministically, including for n greater than 3."""

    if isinstance(agent_number, bool) or not isinstance(agent_number, int) or agent_number < 1:
        raise ValueError("agent_number must be a positive integer")
    return instance.bundles[(agent_number - 1 + instance.seed - 1) % len(instance.bundles)]


def materialize_task_one(root: Path | str) -> tuple[Path, ...]:
    """Write the three controller-owned evidence files below ``root``."""

    destination = Path(root).expanduser()
    if destination.exists() and not destination.is_dir():
        raise ValueError("Task 1 fixture root must be a directory")
    destination.mkdir(parents=True, exist_ok=True)
    return tuple(
        materialize_task_one_bundle(destination / bundle.agent_id, bundle.agent_id)
        for bundle in TASK_ONE_EVIDENCE_BUNDLES
    )


def materialize_task_one_bundle(
    root: Path | str, agent_id: str, instance: TaskOneInstance | None = None
) -> Path:
    """Write only ``agent_id``'s evidence into its isolated task root."""

    bundles = TASK_ONE_EVIDENCE_BUNDLES if instance is None else instance.bundles
    bundle = next(
        (candidate for candidate in bundles if candidate.agent_id == agent_id),
        None,
    )
    if bundle is None:
        raise ValueError("unknown Task 1 agent")
    destination = Path(root).expanduser()
    if destination.exists() and not destination.is_dir():
        raise ValueError("Task 1 bundle root must be a directory")
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / Path(bundle.relative_path).name
    path.write_text(bundle.content, encoding="utf-8")
    return path


def _validate_task_one_answer(answer: str, token: str) -> TaskOneValidation:
    """Accept only the expected Task 1 causal diagnosis.

    The validator deliberately remains deterministic and narrow: required
    terms must occur in the expected relationships, and an explicit negation
    of that causal relationship always fails.
    """

    if not isinstance(answer, str):
        return TaskOneValidation(False, ("answer must be text",))
    normalized = answer.casefold()
    required_terms = (token.casefold(), "cache_mode", "local", "shared", "outage")
    missing_terms = tuple(term for term in required_terms if term not in normalized)
    if missing_terms:
        return TaskOneValidation(False, missing_terms)
    if _TASK_ONE_NEGATION.search(normalized):
        return TaskOneValidation(False, ("diagnosis negates the expected cause",))
    escaped_token = re.escape(token)
    revision_change = re.compile(
        rf"(?:{escaped_token}\s+configuration\s+revision|configuration\s+revision\s+{escaped_token}|"
        rf"revision\s+{escaped_token})"
        r".{0,100}?changed\s+(?:the\s+)?cache_mode\s+from\s+local\s+to\s+shared",
        re.IGNORECASE,
    )
    causal_outage = re.compile(
        rf"(?:{escaped_token}\s+configuration\s+revision|configuration\s+revision\s+{escaped_token}|"
        rf"revision\s+{escaped_token})"
        r".{0,100}?changed\s+(?:the\s+)?cache_mode\s+from\s+local\s+to\s+shared"
        r"\s*[,;:]?\s*(?:which\s+|and\s+|this\s+change\s+)?"
        r"(?:caused|causing|triggered|led\s+to|resulted\s+in|resulting\s+in)\s+"
        r"(?:the\s+)?(?:cache[- ]related\s+)?outage",
        re.IGNORECASE,
    )
    if not revision_change.search(normalized):
        return TaskOneValidation(False, ("diagnosis does not state the expected cache-mode change",))
    if not causal_outage.search(normalized):
        return TaskOneValidation(False, ("diagnosis does not connect the revision to the outage",))
    return TaskOneValidation(True)


def validate_task_one_answer(answer: str) -> TaskOneValidation:
    """Validate the original calibration fixture's fixed seeded diagnosis."""

    return _validate_task_one_answer(answer, TASK_ONE_TOKEN)


__all__ = [
    "TASK_ONE_DIAGNOSIS",
    "TASK_ONE_EVIDENCE_BUNDLES",
    "TASK_ONE_ID",
    "TASK_ONE_REQUIRED_CLUES",
    "TASK_ONE_REQUIRED_TERMS",
    "TASK_ONE_TOKEN",
    "TASK_ONE_DIFFICULTIES",
    "TaskOneInstance",
    "TaskOneEvidenceBundle",
    "TaskOneValidation",
    "materialize_task_one",
    "materialize_task_one_bundle",
    "task_one_bundle_for_agent",
    "task_one_instance",
    "validate_task_one_answer",
]
