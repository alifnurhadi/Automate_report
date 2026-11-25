import concurrent.futures
import json
import re
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent
for _p in (_SRC, _SRC.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from datetime import datetime
from pathlib import Path

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
    check_complexity_logic,
    extract_all_strings,
    format_calculation,
)
from utils.parser import parse_json, simplify

SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent / "jira_snapshots"
EDITABLE_FIELDS_PATH = Path(__file__).resolve().parents[1] / "jira_editable_field.json"
EMPTY_COMPLEXITY_OK_CATEGORIES = {"lain-lain"}

JIRA_FIELD_PATH = r'C:\Users\Iykra03\Documents\Iykra_alif\Script\python\jira_editable_field.json'

def log(*args):
    print(*args, file=sys.stderr)


def _norm(value) -> str:
    return str(value).strip().lower()


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


def _field_is_empty(filled: dict, field_name: str) -> bool:
    return not any(_norm(name) == _norm(field_name) for name in filled)


def pending_entry(res: dict, mode: str) -> dict:
    entry = {"ticket": res["ticket"]}
    entry.update({k: res.get(k) for k in TARGET_FIELDS[mode]["entry_keys"]})
    if mode == "complexity":
        entry["complexity_missing"] = bool(res.get("complexity_missing"))
    return entry


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


def _log_apply_error(key: str, exc: Exception):
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(SNAPSHOTS_DIR / "apply_errors.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now()} | {key} | {type(exc).__name__}: {exc}\n")


def inspect_field(client, ticket_keys: list[str], field_id: str):
    """Debug helper: show type / value / editability of one field per ticket."""
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

    if only_keys is not None:
        in_file = {item["ticket"] for item in tickets}
        for missing in sorted(only_keys - in_file, key=_ticket_sort_key):
            print(f"[SKIP] {missing} (not in pending file)")
        tickets = [t for t in tickets if t["ticket"] in only_keys]

    cfg = TARGET_FIELDS[target_mode]
    counts = {"updated": 0, "skipped": 0, "would_update": 0}

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
            _log_apply_error(key, e)
            print(f"[SKIP] {key} (see apply_errors.log)")
            counts["skipped"] += 1

    summary = f"{counts['updated']} updated, {counts['skipped']} skipped"
    if dry_run:
        summary = f"{counts['would_update']} would update, {counts['skipped']} skipped (dry run)"
    log(f"\nApply finished: {summary}")


# ---------- scan ----------

def process_single_ticket(ticket_key: str, client, id_name: dict, mode: str) -> dict:
    """Fetch ticket and evaluate category or complexity logic."""
    try:
        filled = build_filled_fields(client.issue(ticket_key), id_name)
        parsed = parse_json({"key": ticket_key, "filled_fields": filled} , JIRA_FIELD_PATH)

        if mode != "complexity":
            return check_logic(parsed)

        result = check_complexity_logic(parsed)
        empty = _field_is_empty(filled, TARGET_FIELDS["complexity"]["jira_name"])
        category = _norm(result.get("category") or "")
        result["complexity_empty"] = empty
        result["complexity_missing"] = empty and category not in EMPTY_COMPLEXITY_OK_CATEGORIES
        return result

    except Exception as e:
        import traceback; traceback.print_exc()   # TEMP: remove after debugging
        return {
            "ticket": ticket_key,
            "status": "error",
            "needs_update": False,
            "error": type(e).__name__,
        }


def scan_tickets(ticket_keys, client, id_name, mode):
    update_list, update_results, scanned_ok = [], [], set()
    scanned = skipped = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(process_single_ticket, key, client, id_name, mode)
            for key in ticket_keys
        ]

        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            scanned += 1

            if res.get("status") == "error":
                print(f"[SKIP] {res['ticket']} ({res.get('error')})")
                skipped += 1
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
                update_list.append(pending_entry(res, mode))

    return update_list, update_results, scanned_ok, scanned, skipped


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

    update_list, update_results, scanned_ok, scanned, skipped = scan_tickets(
        load_issue_keys(args, parser), client, id_name, mode
    )

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
