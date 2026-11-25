"""
Fetch Jira tickets with the `jira` library and save a JSON snapshot.
"""

import argparse
from inspect import trace
import json
import os
from pathlib import Path
import re
import sys

from jira import JIRA
from jira.exceptions import JIRAError

sys.path.append('../')
from utils.parser import parse_json, simplify
from utils.paths import SNAPSHOTS_DIR


secret_path = Path(__file__).resolve().parent.parent / "secret.json"
RANGE_RE = re.compile(r'^(?P<prefix>.+-)(?P<start>\d+)\.\.(?P<end>\d+)$')
MAX_RANGE = 3000

print(secret_path)
def load_issue_keys(args, parser):
    def expand_key(token: str) -> list[str]:
        token = token.strip().upper()
        m = RANGE_RE.match(token)
        if not m:
            return [token]

        start, end = int(m["start"]), int(m["end"])
        if start > end:
            raise ValueError(f"Invalid range '{token}': start number bigger than the end-number")
        if end - start + 1 > MAX_RANGE:
            raise ValueError(f"Range '{token}' exceed {MAX_RANGE} tickets allow for the machine")

        return [f"{m['prefix']}{n}" for n in range(start, end + 1)]
    if bool(args.issue_key) == bool(args.file):
        parser.error("Repeat action, Put only either the ticket it self as the argument or the .txt file contains the issue")

    if args.file:
            # utf-8-sig drops a BOM that Notepad/PowerShell may add to the file.
            # A line may hold one key or several keys separated by whitespace
            # (e.g. tickets_to_update_keys.txt); lines starting with '#' are comments.
        with open(args.file, encoding="utf-8-sig") as f:
            keys = [
                key
                for line in f
                if not line.lstrip().startswith("#")
                for key in line.split()
            ]
    else:
        keys = args.issue_key

    keys_final = []
    for token in keys:
        try:
            keys_final.extend(expand_key(token))
        except ValueError as e:
            parser.error(str(e))

    return list(dict.fromkeys(keys_final))


def build_filled_fields(issue, id_to_name):
    """
    getting value need to mapped
    """
    # filled = {
    #     id_to_name.get(field_id, field_id): simplify(value)
    #     for field_id, value in issue.raw["fields"].items()
    #     if value not in (None, "", [], {})
    # }
    filled = issue.raw['fields']
    filled.setdefault("Description", "")
    return filled


def createArgs(argv=None):
    p = argparse.ArgumentParser(description="Fetch Jira tickets and save snapshots.")
    p.add_argument("issue_key", nargs="*", help="Jira issue keys")
    p.add_argument("--file", help="TXT file with one issue key per line")
    p.add_argument("--out", default=str(SNAPSHOTS_DIR), help="Output folder (shared jira_snapshots at repo root)")
    p.add_argument("--no-save", action="store_true", help="Print only")
    p.add_argument("--format", choices=["json", "raw"], default="json")
    p.add_argument("--api", choices=["2", "3"], default="2", help="REST API version")

    return p

def jira_access(path , api="2"):
    '''Returning jira-client and id-to-name data'''
    print('this is path', path)

    with open( path , 'r') as f:
        secret = json.load(f)

    client = JIRA(
        server=secret["JIRA_BASE_URL"].strip().rstrip("/"),
        token_auth=secret["JIRA_API_TOKEN"],
        options={"rest_api_version": api},
    )

    id_to_name = {f["id"]: f["name"] for f in client.fields()}

    return client , id_to_name


def parse_tickets(keys, path, fmt: str, args) -> tuple[set, dict]:

    client, id_to_name = jira_access(path, args.api)
    from utils.log import activity_logger

    result = {}

    map_path = (
        r'C:\Users\Iykra03\Documents\Iykra_alif'
        r'\Script\python\jira_editable_field.json'
    )

    for index, key in enumerate(keys, start=1):

        print(
            f"\n[{index}/{len(keys)}] Processing: {key}",
            file=sys.stderr
        )

        try:
            issue = client.issue(key)

            if fmt == "raw":
                result[issue.key] = issue.raw
                print(f"SUCCESS: {issue.key} | raw", file=sys.stderr)

            else:
                try:
                    filled_fields = build_filled_fields(
                        issue, id_to_name
                    )

                    result[issue.key] = parse_json(
                        {
                            "key": issue.key,
                            "filled_fields": filled_fields
                        },
                        path=map_path
                    )

                    print(
                        f"SUCCESS: {issue.key} | parsed",
                        file=sys.stderr
                    )

                except Exception as e:
                    import traceback

                    print(
                        f"\n[PARSING ERROR] Ticket: {key}",
                        file=sys.stderr
                    )
                    print(
                        f"Error type: {type(e).__name__}",
                        file=sys.stderr
                    )
                    print(
                        f"Error message: {e}",
                        file=sys.stderr
                    )
                    traceback.print_exc()

                    activity_logger(
                        log=f"{type(e).__name__}: {e} | raw fallback",
                        key=key
                    )

                    # Preserve original Jira response
                    result[issue.key] = issue.raw

                    print(
                        f"FALLBACK: {issue.key} | raw saved",
                        file=sys.stderr
                    )

        except JIRAError as e:
            msg = f"{e.status_code}: {e.text}"

            result[key] = {"error": msg}

            print(
                f"\n[JIRA ERROR] Ticket: {key} | {msg}",
                file=sys.stderr
            )

            activity_logger(key=key, log=msg)

        except Exception as e:
            import traceback

            result[key] = {"error": str(e)}

            print(
                f"\n[FETCH ERROR] Ticket: {key}",
                file=sys.stderr
            )
            traceback.print_exc()

            activity_logger(key=key, log=e)

        # issues=client.issue(key)
        # result[key]=issues.raw

    ticket_num = set(result.keys())

    return ticket_num , result



def write_output(result, out=SNAPSHOTS_DIR, filename='' , save=True):
    output = json.dumps(result, indent=4, ensure_ascii=False, default=str)

    if save:
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, f"{filename}.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"\nSaved: {path}", file=sys.stderr)

    try :
        failed = [k for k, v in result.items() if isinstance(v, dict) and list(v) == ["error"]]
    except :
        failed = []

    print(
        f"\nTotal requested: {len(result)} | "
        f"Successful: {len(result) - len(failed)} | Failed: {len(failed)}",
        file=sys.stderr
    )

def main(path_cfg):
    parser = createArgs()
    args = parser.parse_args()
    args.keys = load_issue_keys(args, parser)
    ticket , details = parse_tickets(args.keys, path_cfg , args.format, args)
    return args,  ticket , details

if __name__ == "__main__":

    secret_path = Path(__file__).resolve().parent.parent / "secret.json"
    args, ticket , detail = main(secret_path)

    print(detail)
    print(ticket)
    write_output(detail, args.out, 'result_detail' ,  not args.no_save)
    write_output(ticket, args.out, 'tickets',  not args.no_save)
