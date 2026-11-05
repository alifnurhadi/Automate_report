import urllib.error
import urllib.request
import urllib.parse
import sys
import base64
import json
from utils.parser import simplify , describe_field_meta
import datetime

def make_auth_header(cfg) -> str:
    email, token, style = cfg["email"], cfg["token"], cfg["auth"].lower()
    if not token or token == "PASTE_TOKEN_HERE":
        sys.exit("Token not filled in. Edit the CONFIG block at the top of main() in this file.")
    if style == "bearer" or (style != "basic" and not email):
        return "Bearer " + token
    if not email:
        sys.exit("auth is \"basic\" but \"email\" is empty in the CONFIG block.")
    return "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()


def api_get(base_url, path, auth_header, optional=False , ctx=None):
    req = urllib.request.Request(
        f"{base_url}{path}",
        headers={"Authorization": auth_header, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if optional:
            return None
        hints = {
            401: "Check token / email in the CONFIG block, and whether the auth style (Bearer vs Basic) is right (\"auth\").",
            403: "You don't have permission to view this issue.",
            404: "Issue not found (or you can't see it). If every ticket gives 404, try --api 2 or --api 3.",
        }
        detail = e.read().decode("utf-8", "replace")[:300]
        sys.exit(f"Jira returned HTTP {e.code}. {hints.get(e.code, '')}\n{detail}")
    except urllib.error.URLError as e:
        sys.exit(f"Could not reach Jira: {e.reason}")

def is_empty(v):
    return v is None or v == [] or v == {} or v == ""


def collect(base_url, auth, key, api , ctx):
    issue = api_get(
        base_url,
        f"/rest/api/{api}/issue/{key}?expand=names,schema,renderedFields,changelog,editmeta,transitions.fields",
        auth, ctx
    )
    editmeta = api_get(base_url, f"/rest/api/{api}/issue/{key}/editmeta", auth, optional=True)

    names = issue.get("names", {})
    filled, empty = {}, []
    for fid, raw in issue.get("fields", {}).items():
        label = names.get(fid, fid)
        val = simplify(raw)
        if is_empty(val):
            empty.append(label)
        else:
            filled[label] = val

    transitions = []
    for t in issue.get("transitions", []):
        transitions.append({
            "id": t["id"],
            "name": t["name"],
            "to": (t.get("to") or {}).get("name"),
            "fields": {fid: describe_field_meta(m) for fid, m in (t.get("fields") or {}).items()},
        })

    editable = None
    if editmeta is not None:
        editable = {fid: describe_field_meta(m) for fid, m in (editmeta.get("fields") or {}).items()}

    return {
        "key": issue.get("key"),
        "url": f"{base_url}/browse/{issue.get('key')}",
        "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "filled_fields": filled,
        "empty_fields": sorted(empty),
        "available_transitions": transitions,
        "editable_fields": editable,
    }, issue
