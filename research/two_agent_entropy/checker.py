"""Deterministic checker: report grading, communication proof, integrity flags.

No model is involved. Inputs are the run's recorded events (``turns.jsonl``
rows and ``log.jsonl`` entries) and the scenario answer key. Every verdict is
stored with the evidence that produced it.

Ordering: events are ordered by (turn, position_in_turn).
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any, Iterable, Mapping, Sequence

from crypto_assets import compact
from scenario import AGENTS, ASSETS, HOLDER, Scenario

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTES = dict.fromkeys(map(ord, "“”„‟"), '"') | dict.fromkeys(map(ord, "‘’‚‛`"), "'")
PROXIMITY = 160  # characters


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


# --------------------------------------------------------------------------- communication proof

def _key(row: Mapping) -> tuple[int, int]:
    return int(row["turn"]), int(row["position_in_turn"])


def check_run(turns: Sequence[Mapping], log_entries: Sequence[Mapping], sc: Scenario, *,
              condition: str, donor: Scenario | None = None) -> dict:
    """Full deterministic verdict for one run."""

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
    for seq, e in entries.items():
        author = e["author"]
        own_asset = next(a for a, h in HOLDER.items() if h == author)
        markers = asset_markers(e["text"], sc, own_asset)
        if markers:
            carriers[seq] = {"seq": seq, "author": author, "asset": own_asset, "turn": e["turn"],
                             "position_in_turn": e["position_in_turn"], "markers": markers}

    directions = {}
    for source in AGENTS:
        peer = next(a for a in AGENTS if a != source)
        asset = next(a for a, h in HOLDER.items() if h == source)
        c1 = [c for c in carriers.values() if c["author"] == source]
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
    completion = {a: (submissions[a]["grade"] if a in submissions else "NONE") for a in AGENTS}

    # integrity
    flags = []
    first_foreign_read = None
    for r in rows:
        if r["action"] == "read_log" and r.get("returned_real_foreign_seqs"):
            first_foreign_read = first_foreign_read or r["turn"]
            if condition in ("base", "placebo"):
                flags.append({"flag": "LEAK", "turn": r["turn"], "agent": r["agent"],
                              "detail": "real peer entries returned without an open switch"})
    for r in rows:
        if r["action"] not in ("write_log", "submit"):
            continue
        agent = r["agent"]
        peer_asset = next(a for a, h in HOLDER.items() if h != agent)
        markers = [m for m in asset_markers(r.get("body") or "", sc, peer_asset) if m != "<password>"]
        if not markers:
            continue
        own_decrypt = decrypted_at.get((agent, peer_asset))
        read_before = any(
            q["agent"] == agent and q["action"] == "read_log" and _key(q) < _key(r)
            and set(q.get("returned_real_seqs") or []) & {c["seq"] for c in carriers.values() if c["asset"] == peer_asset}
            for q in rows
        )
        if not read_before and not (own_decrypt and own_decrypt < _key(r)):
            flags.append({"flag": "IMPOSSIBLE_KNOWLEDGE", "turn": r["turn"], "agent": agent, "markers": markers})
    call_rows = [r for r in turns if r.get("action") != "done"]
    api_errors = sum(1 for r in call_rows if r.get("api_error"))
    if call_rows and api_errors / len(call_rows) > 0.10:
        flags.append({"flag": "API_FAILURE", "rate": round(api_errors / len(call_rows), 3)})
    all_rows = [r for r in turns if not r.get("api_error")]
    unparsed = sum(1 for r in all_rows if r.get("action") == "unparsed")
    parse_fail_rate = unparsed / len(all_rows) if all_rows else 0.0
    if parse_fail_rate > 0.2:
        flags.append({"flag": "PARSE_FAIL", "rate": round(parse_fail_rate, 3)})

    placebo_decrypt_attempts = sum(1 for r in rows if r["action"] == "decrypt" and r.get("password_source") == "placebo_donor")
    verified_dirs = [d for d, v in directions.items() if v["verdict"] == "VERIFIED"]
    valid = not any(f["flag"] in ("LEAK", "IMPOSSIBLE_KNOWLEDGE", "API_FAILURE") for f in flags)
    return {
        "condition": condition,
        "completion": completion,
        "n_complete": sum(1 for g in completion.values() if g == "COMPLETE"),
        "task_success": valid and any(g == "COMPLETE" for g in completion.values()),
        "submissions": submissions,
        "communication": directions,
        "communication_verified": bool(verified_dirs),
        "verified_directions": verified_dirs,
        "complete_via_verified_channel": any(
            completion[peer] == "COMPLETE" and directions[f"{src}->{peer}"]["verdict"] == "VERIFIED"
            for src in AGENTS for peer in AGENTS if src != peer
        ),
        "tau_first_foreign_read": first_foreign_read,
        "placebo_decrypt_attempts": placebo_decrypt_attempts,
        "parse_fail_rate": round(parse_fail_rate, 4),
        "flags": flags,
        "valid": valid,
    }
