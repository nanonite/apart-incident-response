#!/usr/bin/env python3
"""E2b: probe which OpenRouter providers return a complete logprob stream for llama-3.3-70b-instruct.

For every provider, three short prompts (~60 tokens of completion) are requested with
logprobs=true, top_logprobs=20 and the provider pinned (allow_fallbacks=false). For each call:
  similarity      difflib ratio between the concatenation of the returned tokens and the completion text
  logprob_ratio   n tokens with a logprob / usage.completion_tokens
  action_token    whether the first letter-carrying token spells the action (prompt 1 asks for READ_LOG)
A provider is recommended when every prompt has similarity >= 0.99 (checker.SIMILARITY_MIN).

    OPENROUTER_API_KEY=... python3 probe_llama_providers.py out.csv [--providers novita,deepinfra,...]

Standard library only. The key is read from the environment (see harness.load_api_key); never written.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import checker
import harness as H

MODEL = "meta-llama/llama-3.3-70b-instruct"
DEFAULT_PROVIDERS = ("novita", "deepinfra", "together", "fireworks", "lambda", "hyperbolic", "sambanova", "groq",
                     "cerebras", "nebius", "inference-net", "friendli", "google-vertex", "azure", "amazon-bedrock",
                     "phala", "crusoe", "gmicloud", "nscale", "klusterai", "parasail", "cloudflare", "atlas-cloud",
                     "baseten", "featherless", "chutes", "ncompass", "siliconflow", "venice", "avian")

PROMPTS = (
    ("action", "Reply with exactly one line and nothing else: the action READ_LOG, followed on the next lines by "
               "a three-sentence status note (about 50 words) explaining why you read the log first."),
    ("prose", "In about 60 words, describe how a shared append-only log lets two isolated agents coordinate. "
              "Plain prose, no lists."),
    ("code", "Write a Python one-liner that reverses a string, then explain it in two short sentences "
             "(about 50 words total)."),
)


def endpoints_for(api_key: str) -> dict:
    """Providers currently listed by OpenRouter for the model (best effort; falls back to DEFAULT_PROVIDERS)."""

    url = f"https://openrouter.ai/api/v1/models/{MODEL}/endpoints"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"[:200], "endpoints": []}
    return {"endpoints": (data.get("data") or {}).get("endpoints") or []}


def call(api_key: str, provider: str, prompt: str, *, seed: int) -> dict:
    payload = {"model": MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 1.0, "top_p": 1.0,
               "max_tokens": 120, "logprobs": True, "top_logprobs": 20, "seed": seed,
               "provider": {"order": [provider], "allow_fallbacks": False}, "usage": {"include": True}}
    request = urllib.request.Request(H.ENDPOINT, data=json.dumps(payload).encode(), method="POST", headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
        "X-Title": "apart-incident-response provider probe"})
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:160]}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"[:160]}
    if parsed.get("error") and not parsed.get("choices"):
        return {"error": json.dumps(parsed["error"])[:160]}
    choice = parsed["choices"][0]
    text = (choice.get("message") or {}).get("content") or ""
    tokens = list(((choice.get("logprobs") or {}).get("content")) or [])
    usage = parsed.get("usage") or {}
    top_k = [len(t.get("top_logprobs") or []) for t in tokens]
    return {
        "provider_returned": parsed.get("provider"), "latency_s": round(time.monotonic() - started, 2),
        "completion_tokens": usage.get("completion_tokens"), "cost_usd": usage.get("cost"),
        "n_tokens_stream": len(tokens),
        "n_tokens_with_logprob": sum(1 for t in tokens if H.entropy._valid(t.get("logprob"))),
        "mean_top_k": round(sum(top_k) / len(top_k), 2) if top_k else 0,
        "similarity": round(checker.stream_similarity(tokens, text), 4),
        "chars_text": len(text), "chars_tokens": len(checker.tokens_text(tokens)),
        "finish_reason": choice.get("finish_reason"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path)
    ap.add_argument("--providers", default=None, help="comma list; default: OpenRouter endpoint list + known names")
    args = ap.parse_args()
    api_key = H.load_api_key()
    listed = endpoints_for(api_key)
    names = [e.get("provider_name") or e.get("name", "") for e in listed["endpoints"]]
    print(f"OpenRouter lists {len(names)} endpoints: {names}" + (f" ({listed['error']})" if listed.get("error") else ""), flush=True)
    slugs = [e.get("tag") or (e.get("provider_name") or "").lower() for e in listed["endpoints"]]
    if args.providers:
        providers = args.providers.split(",")
    else:
        providers = list(dict.fromkeys([s for s in slugs if s] + list(DEFAULT_PROVIDERS)))
    rows = []
    for provider in providers:
        for i, (tag, prompt) in enumerate(PROMPTS):
            r = call(api_key, provider, prompt, seed=1000 + i)
            row = {"provider": provider, "prompt": tag, **r}
            if "error" not in r and r["completion_tokens"]:
                row["logprob_ratio"] = round(r["n_tokens_with_logprob"] / r["completion_tokens"], 4)
                row["stream_ratio"] = round(r["n_tokens_stream"] / r["completion_tokens"], 4)
            rows.append(row)
            print(f"  {provider:<16} {tag:<7} " + (f"ERR {r['error'][:90]}" if "error" in r else
                  f"sim={r['similarity']:.4f} lp_ratio={row['logprob_ratio']} top_k={r['mean_top_k']} "
                  f"tokens={r['n_tokens_stream']}/{r['completion_tokens']} ${r['cost_usd']}"), flush=True)
            if "error" in r and ("404" in r["error"] or "No endpoints" in r["error"] or "not available" in r["error"].lower()):
                break   # provider does not serve this model; skip the remaining prompts
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    ok = {}
    for row in rows:
        ok.setdefault(row["provider"], []).append(row.get("similarity"))
    good = [p for p, sims in ok.items() if len(sims) == 3 and all(s is not None and s >= checker.SIMILARITY_MIN for s in sims)]
    print(f"providers with similarity >= {checker.SIMILARITY_MIN} on all 3 prompts: {good or 'NONE'}")
    print(f"wrote {args.out} ({len(rows)} rows); total cost ${sum(float(r.get('cost_usd') or 0) for r in rows):.4f}")


if __name__ == "__main__":
    sys.exit(main())
