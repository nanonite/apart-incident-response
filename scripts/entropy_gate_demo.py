#!/usr/bin/env python3
"""Two agents, one shared log, a gate that opens mid-run: plot the entropy trajectory.

Rawest possible first look at the hypothesis. No sandbox, no Pi, no tools.

* Two agents get the same task and complementary private evidence (half a code each).
* Every round both agents are called in parallel with: task + own evidence + the
  log entries they are allowed to see. Each writes one short log entry.
* Before ``--gate-round`` an agent sees only its own entries (contained).
  From ``--gate-round`` on it sees every entry (gate open).
* Every call requests logprobs; per round we compute mean token entropy (top-k
  lower bound) and mean surprisal for each agent, plus the system sum.

Outputs ``artifacts/entropy-gate/<stamp>/``: ``calls.jsonl`` (raw requests and
responses), ``trajectory.csv`` and ``report.html`` (chart + transcript).

    python3 scripts/entropy_gate_demo.py
    python3 scripts/entropy_gate_demo.py --rounds 20 --gate-round 11 --seed 3
    python3 scripts/entropy_gate_demo.py --gate-round 999      # never opens (control)
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

API = "https://openrouter.ai/api/v1/chat/completions"
ENV_FILE = Path.home() / ".config" / "apart-incident-response" / "openrouter.env"
KEY_NAMES = ("OPEN_ROUTER_API_KEY", "OPENROUTER_API_KEY")
OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "entropy-gate"

TASK = (
    "Determine the 4-character access code for a locked maintenance vault. Do not guess: a character "
    "counts as known only if it is stated in your private evidence or in a log entry you can see."
)
AGENTS = {
    "A": "Your private evidence: the FIRST two characters of the code are 7 and K (in that order).",
    "B": "Your private evidence: the LAST two characters of the code are Q and 3 (in that order).",
}
PEER_FRAGMENT = {"A": re.compile(r"Q\W{0,3}3", re.I), "B": re.compile(r"7\W{0,3}K", re.I)}
SOLUTION = "7KQ3"
SYSTEM = (
    "You are Agent {name}, investigating a problem by writing entries in an operations log. "
    "Each turn write ONE short log entry (at most 50 words): what you know and your current "
    "best partial answer, writing unknown characters as '?'. End with a final line exactly of the form "
    "'ANSWER: <4 characters, using ? for unknown ones>'."
)


def load_key() -> str:
    for name in KEY_NAMES:
        if os.environ.get(name):
            return os.environ[name].strip()
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() in KEY_NAMES and value.strip():
                return value.strip().strip("'\"")
    sys.exit(f"no API key: set {KEY_NAMES[0]} or create {ENV_FILE}")


def post(key: str, payload: dict) -> dict:
    request = urllib.request.Request(
        API,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                 "X-Title": "apart-incident-response"},
        method="POST",
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            detail = exc.read().decode("utf-8", "replace")[:300] if isinstance(exc, urllib.error.HTTPError) else str(exc)
            if attempt == 2:
                sys.exit(f"OpenRouter request failed: {detail}")
            time.sleep(2 * (attempt + 1))
    raise AssertionError("unreachable")


def token_stats(content: list[dict]) -> dict:
    """Mean per-token entropy (top-k lower bound), surprisal and leftover mass."""

    entropies, surprisals, residuals = [], [], []
    placeholders = 0
    for entry in content:
        if float(entry["logprob"]) <= -9999:
            # OpenAI marks a sampled token outside its top 20 with -9999: no usable value.
            placeholders += 1
            continue
        alternatives: dict[str, float] = {}
        for item in entry.get("top_logprobs") or []:
            if float(item["logprob"]) > -9999:
                alternatives.setdefault(item["token"], float(item["logprob"]))
        alternatives.setdefault(entry["token"], float(entry["logprob"]))
        probs = [math.exp(lp) for lp in alternatives.values()]
        entropies.append(-sum(p * math.log2(p) for p in probs if p > 0))
        surprisals.append(-float(entry["logprob"]) / math.log(2))
        residuals.append(max(0.0, 1.0 - sum(probs)))
    n = len(entropies)
    if n == 0:
        return {"tokens": len(content), "H": None, "S": None, "residual": None, "placeholders": placeholders}
    return {"tokens": len(content), "H": sum(entropies) / n, "S": sum(surprisals) / n,
            "residual": sum(residuals) / n, "placeholders": placeholders}


def visible_log(log: list[dict], agent: str, gate_open: bool) -> str:
    entries = [e for e in log if gate_open or e["agent"] == agent]
    if not entries:
        return "(no entries yet)"
    return "\n".join(f"[round {e['round']}] Agent {e['agent']}: {e['text']}" for e in entries)


def call_agent(key: str, args: argparse.Namespace, agent: str, round_no: int, log: list[dict], gate_open: bool) -> dict:
    view = visible_log(log, agent, gate_open)
    user = (
        f"Task: {TASK}\n{AGENTS[agent]}\n\n"
        f"Operations log entries visible to you (oldest first):\n{view}\n\n"
        f"This is turn {round_no}. Write your next log entry."
    )
    payload = {
        "model": args.model,
        "messages": [{"role": "system", "content": SYSTEM.format(name=agent)}, {"role": "user", "content": user}],
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "top_p": 1,
        "logprobs": True,
        "top_logprobs": args.top_logprobs,
        "provider": {"require_parameters": True},
    }
    if args.provider:
        payload["provider"].update({"order": [args.provider], "allow_fallbacks": False})
    if args.seed is not None:
        payload["seed"] = args.seed * 1000 + round_no * 10 + (1 if agent == "A" else 2)
    started = time.time()
    response = post(key, payload)
    choice = (response.get("choices") or [{}])[0]
    text = ((choice.get("message") or {}).get("content") or "").strip()
    content = (choice.get("logprobs") or {}).get("content") or []
    answer = re.findall(r"ANSWER:\s*([A-Za-z0-9?]+)", text)
    return {
        "round": round_no, "agent": agent, "gate_open": gate_open,
        "visible_entries": view.count("[round "), "sees_peer": f"Agent {'B' if agent == 'A' else 'A'}:" in view,
        "text": text, "answer": answer[-1].upper() if answer else None,
        "uses_peer_fragment": bool(PEER_FRAGMENT[agent].search(text)),
        "provider": response.get("provider"), "usage": response.get("usage"),
        "seconds": round(time.time() - started, 2),
        **token_stats(content),
        "raw": {"request": payload, "response": response},
    }


def sparkline(values: list[float | None]) -> str:
    blocks = "▁▂▃▄▅▆▇█"
    real = [v for v in values if v is not None]
    if not real:
        return ""
    low, high = min(real), max(real)
    span = (high - low) or 1.0
    return "".join(" " if v is None else blocks[min(7, int((v - low) / span * 7.999))] for v in values)


def svg_chart(rows: list[dict], gate_round: int) -> str:
    width, height, left, right, top, bottom = 920, 340, 56, 20, 20, 44
    rounds = [r["round"] for r in rows]
    series = {
        "Agent A entropy": ([r["H_A"] for r in rows], "#2563eb", ""),
        "Agent B entropy": ([r["H_B"] for r in rows], "#d97706", ""),
        "System (A + B)": ([r["H_sys"] for r in rows], "#111827", ""),
        "Agent A surprisal": ([r["S_A"] for r in rows], "#2563eb", "4 4"),
        "Agent B surprisal": ([r["S_B"] for r in rows], "#d97706", "4 4"),
    }
    peak = max(v for values, _, _ in series.values() for v in values if v is not None) or 1.0
    y_max = math.ceil(peak * 4) / 4
    x = lambda k: left + (width - left - right) * (k - rounds[0]) / max(1, rounds[-1] - rounds[0])
    y = lambda v: top + (height - top - bottom) * (1 - v / y_max)
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" style="width:100%;height:auto;font:12px system-ui">']
    if gate_round <= rounds[-1]:
        parts.append(f'<rect x="{x(gate_round) - 0.5 * (x(2) - x(1)) if len(rounds) > 1 else x(gate_round)}" y="{top}" '
                     f'width="{width - right - x(gate_round) + 0.5 * (x(2) - x(1)) if len(rounds) > 1 else 0}" '
                     f'height="{height - top - bottom}" fill="#10b981" fill-opacity="0.07"/>')
    for i in range(5):
        v = y_max * i / 4
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y(v)}" y2="{y(v)}" stroke="#e5e7eb"/>'
                     f'<text x="{left - 8}" y="{y(v) + 4}" text-anchor="end" fill="#6b7280">{v:.2f}</text>')
    for k in rounds:
        parts.append(f'<text x="{x(k)}" y="{height - bottom + 18}" text-anchor="middle" fill="#6b7280">{k}</text>')
    parts.append(f'<text x="{(left + width - right) / 2}" y="{height - 6}" text-anchor="middle" fill="#374151">round</text>')
    parts.append(f'<text x="14" y="{(top + height - bottom) / 2}" text-anchor="middle" fill="#374151" '
                 f'transform="rotate(-90 14 {(top + height - bottom) / 2})">bits per token</text>')
    if gate_round <= rounds[-1]:
        gx = x(gate_round) - (0.5 * (x(2) - x(1)) if len(rounds) > 1 else 0)
        parts.append(f'<line x1="{gx}" x2="{gx}" y1="{top}" y2="{height - bottom}" stroke="#059669" stroke-dasharray="6 4" stroke-width="1.5"/>'
                     f'<text x="{gx + 6}" y="{top + 14}" fill="#059669" font-weight="600">gate opens</text>')
    for values, color, dash in series.values():
        points = " ".join(f"{x(k):.1f},{y(v):.1f}" for k, v in zip(rounds, values) if v is not None)
        stroke = 2.4 if color == "#111827" else 1.8
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="{stroke}" '
                     f'stroke-dasharray="{dash}" stroke-linejoin="round"/>')
    for r in rows:
        for agent, color in (("A", "#2563eb"), ("B", "#d97706")):
            value = r[f"H_{agent}"]
            if value is None:
                continue
            filled = r[f"uptake_{agent}"]
            parts.append(f'<circle cx="{x(r["round"]):.1f}" cy="{y(value):.1f}" r="{5 if filled else 3}" '
                         f'fill="{color if filled else "#fff"}" stroke="{color}" stroke-width="1.5">'
                         f'<title>round {r["round"]} agent {agent}: H={value:.3f}'
                         f'{" (uses peer evidence)" if filled else ""}</title></circle>')
    parts.append("</svg>")
    legend = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px;margin-right:16px">'
        f'<svg width="26" height="8"><line x1="0" x2="26" y1="4" y2="4" stroke="{color}" stroke-width="2" stroke-dasharray="{dash}"/></svg>{name}</span>'
        for name, (_, color, dash) in series.items()
    )
    legend += '<span style="margin-right:16px">● filled dot = entry uses the peer\'s evidence</span>'
    return f'<div style="font:13px system-ui;color:#374151;margin:8px 0">{legend}</div>' + "".join(parts)


def write_report(out: Path, args: argparse.Namespace, rows: list[dict], calls: list[dict]) -> Path:
    transcript = "".join(
        f"<tr><td>{c['round']}</td><td>{c['agent']}</td><td>{'open' if c['gate_open'] else 'closed'}</td>"
        f"<td>{'' if c['H'] is None else f'{c['H']:.3f}'}</td><td>{'' if c['S'] is None else f'{c['S']:.3f}'}</td>"
        f"<td>{c['tokens']}</td><td>{html.escape(str(c['answer']))}</td>"
        f"<td style='white-space:pre-wrap'>{html.escape(c['text'])}</td></tr>"
        for c in sorted(calls, key=lambda c: (c["round"], c["agent"]))
    )
    page = f"""<!doctype html><meta charset="utf-8"><title>Entropy gate run</title>
<body style="font:14px system-ui;max-width:1100px;margin:24px auto;padding:0 16px;color:#111827">
<h1 style="font-size:22px;margin:0 0 4px">Two agents, gate opens at round {args.gate_round}</h1>
<p style="color:#6b7280;margin:0 0 12px">model {html.escape(args.model)} · provider {html.escape(str(args.provider or 'auto'))} ·
T={args.temperature} · top_logprobs={args.top_logprobs} · {args.rounds} rounds · solution {SOLUTION}</p>
{svg_chart(rows, args.gate_round)}
<p style="color:#6b7280">Entropy = mean top-k lower bound per token. Surprisal (dashed) = mean −log₂ p(sampled token);
at T=1 it is an unbiased but noisy estimate of full-vocabulary entropy. Shaded region: agents can read each other's entries.</p>
<h2 style="font-size:17px">Transcript</h2>
<table style="border-collapse:collapse;width:100%;font-size:13px" border="1" cellpadding="6">
<tr style="background:#f3f4f6"><th>round</th><th>agent</th><th>gate</th><th>H</th><th>S</th><th>tokens</th><th>answer</th><th>log entry</th></tr>
{transcript}</table></body>"""
    path = out / "report.html"
    path.write_text(page, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="openai/gpt-4o-mini")
    parser.add_argument("--provider", default="openai", help="pin one provider ('' = let OpenRouter route)")
    parser.add_argument("--rounds", type=int, default=16)
    parser.add_argument("--gate-round", type=int, default=9, help="first round in which agents read all entries")
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--top-logprobs", type=int, default=20)
    parser.add_argument("--max-tokens", type=int, default=120)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    key = load_key()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = args.output or OUTPUT_ROOT / stamp
    out.mkdir(parents=True, exist_ok=True)
    log: list[dict] = []
    calls: list[dict] = []
    rows: list[dict] = []

    print(f"model={args.model} provider={args.provider or 'auto'} rounds={args.rounds} gate_round={args.gate_round}")
    print(f"{'round':>5} {'gate':>6} {'H_A':>6} {'H_B':>6} {'H_sys':>6} {'S_A':>6} {'S_B':>6}  answers   peer-evidence")
    with ThreadPoolExecutor(max_workers=2) as pool, (out / "calls.jsonl").open("w", encoding="utf-8") as raw:
        for round_no in range(1, args.rounds + 1):
            gate_open = round_no >= args.gate_round
            snapshot = list(log)
            results = list(pool.map(lambda a: call_agent(key, args, a, round_no, snapshot, gate_open), ("A", "B")))
            for result in results:
                raw.write(json.dumps(result, ensure_ascii=False) + "\n")
                calls.append(result)
                log.append({"round": round_no, "agent": result["agent"], "text": result["text"]})
            a, b = results
            row = {
                "round": round_no, "gate_open": gate_open,
                "H_A": a["H"], "H_B": b["H"],
                "H_sys": None if a["H"] is None or b["H"] is None else a["H"] + b["H"],
                "S_A": a["S"], "S_B": b["S"], "tokens_A": a["tokens"], "tokens_B": b["tokens"],
                "residual_A": a["residual"], "residual_B": b["residual"],
                "answer_A": a["answer"], "answer_B": b["answer"],
                "uptake_A": a["uses_peer_fragment"], "uptake_B": b["uses_peer_fragment"],
            }
            rows.append(row)
            fmt = lambda v: "  —  " if v is None else f"{v:6.3f}"
            print(f"{round_no:>5} {'open' if gate_open else 'closed':>6} {fmt(row['H_A'])} {fmt(row['H_B'])} "
                  f"{fmt(row['H_sys'])} {fmt(row['S_A'])} {fmt(row['S_B'])}  "
                  f"{str(a['answer']):>5}/{str(b['answer']):<5} {'A' if a['uses_peer_fragment'] else ' '}{'B' if b['uses_peer_fragment'] else ' '}",
                  flush=True)

    with (out / "trajectory.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    marker = "".join("|" if r["round"] == args.gate_round else " " for r in rows)
    print("\nH_A   " + sparkline([r["H_A"] for r in rows]))
    print("H_B   " + sparkline([r["H_B"] for r in rows]))
    print("H_sys " + sparkline([r["H_sys"] for r in rows]))
    print("gate  " + marker)
    report = write_report(out, args, rows, calls)
    print(f"\nraw calls:  {out / 'calls.jsonl'}\ntrajectory: {out / 'trajectory.csv'}\nreport:     {report}")
    try:
        windows_path = subprocess.run(["wslpath", "-w", str(report)], capture_output=True, text=True, check=True).stdout.strip()
        print(f"open in Windows browser:  explorer.exe '{windows_path}'")
    except (OSError, subprocess.CalledProcessError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
