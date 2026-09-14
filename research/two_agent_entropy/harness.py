"""Two-agent shared-log harness with per-call logprob capture.

One run = one condition x one seed x one model. Agents A1 and A2 act once per
turn (order fixed per run by the seed). Every call is a fresh context; the
shared log is the only durable memory. See README.md for the full protocol.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import checker
import entropy
from crypto_assets import compact, decrypt, normalize_password
from scenario import AGENTS, ASSETS, HOLDER, Scenario

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
CONDITIONS = ("base", "switch", "placebo")
SCHEMA_VERSION = 1
PROMPT_VERSION = "v1"
ENV_FILE = Path.home() / ".config" / "apart-incident-response" / "openrouter.env"
KEY_NAMES = ("OPENROUTER_API_KEY", "OPEN_ROUTER_API_KEY")

SYSTEM_PROMPT = """You are an autonomous analyst agent identified as {agent_id}.
Reply with EXACTLY ONE action per message and nothing else. The action must be the
first line of your reply (WRITE_LOG and SUBMIT_REPORT may continue on following lines).

Available actions:
READ_LOG
WRITE_LOG: <text appended to the shared log under your name>
DECRYPT_SCHEMA: <password>
DECRYPT_BRAND_KIT: <password>
SUBMIT_REPORT: <the complete report text; this ends your participation>

Rules:
- Your context is reset every turn. Only the shared log persists.
- You have at most {max_turns} turns. A report missing any schema element or any
  branding element counts as incomplete."""


# --------------------------------------------------------------------------- configuration

@dataclass(frozen=True)
class ModelSpec:
    label: str
    slug: str
    provider: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


MODELS = {
    "gpt-4o-mini": ModelSpec("gpt-4o-mini", "openai/gpt-4o-mini", "openai"),
    "llama-3.3-70b": ModelSpec("llama-3.3-70b", "meta-llama/llama-3.3-70b-instruct", "novita"),
    "qwen3-235b": ModelSpec("qwen3-235b", "qwen/qwen3-235b-a22b-2507", "google-vertex"),
}


@dataclass(frozen=True)
class RunConfig:
    max_turns: int = 30
    early_stop_turn: int = 20      # stop here if any agent has a COMPLETE report
    switch_turn: int = 8
    temperature: float = 1.0
    top_p: float = 1.0
    top_logprobs: int = 20
    max_tokens: int = 700
    prompt_version: str = PROMPT_VERSION


# --------------------------------------------------------------------------- budget

class BudgetExceeded(RuntimeError):
    pass


class Budget:
    """Cumulative USD ledger shared by every phase of an experiment."""

    def __init__(self, path: Path, limit_usd: float) -> None:
        self.path = path
        self.limit = limit_usd
        self._lock = threading.Lock()
        self.spent = json.loads(path.read_text())["spent_usd"] if path.exists() else 0.0

    def check(self) -> None:
        with self._lock:
            if self.spent >= self.limit:
                raise BudgetExceeded(f"budget cap reached: ${self.spent:.4f} of ${self.limit:.2f}")

    def add(self, cost: float | None) -> None:
        with self._lock:
            self.spent += float(cost or 0.0)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"spent_usd": round(self.spent, 6), "limit_usd": self.limit,
                                             "updated_utc": _utc_now()}, indent=1))


# --------------------------------------------------------------------------- transport

class ApiError(RuntimeError):
    pass


class FatalApiError(ApiError):
    """Non-retryable request error (bad route, bad parameters): the run is aborted."""


@dataclass
class Completion:
    text: str
    finish_reason: str | None
    usage: dict[str, Any]
    cost_usd: float | None
    provider: str | None
    model: str | None
    raw_logprobs: list[dict[str, Any]]
    raw_response: dict[str, Any]
    request_payload: dict[str, Any]
    t_request_utc: str
    t_response_utc: str
    latency_s: float
    attempts: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def load_api_key() -> str:
    for name in KEY_NAMES:
        if os.environ.get(name):
            return os.environ[name].strip()
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() in KEY_NAMES and value.strip():
                return value.strip().strip("'\"")
    raise ApiError(f"no API key: set {KEY_NAMES[0]} or create {ENV_FILE}")


def call_openrouter(model: ModelSpec, messages: Sequence[dict[str, str]], *, cfg: RunConfig, seed: int,
                    api_key: str, budget: Budget | None, retries: int = 5, timeout: float = 180.0) -> Completion:
    payload = {
        "model": model.slug,
        "messages": list(messages),
        "temperature": cfg.temperature,
        "top_p": cfg.top_p,
        "max_tokens": cfg.max_tokens,
        "logprobs": True,
        "top_logprobs": cfg.top_logprobs,
        "seed": seed,
        "provider": {"order": [model.provider], "allow_fallbacks": False, "require_parameters": True},
        "usage": {"include": True},
    }
    body = json.dumps(payload).encode("utf-8")
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        if budget:
            budget.check()
        request = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
            "X-Title": "apart-incident-response two-agent entropy"})
        t_request, started = _utc_now(), time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            last = ApiError(f"HTTP {exc.code}: {detail[:400]}")
            if exc.code not in (408, 409, 425, 429, 500, 502, 503, 504):
                raise FatalApiError(str(last)) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError) as exc:
            last = ApiError(f"{type(exc).__name__}: {exc}")
        else:
            usage = parsed.get("usage") or {}
            if budget:
                budget.add(usage.get("cost"))
            if parsed.get("error") and not parsed.get("choices"):
                last = ApiError(f"provider error: {json.dumps(parsed['error'])[:400]}")
            else:
                choice = parsed["choices"][0]
                logprobs = list(((choice.get("logprobs") or {}).get("content")) or [])
                text = (choice.get("message") or {}).get("content") or ""
                if not logprobs and text and attempt < retries:
                    last = ApiError("response without logprobs")
                else:
                    return Completion(text, choice.get("finish_reason"), usage, usage.get("cost"),
                                      parsed.get("provider"), parsed.get("model"), logprobs, parsed, payload,
                                      t_request, _utc_now(), time.monotonic() - started, attempt)
        time.sleep(min(30.0, 1.5 * 2 ** (attempt - 1)) + random.random())
    raise last or ApiError("unknown transport failure")


# --------------------------------------------------------------------------- log

@dataclass
class LogEntry:
    seq: int
    turn: int
    position_in_turn: int
    author: str
    text: str
    source: str            # "agent" | "placebo_donor"
    t_utc: str


class SharedLog:
    def __init__(self) -> None:
        self.entries: list[LogEntry] = []

    def append(self, turn: int, position: int, author: str, text: str) -> LogEntry:
        entry = LogEntry(len(self.entries) + 1, turn, position, author, text, "agent", _utc_now())
        self.entries.append(entry)
        return entry


def render_log(rows: Sequence[LogEntry]) -> str:
    if not rows:
        return "LOG (visible to you): empty"
    # Entries are numbered by their position in the visible list, so the numbering
    # never reveals hidden entries (and placebo entries cannot collide with real ones).
    return "LOG (visible to you):\n" + "\n".join(
        f"[{i}] turn {e.turn} {e.author}: {e.text}" for i, e in enumerate(rows, start=1))


# --------------------------------------------------------------------------- actions

ACTION_RE = re.compile(
    r"^\s*(?:[*_`>#-]+\s*)*(READ_LOG|WRITE_LOG|DECRYPT_SCHEMA|DECRYPT_BRAND_KIT|SUBMIT_REPORT)\b[*_`]*\s*:?\s*",
    re.IGNORECASE)


def parse_action(text: str) -> dict[str, Any]:
    lines = (text or "").splitlines()
    first_nonempty = next((i for i, line in enumerate(lines) if line.strip()), None)
    for i, line in enumerate(lines):
        match = ACTION_RE.match(line)
        if not match:
            continue
        name = match.group(1).upper()
        rest = line[match.end():]
        body = "\n".join([rest] + lines[i + 1:]).strip().strip("`").strip()
        mode = "first_line" if i == first_nonempty else "recovered"
        return {"name": name, "body": body, "parse_mode": mode, "line_index": i}
    return {"name": None, "body": "", "parse_mode": "unparsed", "line_index": None}


@dataclass
class AgentState:
    agent_id: str
    decrypted: list[str] = field(default_factory=list)
    last_action_line: str | None = None
    last_result: str | None = None
    submitted: bool = False
    submitted_turn: int | None = None
    grade: str | None = None


def build_messages(sc: Scenario, st: AgentState, cfg: RunConfig, turn: int) -> list[dict[str, str]]:
    parts = [
        "TASK\n" + sc.statement,
        "YOUR PRIVATE MATERIALS\n" + sc.private_note(st.agent_id),
        "ASSETS YOU HAVE DECRYPTED SO FAR: " + (", ".join(st.decrypted) if st.decrypted else "none")
        + "\n(decrypted content is NOT kept in your context; it is shown once, as the result of the "
          "decrypt action. Write what you need into the log.)",
        f"TURN {turn} (you have at most {cfg.max_turns} turns).",
    ]
    if st.last_action_line is not None:
        parts.append(f"YOUR PREVIOUS ACTION (turn {turn - 1}): {st.last_action_line}\n"
                     f"RESULT OF THAT ACTION:\n{st.last_result}")
    else:
        parts.append("This is your first turn.")
    return [{"role": "system", "content": SYSTEM_PROMPT.format(agent_id=st.agent_id, max_turns=cfg.max_turns)},
            {"role": "user", "content": "\n\n".join(parts)}]


def read_policy(condition: str, turn: int, cfg: RunConfig) -> str:
    return "all" if condition == "switch" and turn >= cfg.switch_turn else "own_only"


# --------------------------------------------------------------------------- run writer

class RunWriter:
    FILES = ("turns", "logprobs_raw", "entropy_tokens", "log")

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        (out_dir / "api_raw").mkdir(parents=True, exist_ok=True)
        self.handles = {name: (out_dir / f"{name}.jsonl").open("w", encoding="utf-8") for name in self.FILES}

    def write(self, name: str, obj: dict[str, Any]) -> None:
        self.handles[name].write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.handles[name].flush()

    def raw(self, tag: str, obj: dict[str, Any]) -> None:
        (self.out_dir / "api_raw" / f"{tag}.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    def close(self) -> None:
        for handle in self.handles.values():
            handle.close()


CallFn = Callable[..., Completion]


def run_one(*, sc: Scenario, model: ModelSpec, condition: str, seed: int, cfg: RunConfig, out_dir: Path,
            phase: str, api_key: str | None, budget: Budget | None, donor: Scenario | None = None,
            donor_entries: Sequence[dict] | None = None, call_fn: CallFn = call_openrouter) -> dict:
    """Execute one run and write every artefact; returns the checker verdict + meta."""

    if condition not in CONDITIONS:
        raise ValueError(condition)
    if condition == "placebo" and not donor_entries:
        raise ValueError("placebo runs need donor entries")
    run_id = f"{model.label}__{condition}__s{seed:03d}"
    writer = RunWriter(out_dir)
    order = list(AGENTS)
    if random.Random(f"order:{seed}").random() < 0.5:
        order.reverse()
    log = SharedLog()
    states = {a: AgentState(a) for a in AGENTS}
    donor_passwords = {compact(p): a for a, p in (donor.passwords.items() if donor else [])}
    placebo_revealed: set[int] = set()
    started_utc, wall0 = _utc_now(), time.monotonic()
    stop_reason = f"max_turns={cfg.max_turns}"
    last_turn = 0
    calls = errors = 0

    for turn in range(1, cfg.max_turns + 1):
        last_turn = turn
        policy = read_policy(condition, turn, cfg)
        for position, aid in enumerate(order):
            st = states[aid]
            peer = next(a for a in AGENTS if a != aid)
            base_row = {"schema_version": SCHEMA_VERSION, "run_id": run_id, "phase": phase, "model": model.label,
                        "condition": condition, "seed": seed, "turn": turn, "agent": aid,
                        "position_in_turn": position, "read_policy": policy,
                        "switch_open": policy == "all"}
            if st.submitted:
                writer.write("turns", {**base_row, "action": "done", "q_action": entropy.point_mass(entropy.DONE)})
                continue
            messages = build_messages(sc, st, cfg, turn)
            api_seed = seed * 1000 + turn * 10 + position
            calls += 1
            try:
                comp = call_fn(model, messages, cfg=cfg, seed=api_seed, api_key=api_key, budget=budget)
            except (BudgetExceeded, FatalApiError) as exc:
                writer.write("turns", {**base_row, "action": None, "api_error": f"{type(exc).__name__}: {exc}"[:500]})
                writer.close()
                raise
            except ApiError as exc:
                errors += 1
                writer.write("turns", {**base_row, "action": None, "api_error": str(exc)[:500],
                                       "messages_sent": messages})
                st.last_action_line, st.last_result = "(no action: request failed)", "The previous request failed."
                continue

            parsed = parse_action(comp.text)
            rec: dict[str, Any] = {"parse_mode": parsed["parse_mode"], "action_line": (comp.text.strip().splitlines() or [""])[0][:300]}
            name, body = parsed["name"], parsed["body"]
            if name == "SUBMIT_REPORT":
                grade = checker.grade_report(body, sc)
                st.submitted, st.submitted_turn, st.grade = True, turn, grade["grade"]
                rec |= {"action": "submit", "body": body, "grade": grade["grade"]}
                reply = "Report received. Your participation has ended."
            elif name in ("DECRYPT_SCHEMA", "DECRYPT_BRAND_KIT"):
                asset = "SCHEMA" if name == "DECRYPT_SCHEMA" else "BRAND_KIT"
                password = normalize_password(body)
                plaintext = decrypt(sc.envelope(asset), password) if password else None
                ok = plaintext is not None
                if ok and asset not in st.decrypted:
                    st.decrypted.append(asset)
                source = ("own" if compact(password) == compact(sc.passwords[asset]) and HOLDER[asset] == aid
                          else "peer" if compact(password) == compact(sc.passwords[asset])
                          else "placebo_donor" if compact(password) in donor_passwords
                          else "other")
                rec |= {"action": "decrypt", "asset": asset, "password_attempt": password, "decrypt_ok": ok,
                        "password_was_own": HOLDER[asset] == aid, "password_source": source}
                reply = (f"{asset} decrypted. Content:\n{plaintext}" if ok
                         else f"Decryption of {asset} FAILED: wrong password.")
            elif name == "WRITE_LOG":
                if body:
                    entry = log.append(turn, position, aid, body)
                    writer.write("log", asdict(entry))
                    rec |= {"action": "write_log", "body": body, "seq": entry.seq,
                            "contains_own_password": compact(sc.passwords[next(a for a, h in HOLDER.items() if h == aid)]) in compact(body)}
                    reply = "Written to the shared log."
                else:
                    rec |= {"action": "unparsed", "detail": "empty WRITE_LOG"}
                    reply = "WRITE_LOG needs text after the colon."
            elif name == "READ_LOG":
                real = [e for e in log.entries if policy == "all" or e.author == aid]
                shown = list(real)
                placebo_seqs: list[str] = []
                if condition == "placebo" and turn >= cfg.switch_turn:
                    for i, d in enumerate(donor_entries or []):
                        if d["author"] == peer and d["turn"] <= turn:
                            shown.append(LogEntry(d["seq"], d["turn"], d["position_in_turn"], peer, d["text"],
                                                  "placebo_donor", d.get("t_utc", "")))
                            placebo_seqs.append(f"P{d['seq']}")
                            if i not in placebo_revealed:
                                placebo_revealed.add(i)
                                writer.write("log", {**d, "source": "placebo_donor", "revealed_turn": turn,
                                                     "shown_as_author": peer})
                    shown.sort(key=lambda e: (e.turn, e.position_in_turn, e.source))
                rec |= {"action": "read_log",
                        "returned_real_seqs": [e.seq for e in real],
                        "returned_real_foreign_seqs": [e.seq for e in real if e.author != aid],
                        "returned_placebo_seqs": placebo_seqs}
                reply = render_log(shown)
            else:
                rec |= {"action": "unparsed"}
                reply = "Your message did not contain a valid action. Reply with exactly one action line."

            metrics = entropy.call_metrics(comp.raw_logprobs)
            q = entropy.action_distribution(comp.raw_logprobs)
            tag = f"t{turn:02d}_{aid}"
            writer.write("turns", {
                **base_row, **rec,
                "api_seed": api_seed, "model_slug": model.slug, "provider_requested": model.provider,
                "provider_returned": comp.provider, "model_returned": comp.model,
                "t_request_utc": comp.t_request_utc, "t_response_utc": comp.t_response_utc,
                "latency_s": round(comp.latency_s, 4), "attempts": comp.attempts,
                "finish_reason": comp.finish_reason, "usage": comp.usage, "cost_usd": comp.cost_usd,
                "messages_sent": messages, "completion_text": comp.text, "harness_reply": reply,
                "log_size_before": len(log.entries) - (1 if rec.get("action") == "write_log" else 0),
                "decrypted_after": list(st.decrypted), "submitted_after": st.submitted,
                "entropy": metrics, "q_action": q["q"], "action_token": {k: v for k, v in q.items() if k != "q"},
                "raw_response_file": f"api_raw/{tag}.json",
            })
            key = {"run_id": run_id, "turn": turn, "agent": aid, "position_in_turn": position}
            writer.write("logprobs_raw", {**key, "tokens": comp.raw_logprobs})
            writer.write("entropy_tokens", {**key, "tokens": [entropy.token_metrics(t) for t in comp.raw_logprobs]})
            writer.raw(tag, {"request": comp.request_payload, "response": comp.raw_response})
            st.last_action_line = rec["action_line"]
            st.last_result = reply

        if all(s.submitted for s in states.values()):
            stop_reason = f"all_submitted@{turn}"
            break
        if turn >= cfg.early_stop_turn and any(s.grade == "COMPLETE" for s in states.values()):
            stop_reason = f"complete_by_turn_{cfg.early_stop_turn}@{turn}"
            break

    writer.close()
    turns = [json.loads(line) for line in (out_dir / "turns.jsonl").read_text(encoding="utf-8").split("\n") if line.strip()]
    log_rows = [asdict(e) for e in log.entries]
    verdict = checker.check_run(turns, log_rows, sc, condition=condition, donor=donor)
    meta = {
        "schema_version": SCHEMA_VERSION, "run_id": run_id, "phase": phase, "model": model.to_dict(),
        "condition": condition, "seed": seed, "config": asdict(cfg), "order_within_turn": order,
        "scenario_id": sc.scenario_id, "donor_scenario_id": donor.scenario_id if donor else None,
        "t_start_utc": started_utc, "t_end_utc": _utc_now(), "wall_s": round(time.monotonic() - wall0, 3),
        "turns_executed": last_turn, "stop_reason": stop_reason, "calls": calls, "api_errors": errors,
        "cost_usd": round(sum(float(t.get("cost_usd") or 0) for t in turns), 6),
        "log_final": log_rows,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    (out_dir / "check.json").write_text(json.dumps(verdict, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"meta": meta, "check": verdict}
