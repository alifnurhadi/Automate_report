"""
Fetch Jira tickets with the `jira` library and save a JSON snapshot.
"""

import argparse
import json
import os
import sys

from jira import JIRA
from jira.exceptions import JIRAError

from utils.parser import parse_json, simplify


def load_issue_keys(args, parser):
    if bool(args.issue_key) == bool(args.file):
        parser.error("Repeat action, Put only either the ticket it self as the argument or the .txt file contains the issue")

    if args.file:
        with open(args.file, encoding="utf-8") as f:
            keys = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    else:
        keys = args.issue_key

    return list(dict.fromkeys(keys))


def build_filled_fields(issue, id_to_name):
    """
    getting value need to mapped
    """
    filled = {
        id_to_name.get(field_id, field_id): simplify(value)
        for field_id, value in issue.raw["fields"].items()
        if value not in (None, "", [], {})
    }
    filled.setdefault("Description", "")
    return filled


secret_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secret.json")
# with open(secret_path, encoding="utf-8") as f:
#     secret = json.load(f)
#
def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Fetch Jira tickets and save snapshots.")
    p.add_argument("issue_key", nargs="*", help="Jira issue keys")
    p.add_argument("--file", help="TXT file with one issue key per line")
    p.add_argument("--out", default="jira_snapshots", help="Output folder")
    p.add_argument("--no-save", action="store_true", help="Print only")
    p.add_argument("--format", choices=["json", "raw"], default="json")
    p.add_argument("--api", choices=["2", "3"], default="2", help="REST API version")
    args = p.parse_args(argv)
    args.keys = load_issue_keys(args, p)
    return args

def jira_access(path , api="2"):

    with open(path, encoding="utf-8") as f:
        secret = json.load(f)

    client = JIRA(
        server=secret["JIRA_BASE_URL"].strip().rstrip("/"),
        token_auth=secret["JIRA_API_TOKEN"],
        options={"rest_api_version": args.api},
    )

    id_to_name = {f["id"]: f["name"] for f in client.fields()}

    return client , id_to_name


def read_tickets(keys , fmt:str)-> tuple[set , dict]:

    client, id_to_name = jira_access( secret_path , args.api)

    result = {}
    for key in keys:
        try:
            issue = client.issue(key)
            if fmt == "raw":
                result[issue.key] = issue.raw
            else:
                result[issue.key] = parse_json(
                    {"key": issue.key, "filled_fields": build_filled_fields(issue, id_to_name)}
                )
            print(f"SUCCESS: {issue.key}", file=sys.stderr)

        except JIRAError as e:
            msg = f"{e.status_code}: {e.text}"
            result[key] = {"error": msg}
            print(f"ERROR: {key} - {msg}", file=sys.stderr)
        except Exception as e:
            result[key] = {"error": str(e)}
            print(f"ERROR: {key} - {e}", file=sys.stderr)

    ticket_num = set(result.keys())

    return ticket_num , result



def write_output(result, out="jira_snapshots", save=True):
    output = json.dumps(result, indent=4, ensure_ascii=False, default=str)

    if save:
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, "tickets.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"\nSaved: {path}", file=sys.stderr)

    failed = [k for k, v in result.items() if isinstance(v, dict) and list(v) == ["error"]]
    print(
        f"\nTotal requested: {len(result)} | "
        f"Successful: {len(result) - len(failed)} | Failed: {len(failed)}",
        file=sys.stderr
    )

def main(args):
    return read_tickets(args.keys, args.format)

if __name__ == "__main__":
    args = parse_args()
    ticket , detail = main(args)
    print(detail)
    print(ticket)
    # write_output(result, args.out, not args.no_save)
