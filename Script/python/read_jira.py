"""
Fetch Jira tickets and save a snapshot of what's available on them.

Usage:
  python jira_read.py ERA26-625
  python jira_read.py ERA26-625 ERA26-487 --format json
  python jira_read.py ERA26-625 --format raw
  python jira_read.py ERA26-625 --out notes
  python jira_read.py ERA26-625 --no-save
  python jira_read.py --file tickets.txt --format json
"""

import argparse
import json
import os
import ssl
import sys
import urllib.parse

from utils.parser import parse_json
from utils.connect import collect, make_auth_header


def resolve_issue_keys(args, parser):
    if bool(args.issue_key) == bool(args.file):
        parser.error("Provide either ticket arguments or --file, not both.")

    if args.file:
        if not os.path.isfile(args.file):
            parser.error(f"Input file not found: {args.file}")

        with open(args.file, "r", encoding="utf-8") as f:
            issue_keys = [
                line.strip()
                for line in f
                if line.strip() and not line.strip().startswith("#")
            ]
    else:
        issue_keys = args.issue_key

    issue_keys = list(dict.fromkeys(issue_keys))

    if not issue_keys:
        parser.error("No Jira issue keys provided.")

    return issue_keys


def main():
    p = argparse.ArgumentParser(
        description="Fetch Jira tickets and save their snapshots."
    )

    p.add_argument("issue_key", nargs="*", help="Jira issue keys")
    p.add_argument("--out", default="jira_snapshots", help="Output folder")
    p.add_argument("--no-save", action="store_true", help="Print only")
    p.add_argument(
        "--format",
        choices=["json", "raw"],
        default="json",
        help="Output format (default: json)"
    )
    p.add_argument(
        "--api",
        choices=["2", "3"],
        default="2",
        help="Jira REST API version (default: 2)"
    )
    p.add_argument(
        "--file",
        help="TXT file containing Jira issue keys, one per line"
    )

    args = p.parse_args()
    issue_keys = resolve_issue_keys(args, p)

    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "secret.json"
    )

    with open(config_path, "r", encoding="utf-8") as f:
        secret = json.load(f)

    cfg = {
        "base_url": secret["JIRA_BASE_URL"],
        "token": secret["JIRA_API_TOKEN"],
        "email": secret["JIRA_EMAIL"],
        "auth": "bearer",
        "ca_bundle": "",
    }

    base_url = cfg["base_url"].strip().rstrip("/")

    if not base_url:
        sys.exit("base_url is empty.")

    ssl_ctx = ssl.create_default_context(
        cafile=cfg["ca_bundle"] or None
    )

    auth = make_auth_header(cfg)

    batch_data = {
        "tickets": {},
        "errors": {}
    }

    for issue_key in issue_keys:
        try:
            encoded_key = urllib.parse.quote(issue_key, safe="")

            result, raw = collect(
                base_url,
                auth,
                encoded_key,
                args.api,
                ctx=ssl_ctx
            )

            ticket_key = result.get("key") or issue_key

            fields = raw.get("fields", {})

            for label, block, items in (
                ("comments", fields.get("comment"), "comments"),
                ("worklogs", fields.get("worklog"), "worklogs"),
                ("change history", raw.get("changelog"), "histories"),
            ):
                if isinstance(block, dict):
                    total = block.get("total", 0)
                    retrieved = len(block.get(items, []))

                    if total > retrieved:
                        print(
                            f"NOTE: only {retrieved} of {total} "
                            f"{label} are in the raw response "
                            f"for {ticket_key}.",
                            file=sys.stderr
                        )

            batch_data["tickets"][ticket_key] = (
                raw if args.format == "raw"
                else parse_json(result)
            )

            print(f"SUCCESS: {ticket_key}", file=sys.stderr)

        except Exception as e:
            batch_data["errors"][issue_key] = str(e)
            print(f"ERROR: {issue_key} - {e}", file=sys.stderr)

    output_data = {
        "tickets": batch_data["tickets"],
        "errors": batch_data["errors"]
    }

    output = json.dumps(
        output_data,
        indent=4,
        ensure_ascii=False,
        default=str
    )

    print(output)

    if not args.no_save:
        os.makedirs(args.out, exist_ok=True)

        output_path = os.path.join(args.out, "tickets.json")

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(
                output_data,
                f,
                indent=4,
                ensure_ascii=False,
                default=str
            )

        print(f"\nSaved: {output_path}", file=sys.stderr)

    print(
        f"\nExtraction completed."
        f"\nTotal requested : {len(issue_keys)}"
        f"\nSuccessful      : {len(batch_data['tickets'])}"
        f"\nFailed          : {len(batch_data['errors'])}",
        file=sys.stderr
    )


if __name__ == "__main__":
    main()
