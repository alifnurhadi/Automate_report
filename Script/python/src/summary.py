import concurrent.futures
import json
import os
import sys
from collections import defaultdict

from jira.exceptions import JIRAError

from read_jira_v2 import jira_access, createArgs, load_issue_keys

FIELD_NAME = "Group AdHoc"
NO_GROUP = "Tanpa Group"
TODO_FILE = "manual_group_todo.json"


def read_value(val):
    """Jira custom field can be str, dict, or list. Make it plain text."""
    if val in (None, "", [], {}):
        return None
    if isinstance(val, dict):
        return val.get("value") or val.get("name") or str(val)
    if isinstance(val, list):
        return ", ".join(filter(None, (read_value(v) for v in val))) or None
    return str(val)


def load_manual(path):
    """manual file: {"ERA23-123": "Rekening Koran", ...}. empty value = skip."""
    if not path:
        return {}
    if not os.path.exists(path):
        sys.exit(f"Manual file not found: {path}")
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    return {k.strip().upper(): v.strip() for k, v in data.items() if v and v.strip()}


def num(key):
    tail = key.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def main():
    parser = createArgs()
    parser.add_argument("--secret", required=True, help="Path to secret.json")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--manual", help="JSON file with manual group {key: group}")
    args = parser.parse_args()

    issues = load_issue_keys(args, parser)
    manual = load_manual(args.manual)
    jira, id_toname = jira_access(args.secret)

    name_to_id = {name: fid for fid, name in id_toname.items()}
    field_id = name_to_id.get(FIELD_NAME)
    if not field_id:
        sys.exit(f"Field '{FIELD_NAME}' not found in Jira")

    print(f"Fetch {len(issues)} ticket | field {FIELD_NAME} = {field_id} | manual {len(manual)}",
          file=sys.stderr)

    def func(key):
        try:
            issue = jira.issue(key, fields=f"{field_id},summary")
            f = issue.raw["fields"]
            return key, read_value(f.get(field_id)), f.get("summary", ""), None
        except JIRAError as e:
            return key, None, "", f"{e.status_code}: {e.text}"
        except Exception as e:
            return key, None, "", str(e)

    groups = defaultdict(list)
    ungrouped = {}   # key -> summary
    failed = {}      # key -> error

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        ftr = [ex.submit(func, key) for key in issues]
        for done, f in enumerate(concurrent.futures.as_completed(ftr), 1):
            key, group, summary, err = f.result()
            tag = f"[{done}/{len(issues)}]"

            if key in manual:                       # manual win
                groups[manual[key]].append(key)
                print(f"{tag} MAN  {key} -> {manual[key]}", file=sys.stderr)
            elif err:
                failed[key] = err
                print(f"{tag} FAIL {key} | {err}", file=sys.stderr)
            elif group:
                groups[group].append(key)
                print(f"{tag} OK   {key} -> {group}", file=sys.stderr)
            else:
                ungrouped[key] = summary
                print(f"{tag} NONE {key}", file=sys.stderr)

    os.makedirs(args.out, exist_ok=True)

    # result
    result = {g: sorted(keys, key=num) for g, keys in sorted(groups.items())}
    res_path = os.path.join(args.out, "hasil_group.json")
    with open(res_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # count
    print("\nJumlah:", file=sys.stderr)
    for g, keys in result.items():
        print(f"  {g}: {len(keys)}", file=sys.stderr)
    print(f"  {NO_GROUP}: {len(ungrouped)} | Gagal: {len(failed)}", file=sys.stderr)

    # todo for manual
    todo_keys = sorted({**ungrouped, **failed}, key=num)
    if not todo_keys:
        print(f"\nAll ticket grouped. Saved: {res_path}", file=sys.stderr)
        return

    print(f"\nTicket NOT in any group ({len(todo_keys)}):", file=sys.stderr)
    for k in todo_keys:
        why = f"FAIL {failed[k][:60]}" if k in failed else (ungrouped[k] or "")[:60]
        print(f"  - {k:<12} {why}", file=sys.stderr)

    todo_path = os.path.join(args.out, TODO_FILE)
    # keep old manual value, add new empty slot
    todo = {k: manual.get(k, "") for k in todo_keys}
    with open(todo_path, "w", encoding="utf-8") as fh:
        json.dump(todo, fh, indent=2, ensure_ascii=False)

    abs_todo = os.path.abspath(todo_path)
    print(
        f"\nFill group by hand here:\n  {abs_todo}\n"
        f"Value example: \"Rekening Koran\", \"Critical Report\", \"Lain-lain\"\n"
        f"Then run again with:\n  --manual \"{abs_todo}\"",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
