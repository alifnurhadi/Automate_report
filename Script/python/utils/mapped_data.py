import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_PATH = BASE_DIR / "secret.json"

MAX_WORKERS = min(32, (os.cpu_count() or 1) + 4)

CATEGORY_MAPPING = {
    'critical_report': 'Critical Report',
    'general_ledger': 'General Ledger',
    'rekening_koran': 'Rekening Koran',
}

CRITICAL_REPORT = {
    'from datalake.`10000_cr_', 'tical report', ' ds between'
}

GENERAL_LEDGER = {
    'gl ', 'general ledger', '_glhist', 'gl number',
    'rincian gl', "172.18.53.138", "172.24.49.242", "172.18.36.229",
    "172.24.83.98", "172.18.141.2"
}

REKENING_KORAN = {
    '.[request_account_statement_channel]',
    '_ddhist', '172.18.76.23', '8000_rc', 'ment_rc'
}

CATEGORIES_KEYWORDS = {
    'critical_report': CRITICAL_REPORT,
    'general_ledger': GENERAL_LEDGER,
    'rekening_koran': REKENING_KORAN
}

COMPLEXITY_GROUP = {
    'Simple':{'Critical Report','General Ledger','Rekening Koran'}
}

SEARCH_FIELDS = [
    'title', 'server', 'database', 'table',
    'description', 'langkah_kerja', 'disclaimer', 'filled_fields',
]

MULTI_VALUE_FIELDS = {'server', 'database', 'table'}

MIN_WINNING_SCORE = 2


def extract_all_strings(val) -> list[str]:
    """Recursively extract string values from nested dicts, lists, or primitives."""
    texts = []
    if val is None:
        return texts
    if isinstance(val, str):
        if val.strip():
            texts.append(val.strip())
    elif isinstance(val, (list, tuple, set)):
        for item in val:
            texts.extend(extract_all_strings(item))
    elif isinstance(val, dict):
        for sub_val in val.values():
            texts.extend(extract_all_strings(sub_val))
    else:
        texts.append(str(val))
    return texts


def iter_items(field: str, value):
    """Yield (label, text) for every individual value inside a field.

    * dict  -> one branch per key (label becomes "field.key")
    * list  -> one item per element
    * str   -> split on '|' when the field is multi-valued (server/database/table)
    """
    if value is None:
        return
    if isinstance(value, dict):
        for key, sub in value.items():
            yield from iter_items(f"{field}.{key}", sub)
    elif isinstance(value, (list, tuple, set)):
        for sub in value:
            yield from iter_items(field, sub)
    else:
        text = str(value).strip()
        if not text:
            return
        parts = text.split('|') if field in MULTI_VALUE_FIELDS else [text]
        for part in parts:
            part = part.strip()
            if part:
                yield field, part


def match_item(text: str) -> dict:
    """Check ONE value against EVERY category in the mapping.

    Returns {category_key: [matched keywords]}; an empty list means no hit.
    A keyword counts once per item (presence, not frequency). The text is
    padded with a space on both sides so keywords written with a leading or
    trailing space (' ds between', 'gl ') still match at the item's edges.
    """
    padded = f" {text.lower()} "
    return {
        cat: sorted(kw for kw in kws if kw.lower() in padded)
        for cat, kws in CATEGORIES_KEYWORDS.items()
    }


def score_items(issue_data: dict) -> list[dict]:
    """Step 1: one temporary result per value, not one per field.

    A field with three tables produces three results, each checked against
    every category. An empty field produces a single placeholder (item=None).
    """
    results = []
    for field in SEARCH_FIELDS:
        items = list(iter_items(field, issue_data.get(field)))
        if not items:
            results.append({
                "field": field,
                "item": None,
                "hits": {cat: [] for cat in CATEGORIES_KEYWORDS},
            })
            continue
        for label, text in items:
            results.append({"field": label, "item": text, "hits": match_item(text)})
    return results


def decide_category(item_results: list[dict], current_adhoc: str) -> dict:
    """Step 2: add up every temporary result and decide the final group.

    Rules:
      * category score = sum of keyword hits over ALL item results
      * top score < MIN_WINNING_SCORE -> weak evidence, keep current group
      * tie for first place           -> ambiguous, keep current group
      * single clear winner           -> suggest it
    """
    totals = {
        cat: sum(len(r["hits"][cat]) for r in item_results)
        for cat in CATEGORIES_KEYWORDS
    }
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    top_score = ranked[0][1]
    winners = [cat for cat, score in ranked if score == top_score]
    keep = current_adhoc or "Unknown"
    totals_text = ", ".join(f"{CATEGORY_MAPPING[c]}={s}" for c, s in ranked)

    if top_score < MIN_WINNING_SCORE:
        suggested = keep
        reason = (
            f"Highest score is only {top_score} (needs >= {MIN_WINNING_SCORE}) "
            f"({totals_text}); falling back to current '{keep}', no suggestion."
        )
    elif len(winners) > 1:
        names = " / ".join(CATEGORY_MAPPING[c] for c in winners)
        suggested = keep
        reason = (
            f"Tie at {top_score} between {names} ({totals_text}); "
            f"ambiguous, falling back to current '{keep}', no suggestion."
        )
    else:
        winner = winners[0]
        suggested = CATEGORY_MAPPING[winner]
        n_items = sum(1 for r in item_results if r["hits"][winner])
        reason = (
            f"{suggested} wins with {top_score} hit(s) from {n_items} item(s) vs "
            f"{ranked[1][1]} for the next category ({totals_text})."
        )
    return {"totals": totals, "suggested": suggested, "reason": reason}


def check_logic(issue_data: dict, compare_value: dict = None) -> dict:
    """Score every item, decide the category, and only then flag a change."""
    ticket_key = issue_data.get('ticket', '')

    raw_adhoc = issue_data.get('group_adhoc') or issue_data.get('Group AdHoc', '')
    adhoc_texts = extract_all_strings(raw_adhoc)
    current_adhoc = adhoc_texts[0] if adhoc_texts else ""

    item_results = score_items(issue_data)
    decision = decide_category(item_results, current_adhoc)
    suggested_adhoc = decision["suggested"]

    needs_update = bool(
        suggested_adhoc != "Unknown"
        and current_adhoc.lower() != suggested_adhoc.lower()
    )
    status = "suggested to change" if needs_update else "no-changes"

    summary = (
        f"{ticket_key}: '{current_adhoc}' -> '{suggested_adhoc}' "
        f"[{status}]. {decision['reason']}"
    )

    return {
        "ticket": ticket_key,
        "old_group_adhoc": current_adhoc,
        "suggested_group_adhoc": suggested_adhoc,
        "status": status,
        "needs_update": needs_update,
        "item_scores": item_results,
        "category_totals": decision["totals"],
        "decision_summary": summary,
    }


def get_complexity_for_category(category_name: str) -> str:
    """Map category name to complexity group from COMPLEXITY_GROUP."""
    if category_name in ( '', None ):
        return ""
    for complexity_level, categories in COMPLEXITY_GROUP.items():
        if any(cat.lower() == str(category_name).lower() for cat in categories):
            return complexity_level
    return ""


def check_complexity_logic(issue_data: dict, compare_value: dict = None) -> dict:
    """Evaluate ticket complexity based on Jira Complexity field or mapped category."""
    ticket_key = issue_data.get('ticket', '')

    raw_complexity = issue_data.get('complexity') or issue_data.get('Complexity', '')

    adhoc_texts = extract_all_strings(raw_complexity)
    current_complexity = adhoc_texts[0] if adhoc_texts else ""

    if not raw_complexity and 'filled_fields' in issue_data:
        raw_complexity = issue_data['filled_fields'].get('Complexity', '')

    cat_result = check_logic(issue_data)
    detected_category = cat_result.get('old_group_adhoc', '')

    print('[debug] : original',raw_complexity , ' ' , ticket_key)
    print('[debug] :',repr(raw_complexity))
    if raw_complexity in ('' , None ) :
        print('[debug] :here', ' ' , ticket_key, ' ',detected_category)
        suggested_complexity = get_complexity_for_category(detected_category)
        print('[debug] : suggested\n ',suggested_complexity , ' ' , ticket_key)
    else:
        print('[debug] :there ', ' ' , ticket_key)
        suggested_complexity = raw_complexity
    # Derive suggested complexity from category or mapped complexity rules


    needs_update = bool(
        suggested_complexity != "Unknown"
        and current_complexity.lower() != suggested_complexity.lower()
    )
    status = "suggested to change" if needs_update else "no-changes"

    summary = (
        f"{ticket_key}: Complexity '{current_complexity or 'NOT_FOUND'}' -> '{suggested_complexity}' "
        f"[{status}] (mapped from category '{detected_category}')"
    )

    return {
        "ticket": ticket_key,
        "old_complexity": current_complexity,
        "suggested_complexity": suggested_complexity,
        "category": detected_category,
        "status": status,
        "needs_update": needs_update,
        "decision_summary": summary
    }


def _short(text: str, width: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def format_calculation(result: dict) -> str:
    """Readable per-item table (one row per value), ending with the summary."""
    rows = result.get("item_scores")
    if not rows:
        return result.get("decision_summary") or (
            f"{result.get('ticket')}: {result.get('status')} "
            f"({result.get('suggested_group_adhoc')})"
        )

    cats = list(CATEGORIES_KEYWORDS)
    names = [CATEGORY_MAPPING[c] for c in cats]
    fw, iw = 24, 36
    header = (
        f"{'field':<{fw}} | {'item':<{iw}} | "
        + " | ".join(names)
        + " | matched keywords"
    )
    lines = [f"=== {result['ticket']} ===", header, "-" * len(header)]

    # Only rows with at least one keyword hit are shown; the rest are hidden.
    matched_rows = [r for r in rows if any(r["hits"][c] for c in cats)]
    if not matched_rows:
        lines.append("(no item matched any keyword)")

    for r in matched_rows:
        item = _short(r["item"], iw)
        counts = " | ".join(f"{len(r['hits'][c]):^{len(n)}}" for c, n in zip(cats, names))
        matched = "; ".join(
            f"{CATEGORY_MAPPING[c]}: {r['hits'][c]}" for c in cats if r["hits"][c]
        )
        lines.append(f"{_short(r['field'], fw):<{fw}} | {item:<{iw}} | {counts} | {matched}")

    lines.append("-" * len(header))
    totals = result["category_totals"]
    total_counts = " | ".join(f"{totals[c]:^{len(n)}}" for c, n in zip(cats, names))
    lines.append(f"{'TOTAL':<{fw}} | {'':<{iw}} | {total_counts} |")
    lines.append("")
    lines.append(f"SUMMARY: {result['decision_summary']}")
    return "\n".join(lines)
