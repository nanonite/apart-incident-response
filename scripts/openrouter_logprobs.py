#!/usr/bin/env python3
"""Send one OpenRouter chat request with logprobs and show exactly what comes back.

The key is read from ``OPEN_ROUTER_API_KEY`` (or ``OPENROUTER_API_KEY``), falling
back to ``~/.config/apart-incident-response/openrouter.env``. It is never
printed or written to the artifact.

Examples::

    python3 scripts/openrouter_logprobs.py
    python3 scripts/openrouter_logprobs.py --prompt "The root cause was" --top-logprobs 10
    python3 scripts/openrouter_logprobs.py --list-models

For every generated token the script prints the sampled token, its logprob,
probability and surprisal, the top-k alternatives, and entropy estimates:

* ``H_topk_lower``: partial sum over the returned top-k, a guaranteed lower
  bound on full-vocabulary entropy (dropped terms are >= 0);
* ``H_renorm``: entropy of the top-k renormalised to sum to 1 (a common
  approximation, not a guaranteed bound);
* ``residual``: probability mass outside the top-k;
* ``H_upper``: only with ``--vocab-size``, assumes the residual is spread evenly.

The sampled token normally appears inside ``top_logprobs`` too; it is not
counted twice.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://openrouter.ai/api/v1"
ENV_FILE = Path.home() / ".config" / "apart-incident-response" / "openrouter.env"
KEY_NAMES = ("OPEN_ROUTER_API_KEY", "OPENROUTER_API_KEY")
DEFAULT_MODEL = "inclusionai/ling-3.0-flash-vl:free"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "artifacts" / "openrouter-logprobs"


def load_key() -> str:
    for name in KEY_NAMES:
        if os.environ.get(name):
            return os.environ[name].strip()
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() in KEY_NAMES and value.strip():
                return value.strip().strip('"').strip("'")
    sys.exit(f"no API key: set {KEY_NAMES[0]} or create {ENV_FILE}")


def http_json(url: str, key: str | None = None, payload: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json", "X-Title": "apart-incident-response"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        sys.exit(f"HTTP {exc.code} from OpenRouter: {body[:800]}")


def list_models() -> None:
    models = http_json(f"{API}/models")["data"]
    capable = [
        m for m in models
        if {"logprobs", "top_logprobs"} <= set(m.get("supported_parameters") or [])
    ]
    capable.sort(key=lambda m: float(m["pricing"].get("prompt") or 0))
    print(f"{len(capable)} of {len(models)} models advertise logprobs + top_logprobs\n")
    print(f"{'model':55} {'$/M in':>9} {'$/M out':>9}")
    for m in capable:
        price_in = float(m["pricing"].get("prompt") or 0) * 1e6
        price_out = float(m["pricing"].get("completion") or 0) * 1e6
        print(f"{m['id']:55} {price_in:9.3f} {price_out:9.3f}")


class Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text


def bar(p: float, width: int = 20) -> str:
    filled = round(p * width)
    return "█" * filled + "·" * (width - filled)


def show_token(token: str) -> str:
    return json.dumps(token, ensure_ascii=False)


def entropy_stats(entry: dict, vocab_size: int | None) -> dict:
    """Entropy estimates for one position from the returned top-k logprobs."""

    alternatives: dict[str, float] = {}
    for item in entry.get("top_logprobs") or []:
        # A token string can repeat (different byte sequences); keep the first.
        alternatives.setdefault(item["token"], float(item["logprob"]))
    if entry["token"] not in alternatives:
        alternatives[entry["token"]] = float(entry["logprob"])
    probs = [math.exp(lp) for lp in alternatives.values()]
    mass = min(sum(probs), 1.0)
    residual = max(1.0 - mass, 0.0)
    lower = -sum(p * math.log2(p) for p in probs if p > 0)
    renorm = -sum((p / mass) * math.log2(p / mass) for p in probs if p > 0) if mass > 0 else 0.0
    stats = {"k": len(probs), "topk_mass": mass, "residual": residual,
             "H_topk_lower": lower, "H_renorm": renorm}
    if vocab_size and residual > 0 and vocab_size > len(probs):
        stats["H_upper"] = lower + residual * math.log2((vocab_size - len(probs)) / residual)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt", default="In one short sentence: what usually causes a cache outage after a config change?")
    parser.add_argument("--system", default=None, help="optional system message")
    parser.add_argument("--top-logprobs", type=int, default=5, help="alternatives per token (0-20)")
    parser.add_argument("--max-tokens", type=int, default=40)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--vocab-size", type=int, default=None, help="enables the entropy upper bound")
    parser.add_argument("--raw", type=int, default=2, help="print the raw JSON of the first N token entries")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--list-models", action="store_true", help="list models that advertise logprobs")
    args = parser.parse_args()

    if args.list_models:
        list_models()
        return 0
    if not 0 <= args.top_logprobs <= 20:
        parser.error("--top-logprobs must be between 0 and 20")

    style = Style(sys.stdout.isatty() and not args.no_color)
    key = load_key()
    messages = ([{"role": "system", "content": args.system}] if args.system else []) + [
        {"role": "user", "content": args.prompt}
    ]
    payload = {
        "model": args.model,
        "messages": messages,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "logprobs": True,
        "top_logprobs": args.top_logprobs,
        # Only route to providers that actually honour logprobs.
        "provider": {"require_parameters": True},
    }
    if args.seed is not None:
        payload["seed"] = args.seed

    print(style(f"→ POST {API}/chat/completions", "2"))
    print(style(json.dumps(payload, indent=2, ensure_ascii=False), "2"))
    response = http_json(f"{API}/chat/completions", key, payload)

    choice = (response.get("choices") or [{}])[0]
    content = (choice.get("logprobs") or {}).get("content") or []
    print()
    print(style("model:    ", "1") + str(response.get("model")) + style(f"   provider: {response.get('provider')}", "2"))
    print(style("response: ", "1") + str((choice.get("message") or {}).get("content")))
    print(style("finish:   ", "1") + str(choice.get("finish_reason")) + style(f"   usage: {response.get('usage')}", "2"))

    if not content:
        print(style("\nNo logprobs returned. Try another model (--list-models).", "31"))
    else:
        print(style(f"\n── raw JSON: first {min(args.raw, len(content))} of {len(content)} token entries "
                    "(choices[0].logprobs.content[i]) ──", "1"))
        for entry in content[: args.raw]:
            print(json.dumps(entry, indent=2, ensure_ascii=False))

        print(style("\n── per token ──", "1"))
        rows = []
        for index, entry in enumerate(content):
            lp = float(entry["logprob"])
            p = math.exp(lp)
            stats = entropy_stats(entry, args.vocab_size)
            rows.append({"token": entry["token"], "logprob": lp, "p": p, "surprisal_bits": -lp / math.log(2), **stats})
            upper = f"  H_upper={stats['H_upper']:.2f}" if "H_upper" in stats else ""
            print(
                style(f"[{index:>3}] ", "2") + style(f"{show_token(entry['token']):<18}", "1;36")
                + f" logprob={lp:8.4f}  p={p:6.4f}  surprisal={-lp / math.log(2):6.3f} bits"
            )
            print(
                style("      entropy ", "2")
                + f"H_topk_lower={stats['H_topk_lower']:.3f}  H_renorm={stats['H_renorm']:.3f}  "
                + f"top-k mass={stats['topk_mass']:.4f}  residual={stats['residual']:.4f}{upper}"
            )
            for alt in entry.get("top_logprobs") or []:
                ap = math.exp(float(alt["logprob"]))
                chosen = alt["token"] == entry["token"]
                marker = style("◀ sampled", "32") if chosen else ""
                print(f"        {bar(ap)} {ap:6.4f}  {float(alt['logprob']):8.4f}  {show_token(alt['token'])} {marker}")

        n = len(rows)
        print(style("\n── summary over the response ──", "1"))
        print(f"tokens:                 {n}")
        print(f"mean surprisal:         {sum(r['surprisal_bits'] for r in rows) / n:.3f} bits/token")
        print(f"total surprisal:        {sum(r['surprisal_bits'] for r in rows):.3f} bits  (= -log2 p(response))")
        print(f"mean H_topk_lower:      {sum(r['H_topk_lower'] for r in rows) / n:.3f} bits/token")
        print(f"mean H_renorm:          {sum(r['H_renorm'] for r in rows) / n:.3f} bits/token")
        print(f"mean residual mass:     {sum(r['residual'] for r in rows) / n:.4f}")
        if all("H_upper" in r for r in rows):
            print(f"mean H_upper:           {sum(r['H_upper'] for r in rows) / n:.3f} bits/token")

    args.output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = args.output / f"{stamp}-{args.model.replace('/', '_')}.json"
    path.write_text(json.dumps({"request": payload, "response": response}, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(style(f"\nsaved full request + response → {path}", "2"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
