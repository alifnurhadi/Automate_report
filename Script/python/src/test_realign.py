import concurrent.futures
import json
import re
import sys
from datetime import datetime
from pathlib import Path
import traceback


_SRC = Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_SRC, _SRC.parent) if str(p) not in sys.path]

from read_jira_v2 import (
    build_filled_fields,
    jira_access,
    load_issue_keys,
    parse_args,
)
from utils.mapped_data import (
    SECRET_PATH,
    MAX_WORKERS,
    check_logic,
    extract_all_strings,
    format_calculation,
    get_complexity_for_category,
)
from utils.parser import parse_json, simplify
from utils.log import result_logger

from utils.paths import SNAPSHOTS_DIR
EDITABLE_FIELDS_PATH = _SRC.parent / "jira_editable_field.json"

EMPTY_COMPLEXITY_OK_CATEGORIES = {"lain-lain"}
# Group AdHoc values that mean "not set" (Jira default / placeholder).
EMPTY_ADHOC_VALUES = {"", "none", "unknown", "-", "n/a"}


def log(*args):
    print(*args, file=sys.stderr)


def _norm(value) -> str:
    return str(value).strip().lower()


def _is_blank(value) -> bool:
    return _norm(value) in EMPTY_ADHOC_VALUES


def load_editable_fields() -> dict:
    with EDITABLE_FIELDS_PATH.open("r", encoding="utf-8") as f:
        fields = json.load(f)
    if not isinstance(fields, dict):
        raise ValueError("jira_editable_field.json must contain a JSON object")
    return fields


EDITABLE_FIELDS = load_editable_fields()

TARGET_FIELDS = {
    "category": {
        "jira_name": "Group AdHoc",
        "field_id": EDITABLE_FIELDS.get("Group AdHoc"),
        "json_key": "suggested_group_adhoc",
        "entry_keys": (
            "old_group_adhoc",
            "suggested_group_adhoc",
            "category_totals",
            "decision_summary",
        ),
    },
    "complexity": {
        "jira_name": "Complexity",
        "field_id": EDITABLE_FIELDS.get("Complexity"),
        "json_key": "suggested_complexity",
        "entry_keys": (
            "old_complexity",
            "suggested_complexity",
            "category",
            "decision_summary",
        ),
    },
}


# ---------- helpers ----------

def target_paths(mode: str):
    stem = f"tickets_to_update_{mode}"
    return (
        SNAPSHOTS_DIR / f"{stem}.json",
        SNAPSHOTS_DIR / f"{stem}_log.txt",
        SNAPSHOTS_DIR / f"{stem}_keys.txt",
    )


def _ticket_sort_key(key: str):
    """Natural order so ERA-2 comes before ERA-10."""
    m = re.match(r"^(.*?)(\d+)$", key)
    return (m.group(1), int(m.group(2))) if m else (key, 0)


def _sorted_by_ticket(items):
    return sorted(items, key=lambda r: _ticket_sort_key(r["ticket"]))


def _log_error(key: str, exc: Exception, filename: str):
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(SNAPSHOTS_DIR / filename, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now()} | {key} | {type(exc).__name__}: {exc}\n")


def pending_entry(res: dict, mode: str) -> dict:
    entry = {"ticket": res["ticket"]}
    entry.update({k: res.get(k) for k in TARGET_FIELDS[mode]["entry_keys"]})
    if mode == "complexity":
        entry["complexity_missing"] = bool(res.get("complexity_missing"))
    return entry


def print_report(groups: dict, mode: str):
    """Every scanned ticket, grouped by the action it needs."""
    cfg = TARGET_FIELDS[mode]
    old_key, new_key = cfg["entry_keys"][0], cfg["json_key"]

    def section(title: str, rows: list[str], count: int):
        print(f"\n=== {title} ({count}) ===")
        print("\n".join(rows) if rows else "(none)")

    update = [
        f"{u['ticket']:<14} {u.get(old_key) or '(empty)'} -> {u.get(new_key) or '(no suggestion)'}"
        for u in _sorted_by_ticket(groups["update"])
    ]
    no_change = [
        f"{r['ticket']:<14} {r.get(old_key) or '(empty)'}  "
        f"{'(no suggestion)' if _is_blank(r.get(new_key)) else '(unchanged)'}"
        for r in _sorted_by_ticket(groups["no_change"])
    ]

    by_reason = {}
    for r in groups["skipped"]:
        reason = f"{r.get('error')}: {r.get('error_msg')}"
        by_reason.setdefault(reason, []).append(r["ticket"])
    skipped = [
        f"{reason}\n    " + " ".join(sorted(tickets, key=_ticket_sort_key))
        for reason, tickets in by_reason.items()
    ]

    print(f"\n######## REPORT [{mode}] {cfg['jira_name']} ########")
    section("UPDATE", update, len(update))
    section("NO CHANGE", no_change, len(no_change))
    section("SKIPPED (by reason)", skipped, len(groups["skipped"]))


# ---------- pending / log files ----------

def write_update_keys(items: list[dict], keys_file: Path):
    """Write the keys that need an update, space-separated."""
    keys_file.parent.mkdir(parents=True, exist_ok=True)
    keys = [r["ticket"] for r in _sorted_by_ticket(items)]
    keys_file.write_text(" ".join(keys) + "\n", encoding="utf-8")
    log(f"Wrote {len(keys)} key(s) for CLI use to: {keys_file}")


def merge_pending(pending_file: Path, update_list: list[dict], scanned_ok: set):
    existing = []
    if pending_file.exists():
        try:
            loaded = json.loads(pending_file.read_text(encoding="utf-8"))
            existing = loaded if isinstance(loaded, list) else []
        except (json.JSONDecodeError, OSError):
            log("Could not read existing pending file; using this scan only.")

    fresh = {item["ticket"] for item in update_list}
    kept = [i for i in existing if i.get("ticket") not in scanned_ok]
    removed = sum(
        1 for i in existing
        if i.get("ticket") in scanned_ok and i.get("ticket") not in fresh
    )
    merged = _sorted_by_ticket(kept + update_list)
    return merged, existing, len(kept), removed


def append_update_log(results: list[dict], log_file: Path, mode: str):
    """Append tickets that need an update to a text log."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(
            f"##### Run {stamp} [{mode}] | "
            f"{len(results)} ticket(s) need update #####\n\n"
        )
        for res in _sorted_by_ticket(results):
            if mode == "complexity":
                note = "NOTE: Complexity field is empty\n" if res.get("complexity_missing") else ""
                f.write(
                    f"=== {res['ticket']} ===\n{note}"
                    f"SUMMARY: {res.get('decision_summary')}\n\n"
                )
            else:
                f.write(format_calculation(res) + "\n\n")

    log(f"Appended {len(results)} ticket(s) to log: {log_file}")


# ---------- Jira field helpers ----------

def find_editable_field(client, ticket_key: str, field_name: str):
    field_id = EDITABLE_FIELDS.get(field_name)
    if not field_id:
        raise LookupError(f"Field '{field_name}' not found in {EDITABLE_FIELDS_PATH}")

    info = client.editmeta(ticket_key).get("fields", {}).get(field_id)
    if not info:
        raise LookupError(f"Field '{field_name}' ({field_id}) is not editable on {ticket_key}")
    return field_id, info


def build_field_payload(info: dict, value: str):
    """Convert suggested text into Jira's expected field payload."""
    schema = info.get("schema") or {}
    ftype, items = schema.get("type"), schema.get("items")
    allowed = info.get("allowedValues") or []

    match = next(
        (
            opt for opt in allowed
            if (opt.get("value") or opt.get("name")) is not None
            and _norm(opt.get("value") or opt.get("name")) == _norm(value)
        ),
        None,
    )
    if allowed and match is None:
        raise ValueError("Value is not an allowed option")

    option = {"id": match["id"]} if match and "id" in match else {"value": value}

    if ftype == "array":
        return [value] if items == "string" else [option]
    if ftype in ("option", "option-with-child"):
        return option
    if ftype == "string":
        return value
    raise ValueError(f"Unsupported field type: {ftype}")


def _current_values(issue, field_id: str) -> list[str]:
    raw = issue.raw["fields"].get(field_id)
    return [s.lower() for s in extract_all_strings(simplify(raw))]


def inspect_field(client, ticket_keys: list[str], field_id: str):
    """Show type / value / editability of one field per ticket."""
    for key in ticket_keys:
        try:
            fields = client.issue(key).raw.get("fields", {})
            editable = field_id in client.editmeta(key).get("fields", {})
            print(
                f"{key} | Type: {fields.get('issuetype', {}).get('name')} | "
                f"Value: {fields.get(field_id)} | Editable: {editable}"
            )
        except Exception as exc:
            print(f"{key} | ERROR: {exc}")


# ---------- apply ----------

def apply_changes(client, pending_file: Path, target_mode: str, dry_run: bool, only_keys=None):
    """Apply pending Jira updates and verify each update."""
    if dry_run:
        print(f"*** DRY RUN [{target_mode}]: nothing will be written to Jira ***")

    if not pending_file.exists():
        log(f"No pending updates file found at {pending_file}")
        return

    tickets = json.loads(pending_file.read_text(encoding="utf-8"))

    # ---- new block starts here ----
    cfg = TARGET_FIELDS[target_mode]
    counts = {"updated": 0, "skipped": 0, "would_update": 0}

    if only_keys is not None:
        in_file = {item["ticket"] for item in tickets}
        missing = sorted(only_keys - in_file, key=_ticket_sort_key)
        if missing:
            counts["skipped"] += len(missing)
            log(f"[SKIP] {len(missing)} key(s) not in pending file: " + " ".join(missing))
        tickets = [t for t in tickets if t["ticket"] in only_keys]

    if not tickets:
        log(f"Nothing to apply: no requested key is pending in {pending_file}")
        return

    for item in tickets:
        key = item["ticket"]
        new_val = item.get(cfg["json_key"])

        try:
            if not new_val:
                raise ValueError("Missing suggested value")

            issue = client.issue(key)
            field_id, info = find_editable_field(client, key, cfg["jira_name"])
            current = _current_values(issue, field_id)

            if current == [_norm(new_val)]:
                print(f"[SKIP] {key}: {cfg['jira_name']} already correct")
                counts["skipped"] += 1
                continue

            payload = build_field_payload(info, new_val)
            before = current or "(empty)"

            if dry_run:
                print(f"[DRY-RUN] {key}: {before} -> {payload}")
                counts["would_update"] += 1
                continue

            issue.update(fields={field_id: payload})

            if _norm(new_val) not in _current_values(client.issue(key), field_id):
                raise RuntimeError("Update verification failed")

            print(f"[SUCCESS] {key}: {cfg['jira_name']} {before} -> '{new_val}'")
            counts["updated"] += 1

        except Exception as e:
            _log_error(key, e, "apply_errors.log")
            print(f"[SKIP] {key} (see apply_errors.log)")
            counts["skipped"] += 1

    summary = f"{counts['updated']} updated, {counts['skipped']} skipped"
    if dry_run:
        summary = f"{counts['would_update']} would update, {counts['skipped']} skipped (dry run)"
    log(f"\nApply finished: {summary}")


# ---------- scan ----------

def effective_category(cat: dict) -> str:
    """Current Group AdHoc, or the keyword-detected one when the current value is blank."""
    for value in (cat.get("old_group_adhoc"), cat.get("suggested_group_adhoc")):
        if not _is_blank(value):
            return str(value).strip()
    return ""


def process_single_ticket(ticket_key: str, client, id_name: dict, mode: str) -> dict:
    """Fetch ticket and evaluate category or complexity logic."""
    try:
        filled = build_filled_fields(client.issue(ticket_key), id_name)
        parsed = parse_json(
            {"key": ticket_key, "filled_fields": filled},
            EDITABLE_FIELDS_PATH,
        )
        print(parsed)

        if _is_blank(parsed.get("group_adhoc")):
            parsed["group_adhoc"] = ""

        cat = check_logic(parsed)
        if mode != "complexity":
            result_logger(parsed)
            return cat

        category = effective_category(cat)
        current = (extract_all_strings(parsed.get("complexity")) or [""])[0]
        suggested = current or get_complexity_for_category(category)
        needs_update = bool(suggested) and _norm(current) != _norm(suggested)
        status = "suggested to change" if needs_update else "no-changes"
        empty = not current

        return {
            "ticket": ticket_key,
            "old_complexity": current,
            "suggested_complexity": suggested,
            "category": category,
            "status": status,
            "needs_update": needs_update,
            "complexity_empty": empty,
            "complexity_missing": empty and _norm(category) not in EMPTY_COMPLEXITY_OK_CATEGORIES,
            "decision_summary": (
                f"{ticket_key}: Complexity '{current or 'NOT_FOUND'}' -> '{suggested}' "
                f"[{status}] (mapped from category '{category}')"
            ),
        }

    except Exception as e:
        _log_error(ticket_key, e, "scan_errors.log")
        return {
            "ticket": ticket_key,
            "status": "error",
            "needs_update": False,
            "error": type(e).__name__,
            "error_msg": " ".join(str(e).split())[:120],
        }


def scan_tickets(ticket_keys, client, id_name, mode):
    groups = {"update": [], "no_change": [], "skipped": []}
    update_results, scanned_ok = [], set()

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(process_single_ticket, key, client, id_name, mode)
            for key in ticket_keys
        ]

        for future in concurrent.futures.as_completed(futures):
            res = future.result()

            if res.get("status") == "error":
                traceback.print_exc()
                print(f"[SKIP] {res['ticket']} ({res.get('error')}, see scan_errors.log)")
                groups["skipped"].append(res)
                continue

            scanned_ok.add(res["ticket"])

            if mode == "complexity":
                print(
                    f"Ticket: {res['ticket']} | "
                    f"Old Complexity: '{res.get('old_complexity')}' | "
                    f"Suggested: '{res.get('suggested_complexity')}' | "
                    f"Category: '{res.get('category')}' | "
                    f"Status: {res['status']} | "
                    f"Complexity missing: {res.get('complexity_missing')}"
                )
            else:
                print(format_calculation(res))
                print()

            if res.get("needs_update") or res.get("complexity_missing"):
                update_results.append(res)
                groups["update"].append(pending_entry(res, mode))
            else:
                groups["no_change"].append(res)

    return groups, update_results, scanned_ok


def save_scan(update_list, update_results, scanned_ok, mode, files):
    pending_file, log_file, keys_file = files

    merged, existing, kept, removed = merge_pending(pending_file, update_list, scanned_ok)
    changed = merged != existing

    if changed:
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        pending_file.write_text(
            json.dumps(merged, indent=4, ensure_ascii=False), encoding="utf-8"
        )
        log(
            f"\nPending file updated: {len(merged)} [{mode}] ticket(s) now pending "
            f"({len(update_list)} from this scan, {kept} kept from earlier scans, "
            f"{removed} removed): {pending_file}"
        )
    elif merged or pending_file.exists():
        log(f"\nPending file unchanged: {len(merged)} [{mode}] ticket(s) pending: {pending_file}")
    else:
        log("\nNo ticket needs an update and there is no pending file.")

    if update_results:
        append_update_log(update_results, log_file, mode)

    if changed or (merged and not keys_file.exists()):
        write_update_keys(merged, keys_file)


def main():
    parser = parse_args()
    parser.add_argument("--target", choices=["category", "complexity"], default="category",
                        help="Target realigning mode: category or complexity")
    parser.add_argument("--apply", action="store_true", help="Apply saved updates to Jira")
    parser.add_argument("--dry-run", action="store_true", help="With --apply: show what would be written")
    parser.add_argument("--inspect", action="store_true",
                        help="Show type/value/editability of the target field for the given tickets")
    args = parser.parse_args()

    if args.dry_run and not args.apply:
        parser.error("--dry-run only works together with --apply")

    mode = args.target
    files = target_paths(mode)
    client, id_name = jira_access(SECRET_PATH)

    if args.inspect:
        inspect_field(client, load_issue_keys(args, parser), TARGET_FIELDS[mode]["field_id"])
        return

    if args.apply:
        only_keys = set(load_issue_keys(args, parser)) if (args.issue_key or args.file) else None
        apply_changes(client, files[0], mode, args.dry_run, only_keys)
        return

    groups, update_results, scanned_ok = scan_tickets(
        load_issue_keys(args, parser), client, id_name, mode
    )
    update_list = groups["update"]
    scanned = sum(len(g) for g in groups.values())
    skipped = len(groups["skipped"])

    print_report(groups, mode)

    empty_note = ""
    if mode == "complexity":
        empty_count = sum(1 for u in update_list if u.get("complexity_missing"))
        empty_note = f" ({empty_count} with empty Complexity)"

    log(
        f"\nScanned {scanned} ticket(s): {len(update_list)} need update{empty_note}, "
        f"{scanned - len(update_list) - skipped} no change, {skipped} skipped"
    )

    if not args.no_save:
        save_scan(update_list, update_results, scanned_ok, mode, files)


if __name__ == "__main__":
    main()
