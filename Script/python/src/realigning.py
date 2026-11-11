
from collections import Counter
import concurrent.futures
from datetime import datetime
import difflib
import json
from pathlib import Path
import re
import sys

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

EDITABLE_FIELDS_PATH = (
    Path(__file__).resolve().parents[1]
    / "jira_editable_field.json"
)





EMPTY_COMPLEXITY_OK_CATEGORIES = {"lain-lain"}

def load_editable_fields():
    with EDITABLE_FIELDS_PATH.open("r", encoding="utf-8") as f:
        fields = json.load(f)

    if not isinstance(fields, dict):
        raise ValueError("jira_editable_field.json must contain a JSON object")

    return fields


def _field_is_empty(filled: dict, field_name: str) -> bool:
    wanted = field_name.strip().lower()
    return not any(str(name).strip().lower() == wanted for name in filled)


def _ticket_sort_key(key: str):
    """Natural order so ERA-2 comes before ERA-10."""
    m = re.match(r"^(.*?)(\d+)$", key)
    return (m.group(1), int(m.group(2))) if m else (key, 0)


def write_update_keys(results: list[dict], keys_file: Path):
    """Write the keys that need an update, space-separated."""
    keys_file.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted(
        (r["ticket"] for r in results),
        key=_ticket_sort_key,
    )
    keys_file.write_text(" ".join(keys) + "\n", encoding="utf-8")
    print(
        f"Wrote {len(keys)} key(s) for CLI use to: {keys_file}",
        file=sys.stderr,
    )


def merge_pending(
    pending_file: Path,
    update_list: list[dict],
    scanned_ok: set,
):
    existing = []

    if pending_file.exists():
        try:
            existing = json.loads(
                pending_file.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            print(
                "Could not read existing pending file; using this scan only.",
                file=sys.stderr,
            )

        if not isinstance(existing, list):
            existing = []

    fresh = {item["ticket"] for item in update_list}

    kept = [
        item for item in existing
        if item.get("ticket") not in scanned_ok
    ]

    removed = [
        item for item in existing
        if item.get("ticket") in scanned_ok
        and item.get("ticket") not in fresh
    ]

    merged = sorted(
        kept + update_list,
        key=lambda item: _ticket_sort_key(item["ticket"]),
    )

    return merged, existing, len(kept), len(removed)


def append_update_log(
    results: list[dict],
    log_file: Path,
    mode: str = "category",
):
    """Append tickets that need an update to a text log."""
    log_file.parent.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(
            f"##### Run {stamp} [{mode}] | "
            f"{len(results)} ticket(s) need update #####\n\n"
        )

        for res in sorted(
            results,
            key=lambda r: _ticket_sort_key(r["ticket"]),
        ):
            if mode == "complexity":
                note = (
                    "NOTE: Complexity field is empty\n"
                    if res.get("complexity_missing")
                    else ""
                )
                f.write(
                    f"=== {res['ticket']} ===\n"
                    f"{note}"
                    f"SUMMARY: {res.get('decision_summary')}\n\n"
                )
            else:
                f.write(format_calculation(res) + "\n\n")

    print(
        f"Appended {len(results)} ticket(s) to log: {log_file}",
        file=sys.stderr,
    )


def find_editable_field(client, ticket_key: str, field_name: str):
    field_id = EDITABLE_FIELDS.get(field_name)

    if not field_id:
        raise LookupError(
            f"Field '{field_name}' not found in {EDITABLE_FIELDS_PATH}"
        )

    editable_fields = client.editmeta(ticket_key).get("fields", {})
    info = editable_fields.get(field_id)

    if not info:
        raise LookupError(
            f"Field '{field_name}' ({field_id}) is not editable on {ticket_key}"
        )

    return field_id, info

def test_editable_field(client, ticket_key: str, field_name: str):
    field_id = EDITABLE_FIELDS.get(field_name)

    if not field_id:
        print(f"[NOT FOUND] {field_name} is missing from JSON mapping")
        return

    editable_fields = client.editmeta(ticket_key).get("fields", {})
    info = editable_fields.get(field_id)

    if info:
        print(f"\n[EDITABLE] {field_name} -> {field_id}")
        print(f"Field type: {info.get('schema', {}).get('type')}")
        print(f"Allowed values: {info.get('allowedValues', [])}")
    else:
        print(f"\n[NOT EDITABLE] {field_name} -> {field_id}")

def discover_jira_field(client, field_name: str):
    wanted = field_name.strip().lower()

    matches = [
        field
        for field in client.fields()
        if (field.get("name") or "").strip().lower() == wanted
    ]

    if not matches:
        print(f"[NOT FOUND] '{field_name}' does not exist in Jira's global field registry.")
        return []

    print(f"\n[GLOBAL FIELD MATCHES] {field_name}")

    for field in matches:
        print(f"Name: {field.get('name')}")
        print(f"ID:   {field.get('id')}")
        print(f"Type: {field.get('schema', {}).get('type')}")
        print("-" * 35)

    return matches

def inspect_complexity_fields(client, ticket_key):
    issue = client.issue(ticket_key)
    raw_fields = issue.raw.get("fields", {})

    print(f"\n[INSPECT] {ticket_key}")

    for field_id in ["customfield_23257", "customfield_22134"]:
        value = raw_fields.get(field_id)

        print(f"\nField ID: {field_id}")
        print(f"Current value: {value}")

        try:
            field_info = next(
                f for f in client.fields()
                if f.get("id") == field_id
            )
            print(f"Field name: {field_info.get('name')}")
            print(f"Schema: {field_info.get('schema')}")
        except StopIteration:
            print("Field metadata not found")

def build_field_payload(info: dict, value: str):
    """Convert suggested text into Jira's expected field payload."""
    schema = info.get("schema") or {}
    ftype = schema.get("type")
    items = schema.get("items")
    allowed = info.get("allowedValues") or []

    match = None

    for opt in allowed:
        label = opt.get("value") or opt.get("name")

        if (
            label is not None
            and str(label).strip().lower() == str(value).strip().lower()
        ):
            match = opt
            break

    if allowed and match is None:
        raise ValueError("Value is not an allowed option")

    option = (
        {"id": match["id"]}
        if match and "id" in match
        else {"value": value}
    )

    if ftype == "array":
        return [value] if items == "string" else [option]

    if ftype in ("option", "option-with-child"):
        return option

    if ftype == "string":
        return value

    raise ValueError(f"Unsupported field type: {ftype}")


def _current_values(issue, field_id: str) -> list[str]:
    """Return current field values in lowercase."""
    raw = issue.raw["fields"].get(field_id)
    return [
        s.lower()
        for s in extract_all_strings(simplify(raw))
    ]


def apply_changes(
    client,
    pending_file: Path,
    target_mode: str,
    dry_run: bool,
    only_keys: set = None,
):
    """Apply pending Jira updates and verify each update."""

    if dry_run:
        print(
            f"*** DRY RUN [{target_mode}]: nothing will be written to Jira ***"
        )

    if not pending_file.exists():
        print(
            f"No pending updates file found at {pending_file}",
            file=sys.stderr,
        )
        return

    with open(pending_file, "r", encoding="utf-8") as f:
        tickets_to_update = json.load(f)

    if only_keys is not None:
        in_file = {item["ticket"] for item in tickets_to_update}

        for missing in sorted(
            only_keys - in_file,
            key=_ticket_sort_key,
        ):
            print(f"[SKIP] {missing}")

        tickets_to_update = [
            item for item in tickets_to_update
            if item["ticket"] in only_keys
        ]

    cfg = TARGET_FIELDS[target_mode]
    counts = {"updated": 0, "skipped": 0}

    for item in tickets_to_update:
        key = item["ticket"]
        new_val = item.get(cfg["json_key"])

        try:
            if not new_val:
                raise ValueError("Missing suggested value")

            issue = client.issue(key)

            field_id, info = find_editable_field(
                client,
                key,
                cfg["jira_name"],
            )

            current = _current_values(issue, field_id)

            if current == [new_val.strip().lower()]:
                print(
                    f"[SKIP] {key}: "
                    f"{cfg['jira_name']} already correct"
                )
                counts["skipped"] += 1
                continue

            payload = build_field_payload(info, new_val)
            before = current or "(empty)"

            if dry_run:
                print(
                    f"[DRY-RUN] {key}: {before} -> {payload}"
                )
                continue

            issue.update(fields={field_id: payload})

            after = _current_values(
                client.issue(key),
                field_id,
            )

            if new_val.strip().lower() not in after:
                raise RuntimeError("Update verification failed")

            print(
                f"[SUCCESS] {key}: {cfg['jira_name']} "
                f"{before} -> '{new_val}'"
            )

            counts["updated"] += 1

        except Exception as e:
            error_log = SNAPSHOTS_DIR / "apply_errors.log"

            with open(error_log, "a", encoding="utf-8") as f:
                f.write(
                    f"{datetime.now()} | {key} | "
                    f"{type(e).__name__}: {e}\n"
                )

            print(f"[SKIP] {key}")
            counts["skipped"] += 1

    mode = " (dry run, nothing written)" if dry_run else ""

    print(
        f"\nApply finished{mode}: "
        f"{counts['updated']} updated, "
        f"{counts['skipped']} skipped",
        file=sys.stderr,
    )

def test_complexity_update(client, ticket_key: str, new_value: str = "Simple"):
    FIELD_ID = "customfield_23257"

    print(f"\n[TEST UPDATE] {ticket_key}")
    print(f"Field: Complexity ({FIELD_ID})")
    print(f"New value: {new_value}")

    try:
        # Read current value
        issue = client.issue(ticket_key)
        current = issue.raw.get("fields", {}).get(FIELD_ID)

        print(f"[BEFORE] {current}")

        # Safety check: only update an empty field
        if current is not None:
            print("[ABORT] Complexity is not empty. No changes made.")
            return False

        # Update Jira single-select field
        issue.update(
            fields={
                FIELD_ID: {"value": new_value}
            }
        )

        print("[UPDATE REQUEST] Submitted successfully.")

        # Fetch again to verify
        updated_issue = client.issue(ticket_key)
        updated_value = (
            updated_issue.raw.get("fields", {}).get(FIELD_ID)
        )

        actual_value = (
            updated_value.get("value")
            if isinstance(updated_value, dict)
            else updated_value
        )

        print(f"[AFTER] {updated_value}")

        if actual_value == new_value:
            print(f"[SUCCESS] Complexity updated to '{new_value}'.")
            return True

        print("[WARNING] Update submitted, but verification did not match.")
        return False

    except Exception as exc:
        print(f"[FAILED] Jira update failed: {exc}")
        return False

def process_single_ticket(
    ticket_key: str,
    client,
    id_name: dict,
    mode: str = "category",
) -> dict:
    """Fetch ticket and evaluate category or complexity logic."""

    try:
        ticket = client.issue(ticket_key)

        filled = build_filled_fields(ticket, id_name)

        parsed = parse_json({
            "key": ticket_key,
            "filled_fields": filled,
        })

        if mode == "complexity":
            result = check_complexity_logic(parsed)

            result["complexity_empty"] = _field_is_empty(
                filled,
                TARGET_FIELDS["complexity"]["jira_name"],
            )

            category = str(
                result.get("category") or ""
            ).strip().lower()

            result["complexity_missing"] = (
                result["complexity_empty"]
                and category not in EMPTY_COMPLEXITY_OK_CATEGORIES
            )

            return result

        return check_logic(parsed)

    except Exception:
        # Do not return or expose exception details.
        return {
            "ticket": ticket_key,
            "status": "error",
            "needs_update": False,
        }



EDITABLE_FIELDS = load_editable_fields()
TARGET_FIELDS = {
    "category": {
        "jira_name": "Group AdHoc",
        "field_id": EDITABLE_FIELDS.get("Group AdHoc"),
        "json_key": "suggested_group_adhoc",
    },
    "complexity": {
        "jira_name": "Complexity",
        "field_id": EDITABLE_FIELDS.get("Complexity"),
        "json_key": "suggested_complexity",
    },
}
def main():

    parser = parse_args()

    parser.add_argument(
        "--target",
        choices=["category", "complexity"],
        default="category",
        help="Target realigning mode: category or complexity",
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply saved updates to Jira",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --apply: show what would be written",
    )

    args_val = parser.parse_args()

    target_mode = getattr(args_val, "target", "category")

    pending_file = (
        SNAPSHOTS_DIR / f"tickets_to_update_{target_mode}.json"
    )

    update_log_file = (
        SNAPSHOTS_DIR / f"tickets_to_update_{target_mode}_log.txt"
    )

    update_keys_file = (
        SNAPSHOTS_DIR / f"tickets_to_update_{target_mode}_keys.txt"
    )

    client, id_name = jira_access(SECRET_PATH)

    if args_val.apply:
        only_keys = (
            set(load_issue_keys(args_val, parser))
            if (args_val.issue_key or args_val.file)
            else None
        )

        apply_changes(
            client,
            pending_file,
            target_mode,
            args_val.dry_run,
            only_keys,
        )
        return

    ticket_keys = load_issue_keys(args_val, parser)

    update_list = []
    update_results = []

    scanned = 0
    scanned_ok = set()
    skipped_count = 0

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                process_single_ticket,
                key,
                client,
                id_name,
                target_mode,
            ): key
            for key in ticket_keys
        }

        for future in concurrent.futures.as_completed(futures):

            res = future.result()
            scanned += 1

            if res.get("status") == "error":
                print(f"[SKIP] {res['ticket']}")
                skipped_count += 1
                continue

            scanned_ok.add(res["ticket"])

            if target_mode == "complexity":
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

                if target_mode == "complexity":
                    update_list.append({
                        "ticket": res["ticket"],
                        "old_complexity": res.get("old_complexity"),
                        "suggested_complexity": res.get("suggested_complexity"),
                        "category": res.get("category"),
                        "complexity_missing": bool(
                            res.get("complexity_missing")
                        ),
                        "decision_summary": res.get("decision_summary"),
                    })

                else:
                    update_list.append({
                        "ticket": res["ticket"],
                        "old_group_adhoc": res["old_group_adhoc"],
                        "suggested_group_adhoc": res["suggested_group_adhoc"],
                        "category_totals": res.get("category_totals"),
                        "decision_summary": res.get("decision_summary"),
                    })

    empty_count = sum(
        1 for u in update_list
        if u.get("complexity_missing")
    )

    empty_note = (
        f" ({empty_count} with empty Complexity)"
        if target_mode == "complexity"
        else ""
    )

    no_change = scanned - len(update_list) - skipped_count

    print(
        f"\nScanned {scanned} ticket(s): "
        f"{len(update_list)} need update{empty_note}, "
        f"{no_change} no change, "
        f"{skipped_count} skipped",
        file=sys.stderr,
    )

    if not args_val.no_save:

        merged, existing, kept, removed = merge_pending(
            pending_file,
            update_list,
            scanned_ok,
        )

        changed = merged != existing

        if changed:
            SNAPSHOTS_DIR.mkdir(
                parents=True,
                exist_ok=True,
            )

            with open(
                pending_file,
                "w",
                encoding="utf-8",
            ) as f:
                json.dump(
                    merged,
                    f,
                    indent=4,
                    ensure_ascii=False,
                )

            print(
                f"\nPending file updated: {len(merged)} "
                f"[{target_mode}] ticket(s) now pending "
                f"({len(update_list)} from this scan, "
                f"{kept} kept from earlier scans, "
                f"{removed} removed): {pending_file}",
                file=sys.stderr,
            )

        elif merged or pending_file.exists():
            print(
                f"\nPending file unchanged: {len(merged)} "
                f"[{target_mode}] ticket(s) pending: {pending_file}",
                file=sys.stderr,
            )

        else:
            print(
                "\nNo ticket needs an update and there is no pending file.",
                file=sys.stderr,
            )

        if update_results:
            append_update_log(
                update_results,
                update_log_file,
                mode=target_mode,
            )

        if changed or (
            merged and not update_keys_file.exists()
        ):
            write_update_keys(
                merged,
                update_keys_file,
            )

tickets = ['ERA25-27','ERA25-498','ERA25-41','ERA25-42','ERA25-77','ERA25-82','ERA25-113','ERA25-116']


if __name__ == "__main__":
    client, id_name = jira_access(SECRET_PATH)
    def inspect_complexity_bulk(client, ticket_keys):
        field_id = "customfield_23257"

        for key in ticket_keys:
            try:
                issue = client.issue(key)
                fields = issue.raw.get("fields", {})

                editmeta = client.editmeta(key).get("fields", {})

                issue_type = fields.get("issuetype", {}).get("name")
                current = fields.get(field_id)

                print(
                    f"{key} | "
                    f"Type: {issue_type} | "
                    f"Value: {current} | "
                    f"Editable: {field_id in editmeta}"
                )

            except Exception as exc:
                print(f"{key} | ERROR: {exc}")


    inspect_complexity_bulk(
        client,
        tickets
)
    print('ERA26')
    inspect_complexity_bulk(
        client,
        [
            "ERA26-625",
            "ERA26-487",
            "ERA26-500",
            "ERA26-501",
        ]
    )

    # test_complexity_update(
    #     client=client,
    #     ticket_key="ERA25-498",
    #     new_value="Simple",
    # )

# if __name__ == "__main__":

#     client, id_name = jira_access(SECRET_PATH)
#
#     test_editable_field(client, "ERA25-498", "Group AdHoc")
#     test_editable_field(client, "ERA25-498", "Complexity")
#
#     print(f"Mapping file: {EDITABLE_FIELDS_PATH}")
#     print(f"Total mapped fields: {len(EDITABLE_FIELDS)}")
#
#     for name, field_id in EDITABLE_FIELDS.items():
#         print(f"{name:<35} -> {field_id}")
#
#     print("\n[TEST] Group AdHoc:")
#     print(EDITABLE_FIELDS.get("Group AdHoc"))
#
#     print("\n[TEST] Complexity:")
#     print(EDITABLE_FIELDS.get("Complexity", "NOT FOUND"))
    # main()
