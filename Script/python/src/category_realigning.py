# import concurrent.futures
# import json
# from pathlib import Path
# import sys
#
# from read_jira_v2 import (
#     build_filled_fields,
#     jira_access,
#     load_issue_keys,
#     parse_args,
#     write_output,
# )
# from utils.mapped_data import SECRET_PATH, MAX_WORKERS, check_logic
# from utils.parser import parse_json
#
# PENDING_UPDATES_FILE = Path(__file__).resolve().parent.parent / "jira_snapshots" / "tickets_to_update.json"
#
#
# def apply_changes(client, pending_file: Path = PENDING_UPDATES_FILE):
#     """Apply saved pending ticket category updates directly to Jira."""
#     if not pending_file.exists():
#         print(f"No pending updates file found at {pending_file}", file=sys.stderr)
#         return
#
#     with open(pending_file, "r", encoding="utf-8") as f:
#         tickets_to_update = json.load(f)
#
#     for item in tickets_to_update:
#         ticket_key = item["ticket"]
#         new_adhoc = item["suggested_group_adhoc"]
#         try:
#             issue = client.issue(ticket_key)
#             print(f"[SUCCESS] Updated {ticket_key} -> '{new_adhoc}'")
#         except Exception as e:
#             print(f"[ERROR] Failed to update {ticket_key}: {e}", file=sys.stderr)
#
#
# def process_single_ticket(ticket_key: str, client, id_name: dict) -> dict:
#     """Fetch ticket fields, parse json structure, and evaluate category logic."""
#     try:
#         ticket = client.issue(ticket_key)
#         filled = build_filled_fields(ticket, id_name)
#         parsed = parse_json({"key": ticket_key, "filled_fields": filled})
#         return check_logic(parsed)
#     except Exception as e:
#         return {
#             "ticket": ticket_key,
#             "old_group_adhoc": "ERROR",
#             "suggested_group_adhoc": f"Error: {e}",
#             "status": "error",
#             "needs_update": False
#         }
#
#
# def main():
#     args_val, parser = parse_args()
#
#     parser.add_argument("--apply", action="store_true", help="Apply saved updates to Jira")
#     args_val = parser.parse_args()
#
#     client, id_name = jira_access(SECRET_PATH)
#
#     if getattr(args_val, "apply", False):
#         apply_changes(client)
#         return
#
#     ticket_keys = load_issue_keys(args_val, parser)
#
#     update_list = []
#     with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
#         futures = {
#             executor.submit(process_single_ticket, key, client, id_name): key
#             for key in ticket_keys
#         }
#         for future in concurrent.futures.as_completed(futures):
#             res = future.result()
#             print(f"Ticket: {res['ticket']} | Old AdHoc: '{res['old_group_adhoc']}' | Suggested: '{res['suggested_group_adhoc']}' | Status: {res['status']}")
#
#             if res.get("needs_update"):
#                 update_list.append({
#                     "ticket": res["ticket"],
#                     "old_group_adhoc": res["old_group_adhoc"],
#                     "suggested_group_adhoc": res["suggested_group_adhoc"]
#                 })
#
#     if update_list and not args_val.no_save:
#         PENDING_UPDATES_FILE.parent.mkdir(parents=True, exist_ok=True)
#         with open(PENDING_UPDATES_FILE, "w", encoding="utf-8") as f:
#             json.dump(update_list, f, indent=4, ensure_ascii=False)
#         print(f"\nSaved {len(update_list)} tickets requiring update to: {PENDING_UPDATES_FILE}", file=sys.stderr)
#
#
# if __name__ == "__main__":
#     main()

import concurrent.futures
from datetime import datetime
import json
from pathlib import Path
import re
import sys

from read_jira_v2 import (
    build_filled_fields,
    jira_access,
    load_issue_keys,
    parse_args,
    write_output,
)
from utils.mapped_data import SECRET_PATH, MAX_WORKERS, check_logic, format_calculation
from utils.parser import parse_json

PENDING_UPDATES_FILE = Path(__file__).resolve().parent.parent / "jira_snapshots" / "tickets_to_update.json"
# History of every run's "needs update" tickets. Separate from the JSON above:
# apply_changes() reads only the JSON, and nothing ever reads this log.
UPDATE_LOG_FILE = PENDING_UPDATES_FILE.parent / "tickets_to_update_log.txt"
# Only the keys that need an update, separated by a single space, so the whole
# file can be passed to this script as CLI arguments. Overwritten on every run.
UPDATE_KEYS_FILE = PENDING_UPDATES_FILE.parent / "tickets_to_update_keys.txt"


def _ticket_sort_key(key: str):
    """Natural order so ERA-2 comes before ERA-10."""
    m = re.match(r"^(.*?)(\d+)$", key)
    return (m.group(1), int(m.group(2))) if m else (key, 0)


def write_update_keys(results: list[dict], keys_file: Path):
    """Write the keys that need an update, space-separated, for use as CLI arguments."""
    keys_file.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted((r["ticket"] for r in results), key=_ticket_sort_key)
    keys_file.write_text(" ".join(keys) + "\n", encoding="utf-8")
    print(f"Wrote {len(keys)} key(s) for CLI use to: {keys_file}", file=sys.stderr)


def append_update_log(results: list[dict], log_file: Path):
    """Append this run's tickets that need an update to a plain-text log.

    Each run adds a timestamped header, then one calculation block per ticket
    (matched rows, totals and the final SUMMARY line). Existing content is kept.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"##### Run {stamp} | {len(results)} ticket(s) need update #####\n\n")
        for res in sorted(results, key=lambda r: _ticket_sort_key(r["ticket"])):
            f.write(format_calculation(res) + "\n\n")
    print(f"Appended {len(results)} ticket(s) to log: {log_file}", file=sys.stderr)


def apply_changes(client, pending_file: Path = PENDING_UPDATES_FILE):
    """Apply saved pending ticket category updates directly to Jira."""
    if not pending_file.exists():
        print(f"No pending updates file found at {pending_file}", file=sys.stderr)
        return

    with open(pending_file, "r", encoding="utf-8") as f:
        tickets_to_update = json.load(f)

    for item in tickets_to_update:
        ticket_key = item["ticket"]
        new_adhoc = item["suggested_group_adhoc"]
        try:
            issue = client.issue(ticket_key)
            print(f"[SUCCESS] Updated {ticket_key} -> '{new_adhoc}'")
        except Exception as e:
            print(f"[ERROR] Failed to update {ticket_key}: {e}", file=sys.stderr)


def process_single_ticket(ticket_key: str, client, id_name: dict) -> dict:
    """Fetch ticket fields, parse json structure, and evaluate category logic."""
    try:
        ticket = client.issue(ticket_key)
        filled = build_filled_fields(ticket, id_name)
        parsed = parse_json({"key": ticket_key, "filled_fields": filled})
        return check_logic(parsed)
    except Exception as e:
        return {
            "ticket": ticket_key,
            "old_group_adhoc": "ERROR",
            "suggested_group_adhoc": f"Error: {e}",
            "status": "error",
            "needs_update": False
        }


def main():
    args_val, parser = parse_args()

    parser.add_argument("--apply", action="store_true", help="Apply saved updates to Jira")
    args_val = parser.parse_args()

    client, id_name = jira_access(SECRET_PATH)

    if getattr(args_val, "apply", False):
        apply_changes(client)
        return

    ticket_keys = load_issue_keys(args_val, parser)

    update_list = []
    update_results = []  # full results (with calculation) for the txt log
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_single_ticket, key, client, id_name): key
            for key in ticket_keys
        }
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            # Show the per-field calculation first; the summary is its last line.
            print(format_calculation(res))
            print()

            if res.get("needs_update"):
                update_results.append(res)
                update_list.append({
                    "ticket": res["ticket"],
                    "old_group_adhoc": res["old_group_adhoc"],
                    "suggested_group_adhoc": res["suggested_group_adhoc"],
                    "category_totals": res.get("category_totals"),
                    "decision_summary": res.get("decision_summary"),
                })

    if update_list and not args_val.no_save:
        PENDING_UPDATES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PENDING_UPDATES_FILE, "w", encoding="utf-8") as f:
            json.dump(update_list, f, indent=4, ensure_ascii=False)
        print(f"\nSaved {len(update_list)} tickets requiring update to: {PENDING_UPDATES_FILE}", file=sys.stderr)
        append_update_log(update_results, UPDATE_LOG_FILE)
        write_update_keys(update_results, UPDATE_KEYS_FILE)


if __name__ == "__main__":
    main()
