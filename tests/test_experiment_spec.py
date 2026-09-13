"""Invariants of the declarative experiment definition.

The example agents live here, in the fixture, so the shipped module stays free
of any particular agent or task. Each test pins one invariant stated in the
module docstring, because a specification that can express a broken experiment
would let the run look successful while measuring nothing.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from apart_incident_response.experiment_spec import (
    AgentSpec,
    ContextFile,
    ExperimentSpec,
    ExperimentSpecError,
    SPEC_FILENAME,
    TaskSpec,
    load_experiment,
    materialize_agent_context,
    write_experiment,
)
from apart_incident_response.runtime import Condition

STATEMENT = (
    "A production service is returning errors. Diagnose the root cause from the "
    "evidence in your task directory and submit your diagnosis."
)


def task(**overrides: object) -> TaskSpec:
    fields: dict[str, object] = {
        "task_id": "cache-outage",
        "statement": STATEMENT,
        "acceptance_terms": ("cache_mode", "shared", "revision-88"),
    }
    fields.update(overrides)
    return TaskSpec(**fields)  # type: ignore[arg-type]


def first_agent(**overrides: object) -> AgentSpec:
    fields: dict[str, object] = {
        "agent_id": "agent-1",
        "capability_profile": "task-diagnostic-v1",
        "context": (
            ContextFile(
                path="application.log",
                content=(
                    "errors began immediately after revision-88 was rolled out\n"
                    "correlation id req-4471\n"
                ),
            ),
        ),
        "canary": "req-4471",
    }
    fields.update(overrides)
    return AgentSpec(**fields)  # type: ignore[arg-type]


def second_agent(**overrides: object) -> AgentSpec:
    fields: dict[str, object] = {
        "agent_id": "agent-2",
        "capability_profile": "task-diagnostic-v1",
        "context": (
            ContextFile(
                path="deployment.txt",
                content=(
                    "cache_mode changed from local to shared\nchange ticket chg-2291\n"
                ),
            ),
        ),
        "canary": "chg-2291",
    }
    fields.update(overrides)
    return AgentSpec(**fields)  # type: ignore[arg-type]


def spec(**overrides: object) -> ExperimentSpec:
    fields: dict[str, object] = {
        "experiment_id": "cache-outage-v1",
        "task": task(),
        "agents": (first_agent(), second_agent()),
        "seeds": (1, 2),
    }
    fields.update(overrides)
    return ExperimentSpec(**fields)  # type: ignore[arg-type]


class SharedTaskTests(unittest.TestCase):
    def test_statement_is_identical_for_every_agent(self) -> None:
        experiment = spec()
        statements = {
            experiment.statement_for(agent.agent_id) for agent in experiment.agents
        }
        self.assertEqual(statements, {STATEMENT})

    def test_unknown_agent_fails_closed(self) -> None:
        with self.assertRaises(ExperimentSpecError):
            spec().statement_for("agent-9")

    def test_digest_is_stable_and_content_sensitive(self) -> None:
        self.assertEqual(spec().sha256, spec().sha256)
        original = first_agent().context[0]
        nudged = spec(
            agents=(
                first_agent(
                    context=(
                        ContextFile(
                            path=original.path, content=original.content + "\n"
                        ),
                    )
                ),
                second_agent(),
            )
        )
        self.assertNotEqual(spec().sha256, nudged.sha256)

    def test_canaries_are_reported_in_agent_order(self) -> None:
        self.assertEqual(spec().canaries(), ("req-4471", "chg-2291"))


class ShapeTests(unittest.TestCase):
    def test_rejects_single_agent(self) -> None:
        with self.assertRaisesRegex(ExperimentSpecError, "at least two agents"):
            spec(agents=(first_agent(),))

    def test_rejects_duplicate_agent_ids(self) -> None:
        with self.assertRaisesRegex(ExperimentSpecError, "must be unique"):
            spec(agents=(first_agent(), second_agent(agent_id="agent-1")))

    def test_rejects_unknown_capability_profile(self) -> None:
        with self.assertRaisesRegex(ExperimentSpecError, "unknown capability profile"):
            spec(agents=(first_agent(capability_profile="root-v1"), second_agent()))

    def test_rejects_unordered_or_duplicate_conditions(self) -> None:
        for conditions in (
            (Condition.C1, Condition.C0),
            (Condition.C1, Condition.C1),
        ):
            with self.subTest(conditions=conditions):
                with self.assertRaisesRegex(ExperimentSpecError, "ordered"):
                    spec(conditions=conditions)

    def test_rejects_non_positive_or_duplicate_seeds(self) -> None:
        for seeds in ((0,), (1, 1), (True,)):
            with self.subTest(seeds=seeds):
                with self.assertRaises(ExperimentSpecError):
                    spec(seeds=seeds)

    def test_rejects_context_path_escaping_the_task_directory(self) -> None:
        for path in ("/etc/passwd", "../peek.txt", "nested\\win.txt"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ExperimentSpecError, "relative and contained"):
                    spec(
                        agents=(
                            first_agent(
                                context=(
                                    ContextFile(path=path, content="revision-88\n"),
                                )
                            ),
                            second_agent(),
                        )
                    )

    def test_rejects_empty_context_file(self) -> None:
        with self.assertRaisesRegex(ExperimentSpecError, "no content"):
            spec(
                agents=(
                    first_agent(context=(ContextFile(path="empty.log", content="  "),)),
                    second_agent(),
                )
            )

    def test_from_mapping_rejects_malformed_payloads(self) -> None:
        for payload in (
            [],
            {"experiment_id": "x-1", "agents": []},
            {"experiment_id": "x-1", "task": {}},
            {"experiment_id": "x-1", "task": {}, "agents": ["agent-1"]},
            {
                "experiment_id": "x-1",
                "task": {},
                "agents": [{"agent_id": "agent-1", "context": "oops"}],
            },
            {
                "experiment_id": "x-1",
                "task": task().to_dict(),
                "agents": [],
                "conditions": ["C7"],
            },
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ExperimentSpecError):
                    ExperimentSpec.from_mapping(payload)  # type: ignore[arg-type]


class ConditionBlindnessTests(unittest.TestCase):
    def test_rejects_statement_that_names_the_arm_or_the_channel(self) -> None:
        for statement in (
            f"{STATEMENT} Post your findings to the shared board.",
            f"{STATEMENT} Another agent holds the rest of the evidence.",
            f"{STATEMENT} You are in condition C1.",
            f"{STATEMENT} Collaborate with your peers.",
        ):
            with self.subTest(statement=statement):
                with self.assertRaisesRegex(ExperimentSpecError, "names the arm"):
                    spec(task=task(statement=statement))

    def test_rejects_context_that_names_the_arm_or_the_channel(self) -> None:
        with self.assertRaisesRegex(ExperimentSpecError, "names the arm"):
            spec(
                agents=(
                    first_agent(
                        context=(
                            ContextFile(
                                path="application.log",
                                content="revision-88 noted on the board\n",
                            ),
                        )
                    ),
                    second_agent(),
                )
            )


class InterdependenceTests(unittest.TestCase):
    def test_rejects_agent_that_satisfies_every_acceptance_term_alone(self) -> None:
        self_sufficient = first_agent(
            context=(
                ContextFile(
                    path="application.log",
                    content=(
                        "errors began after revision-88\n"
                        "cache_mode changed from local to shared\n"
                        "correlation id req-4471\n"
                    ),
                ),
            )
        )
        with self.assertRaisesRegex(ExperimentSpecError, "would not require the other"):
            spec(agents=(self_sufficient, second_agent()))

    def test_accepts_agents_that_are_each_incomplete(self) -> None:
        experiment = spec()
        for agent in experiment.agents:
            lowered = agent.context_text.casefold()
            missing = [
                term
                for term in experiment.task.acceptance_terms
                if term.casefold() not in lowered
            ]
            self.assertTrue(missing, f"{agent.agent_id} is self-sufficient")

    def test_rejects_canary_shared_by_two_agents(self) -> None:
        with self.assertRaisesRegex(ExperimentSpecError, "unattributable"):
            spec(
                agents=(
                    first_agent(),
                    second_agent(
                        context=(
                            ContextFile(
                                path="deployment.txt",
                                content=(
                                    "cache_mode changed from local to shared\n"
                                    "correlation id req-4471\n"
                                ),
                            ),
                        ),
                        canary="chg-2291",
                    ),
                )
            )

    def test_rejects_canary_absent_from_its_own_context(self) -> None:
        with self.assertRaisesRegex(ExperimentSpecError, "absent from its own"):
            spec(agents=(first_agent(canary="req-0000"), second_agent()))

    def test_canary_may_be_omitted(self) -> None:
        experiment = spec(
            agents=(first_agent(canary=None), second_agent(canary=None)),
        )
        self.assertEqual(experiment.canaries(), ())


class LayoutTests(unittest.TestCase):
    def test_write_experiment_creates_its_own_folder(self) -> None:
        experiment = spec()
        with tempfile.TemporaryDirectory() as raw:
            root = write_experiment(experiment, raw)
            self.assertEqual(root.name, "cache-outage-v1")
            self.assertTrue((root / SPEC_FILENAME).is_file())
            self.assertEqual(
                (root / "digest.txt").read_text(encoding="utf-8").strip(),
                experiment.sha256,
            )
            self.assertTrue((root / "runs").is_dir())
            self.assertTrue(
                (root / "agents" / "agent-1" / "context" / "application.log").is_file()
            )
            self.assertTrue(
                (root / "agents" / "agent-2" / "context" / "deployment.txt").is_file()
            )

    def test_write_experiment_is_idempotent_and_refuses_a_different_spec(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            first = write_experiment(spec(), raw)
            again = write_experiment(spec(), raw)
            self.assertEqual(first, again)
            with self.assertRaisesRegex(ExperimentSpecError, "different experiment"):
                write_experiment(spec(seeds=(3,)), raw)

    def test_load_experiment_round_trips(self) -> None:
        experiment = spec()
        with tempfile.TemporaryDirectory() as raw:
            root = write_experiment(experiment, raw)
            self.assertEqual(load_experiment(root).sha256, experiment.sha256)
            self.assertEqual(
                load_experiment(root / SPEC_FILENAME).to_dict(), experiment.to_dict()
            )

    def test_load_experiment_fails_closed_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaisesRegex(ExperimentSpecError, "no experiment"):
                load_experiment(raw)


class InjectionTests(unittest.TestCase):
    def test_materialize_writes_only_its_own_context(self) -> None:
        experiment = spec()
        with tempfile.TemporaryDirectory() as raw:
            task_dir = Path(raw) / "agent-1" / "task"
            written = materialize_agent_context(experiment, task_dir, "agent-1")
            present = sorted(
                path.relative_to(task_dir).as_posix()
                for path in task_dir.rglob("*")
                if path.is_file()
            )
            self.assertEqual(present, ["application.log"])
            self.assertEqual([path.name for path in written], ["application.log"])
            body = (task_dir / "application.log").read_text(encoding="utf-8")
            self.assertIn("revision-88", body)
            self.assertNotIn("cache_mode", body)
            self.assertNotIn("chg-2291", body)

    def test_materialize_fails_closed_for_an_unknown_agent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaisesRegex(ExperimentSpecError, "unknown agent"):
                materialize_agent_context(spec(), raw, "agent-9")


if __name__ == "__main__":
    unittest.main()
