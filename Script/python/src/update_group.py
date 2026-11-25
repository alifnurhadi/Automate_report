import argparse
import concurrent.futures
import json
import os
import sys

from jira.exceptions import JIRAError

from read_jira_v2 import jira_access

FIELD_NAME = "Group AdHoc"


def load_manual(path):
    if not os.path.exists(path):
        sys.exit(f"Manual file not found: {path}")
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    # skip blank value
    return {k.strip().upper(): v.strip() for k, v in data.items() if v and v.strip()}


def main():
    p = argparse.ArgumentParser(description="Update Group AdHoc in Jira from manual JSON.")
    p.add_argument("--manual", required=True, help="JSON {key: group}")
    p.add_argument("--secret", required=True, help="Path to secret.json")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--apply", action="store_true", help="Really write. Without it = dry run")
    p.add_argument("--force", action="store_true", help="Overwrite even if Jira already has value")
    args = p.parse_args()

    manual = load_manual(args.manual)
    if not manual:
        sys.exit("Manual file has no filled value.")

    jira, id_toname = jira_access(args.secret)
    name_to_id = {name: fid for fid, name in id_toname.items()}
    field_id = name_to_id.get(FIELD_NAME)
    if not field_id:
        sys.exit(f"Field '{FIELD_NAME}' not found")

    # field type: option (select list) or plain text
    # field type: array of option (multi-select), option (single), or text
    schema = next((f.get("schema", {}) for f in jira.fields() if f["id"] == field_id), {})
    ftype = schema.get("type")          # "array" / "option" / "string"
    item = schema.get("items")          # for array: "option" or "string"
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"{mode} | {len(manual)} ticket | {FIELD_NAME}={field_id} | type={ftype}/{item}",
          file=sys.stderr)

    def to_text(val):
        """read current value, any shape -> list of text"""
        if not val:
            return []
        if isinstance(val, dict):
            return [val.get("value") or val.get("name") or ""]
        if isinstance(val, list):
            return [t for v in val for t in to_text(v)]
        return [str(val)]

    def work(key, want):
        try:
            issue = jira.issue(key, fields=field_id)
            cur = to_text(issue.raw["fields"].get(field_id))
            cur_low = [c.lower() for c in cur]

            if want.lower() in cur_low and len(cur) == 1:
                return key, "SAME", cur[0]
            if cur and not args.force:
                return key, "SKIP", f"Jira={cur} manual='{want}' (use --force)"

            # option field: match Jira allowed value
            real = want
            if ftype == "option" or item == "option":
                meta = jira.editmeta(key)["fields"].get(field_id)
                if meta is None:
                    return key, "FAIL", "field not editable (status/screen lock?)"
                allowed = {o["value"].lower(): o["value"] for o in meta.get("allowedValues", [])}
                real = allowed.get(want.lower())
                if not real:
                    return key, "FAIL", f"'{want}' not allowed. Allowed: {list(allowed.values())}"

            # build payload per type
            if ftype == "array" and item == "option":
                payload = {field_id: [{"value": real}]}
            elif ftype == "array":                 # labels / text list
                payload = {field_id: [real]}
            elif ftype == "option":
                payload = {field_id: {"value": real}}
            else:
                payload = {field_id: real}

            if not args.apply:
                return key, "PLAN", f"{cur or '-'} -> {payload[field_id]}"

            issue.update(fields=payload)
            return key, "DONE", f"{cur or '-'} -> '{real}'"

        except JIRAError as e:
            return key, "FAIL", f"{e.status_code}: {e.text or e.response.text}"
        except Exception as e:
            return key, "FAIL", f"{type(e).__name__}: {e}"


    count = {}
    fails = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        ftr = [ex.submit(work, k, v) for k, v in manual.items()]
        for i, f in enumerate(concurrent.futures.as_completed(ftr), 1):
            key, status, msg = f.result()
            count[status] = count.get(status, 0) + 1
            if status == "FAIL":
                fails[key] = msg
            print(f"[{i}/{len(manual)}] {status:<4} {key:<12} {msg}", file=sys.stderr)

    print("\nRingkasan:", file=sys.stderr)
    for s in ("PLAN", "DONE", "SAME", "SKIP", "FAIL"):
        if s in count:
            print(f"  {s}: {count[s]}", file=sys.stderr)

    if fails:
        out = os.path.join(os.path.dirname(os.path.abspath(args.manual)), "update_failed.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(fails, fh, indent=2, ensure_ascii=False)
        print(f"\nFail list: {out}", file=sys.stderr)

    if not args.apply:
        print("\nDry run only. Add --apply to write.", file=sys.stderr)


if __name__ == "__main__":
    main()
