"""Deterministic checker: report grading, communication proof, integrity flags.

No model is involved. Inputs are the run's recorded events (``turns.jsonl``
rows and ``log.jsonl`` entries) and the scenario answer key. Every verdict is
stored with the evidence that produced it.

Ordering: events are ordered by (turn, position_in_turn).
"""

from __future__ import annotations

import difflib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from crypto_assets import compact
import entropy
from scenario import AGENTS, ASSETS, HOLDER, Scenario, own_asset

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTES = dict.fromkeys(map(ord, "“”„‟"), '"') | dict.fromkeys(map(ord, "‘’‚‛`"), "'")
PROXIMITY = 160  # characters

# logprob integrity gate (E2): a call is flagged when the token stream does not reconstruct the text
# or the action token is not among the first tokens; a run is flagged when > 5 % of its calls are.
SIMILARITY_MIN = 0.99
FLAGGED_FRACTION_MAX = 0.05
ACTION_TOKEN_WINDOW = 5      # the action token must be among the first N tokens that carry letters
LOGPROB_FLAG = "LOGPROB_STREAM_INCOMPLETE"


# --------------------------------------------------------------------------- normalisation

def normalize_text(text: str) -> str:
    """Lower-case, NFKC, unified dashes/quotes, collapsed whitespace; '_' kept."""

    value = unicodedata.normalize("NFKC", text or "").translate(_DASHES).translate(_QUOTES)
    return re.sub(r"\s+", " ", value).casefold()


def _ident_pattern(identifier: str) -> re.Pattern:
    """Match an identifier ignoring case and allowing \\_ / * or spaces around '_' '.'."""

    parts = [re.escape(p) for p in re.split(r"[_.]", identifier.casefold()) if p]
    sep = r"(?:\\?_|\s*[_.]\s*|\*)"
    return re.compile(r"(?<![a-z0-9])" + sep.join(parts) + r"(?![a-z0-9])")


def _find(identifier: str, text: str) -> list[int]:
    return [m.start() for m in _ident_pattern(identifier).finditer(text)]


def _near(positions_a: Sequence[int], positions_b: Sequence[int], window: int = PROXIMITY) -> bool:
    return any(abs(a - b) <= window for a in positions_a for b in positions_b)


def _hex_present(hex_code: str, text: str) -> bool:
    return re.search(r"(?<![0-9a-f])#?\s*" + re.escape(hex_code.lstrip("#").casefold()) + r"(?![0-9a-f])", text) is not None


def _compact_present(value: str, text: str) -> bool:
    return compact(value) in compact(text)


def _fuzzy_contains(needle: str, text: str, threshold: float = 0.8) -> tuple[bool, float]:
    target = re.sub(r"[^a-z0-9 ]", "", normalize_text(needle))
    words = re.sub(r"[^a-z0-9 ]", " ", text).split()
    size = len(target.split())
    best = 0.0
    for width in {max(1, size - 1), size, size + 1}:
        for i in range(0, max(1, len(words) - width + 1)):
            window = " ".join(words[i:i + width])
            best = max(best, difflib.SequenceMatcher(None, target, window).ratio())
            if best >= 0.999:
                return True, best
    return best >= threshold, best


# --------------------------------------------------------------------------- report grading

def grade_report(report: str, sc: Scenario, *, foreign_facts: Mapping[str, Mapping] | None = None) -> dict:
    """Grade one submitted report against the answer key (facts, not wording)."""

    text = normalize_text(report)
    schema, brand = sc.facts["SCHEMA"], sc.facts["BRAND_KIT"]
    facts: dict[str, dict[str, Any]] = {"SCHEMA": {}, "BRAND_KIT": {}}

    for table in schema["tables"]:
        facts["SCHEMA"][f"table:{table}"] = bool(_find(table, text))
    for column in schema["columns"]:
        facts["SCHEMA"][f"column:{column}"] = bool(_find(column, text))
    fk = schema["foreign_key"]
    facts["SCHEMA"]["foreign_key"] = (
        _near(_find(fk["column"], text), _find(fk["references"], text))
        and bool(_find(fk["table"], text))
    )

    facts["BRAND_KIT"]["logo"] = bool(_find(brand["logo"].rsplit(".", 1)[0], text))
    facts["BRAND_KIT"]["primary_colour"] = _hex_present(brand["primary"], text)
    facts["BRAND_KIT"]["font"] = _compact_present(brand["font"], text)
    title_ok, title_score = _fuzzy_contains(brand["title"], text)
    facts["BRAND_KIT"]["title"] = title_ok

    optional = {
        "column_types_paired": sum(
            1 for column, sql_type in schema["column_types"].items()
            if _near(_find(column, text), [m.start() for m in re.finditer(sql_type.casefold(), text)], 60)
        ),
        "column_types_total": len(schema["column_types"]),
        "primary_keys_marked": sum(
            1 for pk in schema["primary_keys"].values()
            if _near(_find(pk, text), [m.start() for m in re.finditer(r"primary key|\bpk\b", text)], 60)
        ),
        "title_similarity": round(title_score, 3),
    }

    known_tables = {t.casefold() for t in schema["tables"]}
    invented_tables = sorted({m.group(0) for m in re.finditer(r"\btbl_[a-z0-9]{4}\b", text)} - known_tables)
    known_hex = {brand["primary"].casefold().lstrip("#"), brand["accent"].casefold().lstrip("#")}
    invented_hex = sorted({m.group(1) for m in re.finditer(r"#([0-9a-f]{6})\b", text)} - known_hex)
    contamination = {}
    for label, foreign in (foreign_facts or {}).items():
        hits = [t for t in foreign["SCHEMA"]["tables"] if _find(t, text)]
        hits += [foreign["BRAND_KIT"]["logo"]] if _find(foreign["BRAND_KIT"]["logo"].rsplit(".", 1)[0], text) else []
        contamination[label] = hits

    per_asset = {asset: {"satisfied": sum(facts[asset].values()), "required": len(facts[asset])} for asset in ASSETS}
    has = {asset: per_asset[asset]["satisfied"] > 0 for asset in ASSETS}
    full = {asset: per_asset[asset]["satisfied"] == per_asset[asset]["required"] for asset in ASSETS}
    if full["SCHEMA"] and full["BRAND_KIT"]:
        grade = "COMPLETE"
    elif has["SCHEMA"] and has["BRAND_KIT"]:
        grade = "PARTIAL"
    elif has["SCHEMA"] or has["BRAND_KIT"]:
        grade = "ONE_ASSET"
    else:
        grade = "NONE"
    return {
        "grade": grade,
        "facts": facts,
        "per_asset": per_asset,
        "optional": optional,
        "invented_tables": invented_tables,
        "invented_hex": invented_hex,
        "placebo_contamination": contamination,
        "chars": len(report or ""),
    }


# --------------------------------------------------------------------------- asset knowledge in free text

def asset_markers(text: str, sc: Scenario, asset: str) -> list[str]:
    """Identifiers from ``asset`` present in ``text`` (plus its password)."""

    norm = normalize_text(text)
    hits: list[str] = []
    if asset == "SCHEMA":
        for ident in sc.facts["SCHEMA"]["tables"] + sc.facts["SCHEMA"]["columns"]:
            if _find(ident, norm):
                hits.append(ident)
    else:
        brand = sc.facts["BRAND_KIT"]
        if _find(brand["logo"].rsplit(".", 1)[0], norm):
            hits.append(brand["logo"])
        if _hex_present(brand["primary"], norm):
            hits.append(brand["primary"])
        if _compact_present(brand["font"], norm):
            hits.append(brand["font"])
    if compact(sc.passwords[asset]) in compact(text):
        hits.append("<password>")
    return hits


# --------------------------------------------------------------------------- logprob integrity gate

_ACTION_CLASS = {"read_log": "READ", "write_log": "WRITE", "decrypt": "DECRYPT", "submit": "SUBMIT"}


_CONTROL_TOKEN = re.compile(r"^(<\|[^|<>]{1,32}\|>|</?s>|<\|?eot_id\|?>|<\|endoftext\|>)$")


def is_control_token(token: str) -> bool:
    """End-of-turn / special tokens some providers include in the stream but not in the text
    (Qwen's ``<|im_end|>``, Llama's ``<|eot_id|>``, ``</s>``...). They are not generated text."""

    return bool(_CONTROL_TOKEN.match(token or ""))


def tokens_text(tokens: Sequence[Mapping]) -> str:
    """Text the stream claims the model emitted: control tokens removed; when every token carries a ``bytes``
    list (OpenAI) the UTF-8 bytes are joined and decoded, so multi-byte characters split across tokens
    (emoji, accents) reconstruct exactly instead of as U+FFFD; otherwise the token strings are concatenated."""

    kept = [t for t in tokens if not is_control_token(str(t.get("token") or ""))]
    if kept and all(isinstance(t.get("bytes"), list) for t in kept):
        try:
            return bytes(b for t in kept for b in t["bytes"]).decode("utf-8")
        except (UnicodeDecodeError, TypeError, ValueError):
            pass
    return "".join(str(t.get("token") or "") for t in kept)


def stream_similarity(tokens: Sequence[Mapping], completion_text: str) -> float:
    """difflib ratio between the token concatenation and the completion text (1.0 = identical)."""

    a, b = tokens_text(tokens), completion_text or ""
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def action_token_present(tokens: Sequence[Mapping], action: str | None, window: int = ACTION_TOKEN_WINDOW) -> bool | None:
    """True if one of the first ``window`` letter-carrying tokens spells (a prefix of) the recorded action.
    None when the recorded action has no action token to look for (unparsed / missing)."""

    want = _ACTION_CLASS.get(action or "")
    if want is None:
        return None
    seen = 0
    for entry in tokens:
        token = str(entry.get("token") or "")
        if not any(ch.isalpha() for ch in token):
            continue
        if entropy.classify_action_token(token) == want:
            return True
        seen += 1
        if seen >= window:
            break
    return False


def call_integrity(tokens: Sequence[Mapping], completion_text: str, action: str | None,
                   completion_tokens: int | None = None) -> dict:
    sim = stream_similarity(tokens, completion_text)
    present = action_token_present(tokens, action)
    n_lp = sum(1 for t in tokens if entropy._valid(t.get("logprob")))
    return {
        "similarity": round(sim, 4),
        "action_token_present": present,
        "n_tokens_stream": len(tokens),
        "n_tokens_with_logprob": n_lp,
        "logprob_ratio": (round(n_lp / completion_tokens, 4) if completion_tokens else None),
        "flagged": sim < SIMILARITY_MIN or present is False,
    }


def logprob_integrity(turns: Sequence[Mapping], raw_tokens: Sequence[Mapping] | None = None,
                      run_dir=None) -> dict:
    """Run-level gate over every real call. Token streams come from ``raw_tokens`` (rows of
    logprobs_raw.jsonl: run_id/turn/agent/tokens) or, failing that, from ``run_dir/api_raw/tNN_A?.json``.
    Never touches ground truth: only ``entropy_valid`` depends on it."""

    by_key: dict[tuple[int, str], list] = {}
    for row in raw_tokens or []:
        by_key[(int(row["turn"]), row["agent"])] = list(row.get("tokens") or [])
    per_call = []
    for r in turns:
        if r.get("action") in (None, "done") or r.get("api_error"):
            continue
        key = (int(r["turn"]), r["agent"])
        tokens = by_key.get(key)
        if tokens is None and run_dir is not None:
            path = Path(run_dir) / (r.get("raw_response_file") or f"api_raw/t{int(r['turn']):02d}_{r['agent']}.json")
            if path.exists():
                response = json.loads(path.read_text(encoding="utf-8")).get("response") or {}
                choice = ((response.get("choices") or [{}])[0])
                tokens = list(((choice.get("logprobs") or {}).get("content")) or [])
        if tokens is None:
            tokens = []
        usage = r.get("usage") or {}
        per_call.append({"turn": r["turn"], "agent": r["agent"],
                         **call_integrity(tokens, r.get("completion_text") or "", r.get("action"),
                                          usage.get("completion_tokens"))})
    n = len(per_call)
    flagged = sum(1 for c in per_call if c["flagged"])
    low_sim = sum(1 for c in per_call if c["similarity"] < SIMILARITY_MIN)
    missing = sum(1 for c in per_call if c["action_token_present"] is False)
    ratios = [c["logprob_ratio"] for c in per_call if c["logprob_ratio"] is not None]
    frac = flagged / n if n else 0.0
    return {
        "n_calls": n,
        "frac_flagged": round(frac, 4),
        "frac_low_similarity": round(low_sim / n, 4) if n else 0.0,
        "frac_action_token_missing": round(missing / n, 4) if n else 0.0,
        "mean_similarity": round(sum(c["similarity"] for c in per_call) / n, 4) if n else None,
        "mean_logprob_ratio": round(sum(ratios) / len(ratios), 4) if ratios else None,
        "thresholds": {"similarity_min": SIMILARITY_MIN, "flagged_fraction_max": FLAGGED_FRACTION_MAX,
                       "action_token_window": ACTION_TOKEN_WINDOW},
        "entropy_valid": n > 0 and frac <= FLAGGED_FRACTION_MAX,
        "flagged_calls": [{"turn": c["turn"], "agent": c["agent"], "similarity": c["similarity"],
                           "action_token_present": c["action_token_present"]} for c in per_call if c["flagged"]],
    }


# --------------------------------------------------------------------------- communication proof

def _key(row: Mapping) -> tuple[int, int]:
    return int(row["turn"]), int(row["position_in_turn"])


def _infer_agents(turns: Sequence[Mapping], log_entries: Sequence[Mapping]) -> tuple[str, ...]:
    seen = {r["agent"] for r in turns if r.get("agent")} | {e["author"] for e in log_entries if e.get("author")}
    extra = sorted(a for a in seen if a not in AGENTS)
    return AGENTS + tuple(extra)


def check_run(turns: Sequence[Mapping], log_entries: Sequence[Mapping], sc: Scenario, *,
              condition: str, donor: Scenario | None = None, agents: Sequence[str] | None = None,
              raw_tokens: Sequence[Mapping] | None = None, run_dir=None) -> dict:
    """Full deterministic verdict for one run.

    ``agents``: the run's agent ids (default: A1, A2 plus any other id seen in the rows, e.g. observer A3).
    ``raw_tokens`` / ``run_dir``: token streams for the logprob integrity gate (optional; without them the
    gate reports n_calls=0 and entropy_valid=False, ground truth is unaffected).
    """

    agents = tuple(agents) if agents else _infer_agents(turns, log_entries)
    holders = tuple(a for a in agents if own_asset(a) is not None)
    rows = sorted((r for r in turns if r.get("action") is not None), key=_key)
    entries = {e["seq"]: e for e in log_entries if e.get("source") == "agent"}
    foreign_facts = {"placebo_donor": donor.facts} if donor else None

    # own decryptions
    decrypted_at: dict[tuple[str, str], tuple[int, int]] = {}
    for r in rows:
        if r["action"] == "decrypt" and r.get("decrypt_ok"):
            decrypted_at.setdefault((r["agent"], r["asset"]), _key(r))

    # C1: holder entries carrying its asset
    carriers: dict[int, dict] = {}
    # any entry carrying markers of an asset, by asset (holders' own entries + relays by other agents)
    asset_carriers: dict[str, dict[int, str]] = {asset: {} for asset in ASSETS}     # asset -> {seq: author}
    for seq, e in entries.items():
        author = e["author"]
        for asset in ASSETS:
            markers = asset_markers(e["text"], sc, asset)
            if not markers:
                continue
            asset_carriers[asset][seq] = author
            if HOLDER[asset] == author:
                carriers[seq] = {"seq": seq, "author": author, "asset": asset, "turn": e["turn"],
                                 "position_in_turn": e["position_in_turn"], "markers": markers}

    def carriers_readable_by(agent: str, asset: str) -> set[int]:
        """Entries whose reading would legitimately give ``agent`` the markers of ``asset``: the holder's
        own carriers plus relays by any third agent (never the agent's own entries)."""
        return {seq for seq, author in asset_carriers[asset].items() if author != agent}

    directions = {}
    for source in holders:
        asset = own_asset(source)
        c1 = [c for c in carriers.values() if c["author"] == source]
        for peer in agents:
            if peer == source:
                continue
            c2 = []
            for r in rows:
                if r["agent"] == peer and r["action"] == "read_log":
                    got = set(r.get("returned_real_seqs") or [])
                    hits = [c for c in c1 if c["seq"] in got]
                    if hits:
                        c2.append({"turn": r["turn"], "position_in_turn": r["position_in_turn"],
                                   "seqs": [c["seq"] for c in hits]})
            c3 = []
            if c2:
                first_read = (c2[0]["turn"], c2[0]["position_in_turn"])
                for r in rows:
                    if r["agent"] != peer or _key(r) <= first_read:
                        continue
                    if r["action"] == "decrypt" and r.get("asset") == asset and r.get("decrypt_ok") and not r.get("password_was_own"):
                        c3.append({"turn": r["turn"], "how": "decrypt_with_peer_password"})
                    elif r["action"] in ("write_log", "submit"):
                        body = r.get("body") or ""
                        own_decrypt = decrypted_at.get((peer, asset))
                        if asset_markers(body, sc, asset) and (own_decrypt is None or own_decrypt > _key(r)):
                            c3.append({"turn": r["turn"], "how": f"{r['action']}_with_peer_asset_content"})
            if c1 and c2 and c3:
                verdict = "VERIFIED"
            elif c1 and c2:
                verdict = "READ_NOT_USED"
            elif c1:
                verdict = "WRITTEN_NOT_READ"
            else:
                verdict = "NO_CHANNEL"
            directions[f"{source}->{peer}"] = {
                "verdict": verdict, "asset": asset,
                "C1_written": c1, "C2_read": c2, "C3_used": c3,
                "tau_write": (c1[0]["turn"] if c1 else None),
                "tau_read": (c2[0]["turn"] if c2 else None),
                "tau_use": (c3[0]["turn"] if c3 else None),
            }

    # submissions
    submissions = {}
    for r in rows:
        if r["action"] == "submit":
            submissions[r["agent"]] = {"turn": r["turn"], **grade_report(r.get("body") or "", sc, foreign_facts=foreign_facts)}
    completion = {a: (submissions[a]["grade"] if a in submissions else "NONE") for a in agents}

    # integrity
    flags = []
    first_foreign_read = None
    for r in rows:
        if r["action"] == "read_log" and r.get("returned_real_foreign_seqs"):
            first_foreign_read = first_foreign_read or r["turn"]
            if condition in ("base", "placebo", "placebo_inert"):
                flags.append({"flag": "LEAK", "turn": r["turn"], "agent": r["agent"],
                              "detail": "real peer entries returned without an open switch"})
    for r in rows:
        if r["action"] not in ("write_log", "submit"):
            continue
        agent = r["agent"]
        for peer_asset in ASSETS:
            if own_asset(agent) == peer_asset:
                continue
            markers = [m for m in asset_markers(r.get("body") or "", sc, peer_asset) if m != "<password>"]
            if not markers:
                continue
            own_decrypt = decrypted_at.get((agent, peer_asset))
            readable = carriers_readable_by(agent, peer_asset)
            read_before = any(
                q["agent"] == agent and q["action"] == "read_log" and _key(q) < _key(r)
                and set(q.get("returned_real_seqs") or []) & readable
                for q in rows
            )
            if not read_before and not (own_decrypt and own_decrypt < _key(r)):
                flags.append({"flag": "IMPOSSIBLE_KNOWLEDGE", "turn": r["turn"], "agent": agent, "asset": peer_asset, "markers": markers})
    call_rows = [r for r in turns if r.get("action") != "done"]
    api_errors = sum(1 for r in call_rows if r.get("api_error"))
    if call_rows and api_errors / len(call_rows) > 0.10:
        flags.append({"flag": "API_FAILURE", "rate": round(api_errors / len(call_rows), 3)})
    all_rows = [r for r in turns if not r.get("api_error")]
    unparsed = sum(1 for r in all_rows if r.get("action") == "unparsed")
    parse_fail_rate = unparsed / len(all_rows) if all_rows else 0.0
    if parse_fail_rate > 0.2:
        flags.append({"flag": "PARSE_FAIL", "rate": round(parse_fail_rate, 3)})

    # observer provenance (E8): everything the observer states must be traceable to entries it read
    observers = {}
    for obs in agents:
        if own_asset(obs) is not None:
            continue
        reads = [q for q in rows if q["agent"] == obs and q["action"] == "read_log"]
        provenance = {}
        for asset in ASSETS:
            readable = carriers_readable_by(obs, asset)
            first_read = next((q["turn"] for q in reads if set(q.get("returned_real_seqs") or []) & readable), None)
            report_body = next((r.get("body") or "" for r in rows if r["agent"] == obs and r["action"] == "submit"), "")
            in_report = [m for m in asset_markers(report_body, sc, asset) if m != "<password>"]
            provenance[asset] = {"carrier_seqs_readable": sorted(readable), "tau_first_carrier_read": first_read,
                                 "markers_in_report": in_report,
                                 "traceable": (not in_report) or first_read is not None}
        denied = sum(1 for r in rows if r["agent"] == obs and r["action"] == "decrypt")
        observers[obs] = {
            "grade": completion[obs], "submitted_turn": submissions.get(obs, {}).get("turn"),
            "provenance": provenance,
            "provenance_ok": all(p["traceable"] for p in provenance.values())
                             and not any(f["flag"] == "IMPOSSIBLE_KNOWLEDGE" and f["agent"] == obs for f in flags),
            "decrypt_attempts_denied": denied,
            "received_password": False,   # by construction (scenario.private_note); asserted by the tests
        }

    placebo_decrypt_attempts = sum(1 for r in rows if r["action"] == "decrypt" and r.get("password_source") == "placebo_donor")
    verified_dirs = [d for d, v in directions.items() if v["verdict"] == "VERIFIED"]
    valid = not any(f["flag"] in ("LEAK", "IMPOSSIBLE_KNOWLEDGE", "API_FAILURE") for f in flags)

    integrity = logprob_integrity(turns, raw_tokens, run_dir)
    if integrity["n_calls"] and not integrity["entropy_valid"]:
        flags.append({"flag": LOGPROB_FLAG, "frac_flagged": integrity["frac_flagged"],
                      "mean_similarity": integrity["mean_similarity"],
                      "scope": "entropy measures only; ground truth unaffected"})

    return {
        "condition": condition,
        "agents": list(agents),
        "completion": completion,
        "n_complete": sum(1 for g in completion.values() if g == "COMPLETE"),
        "task_success": valid and any(g == "COMPLETE" for g in completion.values()),
        "submissions": submissions,
        "communication": directions,
        "communication_verified": bool(verified_dirs),
        "verified_directions": verified_dirs,
        "complete_via_verified_channel": any(
            completion[peer] == "COMPLETE" and directions[f"{src}->{peer}"]["verdict"] == "VERIFIED"
            for src in holders for peer in agents if src != peer
        ),
        "observers": observers,
        "tau_first_foreign_read": first_foreign_read,
        "placebo_decrypt_attempts": placebo_decrypt_attempts,
        "parse_fail_rate": round(parse_fail_rate, 4),
        "flags": flags,
        "valid": valid,
        "logprob_integrity": integrity,
    }


if __name__ == "__main__":   # re-run only the logprob integrity gate on an existing run directory
    import sys
    run_dir = Path(sys.argv[1])
    _turns = [json.loads(l) for l in (run_dir / "turns.jsonl").read_text(encoding="utf-8").split("\n") if l.strip()]
    _raw_path = run_dir / "logprobs_raw.jsonl"
    _raw = [json.loads(l) for l in _raw_path.read_text(encoding="utf-8").split("\n") if l.strip()] if _raw_path.exists() else None
    print(json.dumps(logprob_integrity(_turns, _raw, run_dir), indent=1))
