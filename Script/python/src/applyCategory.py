import argparse
import concurrent.futures
import json
from pathlib import Path

from src.read_jira_v2 import jira_access , load_issue_keys , parse_args

FIELD_FILE = r'C:\Users\Iykra03\Documents\Iykra_alif\Script\python\jira_editable_field.json'

def applied(client, jira_field, ticket, new_value, field_name):
    field_id = jira_field.get(field_name)
    if field_id is None:
        raise ValueError(f'Unknown field "{field_name}". Available: {list(jira_field.keys())}')

    meta = client.editmeta(ticket)['fields'].get(field_id)
    if meta is None:
        raise ValueError(f'{field_id} is not editable on {ticket}')

    allowed = [v.get('value') or v.get('name') for v in meta.get('allowedValues', [])]
    print(f'{ticket}: schema={meta["schema"]}, allowed={allowed}, sending={new_value!r}')

    # client.issue('ERA23-15').update(fields={
    #     field_id: [{"value": "Rekening Koran"}]
    # })
    client.issue(ticket).update(fields={
        field_id: [{"value": new_value}]
    })

    after = client.issue(ticket, fields=field_id)
    print(f'{ticket}: now = {getattr(after.fields, field_id)}')





def main(args):
    client, _ = jira_access(args.config)

    with open(FIELD_FILE, 'r') as f:
        jira_field = json.load(f)
    with open(args.path, 'r') as f:
        val = json.load(f)

    items = val.items() if isinstance(val, dict) else val
    print(f'Loaded {sum(len(t) for _, t in items)} tickets')

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(applied, client, jira_field, tckt, nv, 'Group AdHoc'): tckt
            for nv, l_tckt in items
            for tckt in l_tckt
        }
        for fut in concurrent.futures.as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                print(f'FAILED {futures[fut]}: {e}')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--path', type=str, required=True, help='JSON mapping value -> tickets')
    p.add_argument('--config', type=str, required=True, help='Path to Jira secret file')
    args = p.parse_args()

    for name in ('path', 'config'):
        if not Path(getattr(args, name)).exists():
            raise ValueError(f'--{name} does not exist: {getattr(args, name)}')

    main(args)

#
# import argparse
# import json
# import os
# import re
# import sys
# from collections import Counter
# from concurrent.futures import ThreadPoolExecutor, as_completed
# from pathlib import Path
#
# from jira.exceptions import JIRAError
# from rich.console import Console
# from rich.panel import Panel
# from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
# from rich.table import Table
#
# from read_jira_v2 import jira_access, load_issue_keys
#
# SECRET = Path(__file__).resolve().parent.parent / "secret.json"
# FIELDS = "summary,status,created,assignee,labels,issuetype"
# GROUPS = ["RK", "GL", "CR", "Lain-Lain"]
# COLOR = {"RK": "green", "GL": "yellow", "CR": "magenta", "Lain-Lain": "white"}
#
# # truth from user. win over rule.
# OVERRIDE = {
#     "ERA23-700": "RK",
#     "ERA23-675": "RK",
# }
#
# # fallback keyword rule (playbook routing tree). order matter.
# RULES = [
#     ("RK", re.compile(r"rekening koran|\brc\b|mutasi rekening|account statement", re.I)),
#     ("GL", re.compile(r"general ledger|jurnal gl|\bgl account\b", re.I)),
#     ("CR", re.compile(r"critical report", re.I)),
# ]
#
#
# def classify(key: str, summary: str) -> str:
#     if key in OVERRIDE:
#         return OVERRIDE[key]
#     for group, pat in RULES:
#         if pat.search(summary or ""):
#             return group
#     return "Lain-Lain"
#
#
# def fetch_one(client, key: str) -> dict:
#     try:
#         f = client.issue(key, fields=FIELDS).raw["fields"]
#         return {
#             "key": key,
#             "summary": f.get("summary") or "",
#             "status": (f.get("status") or {}).get("name", "-"),
#             "created": (f.get("created") or "")[:10],
#             "assignee": (f.get("assignee") or {}).get("displayName", "-"),
#         }
#     except JIRAError as e:
#         return {"key": key, "error": f"{e.status_code}: {e.text}"}
#     except Exception as e:
#         return {"key": key, "error": str(e)}
#
#
# def fetch_all(keys: list[str], workers: int) -> list[dict]:
#     client, _ = jira_access(SECRET)          # one client, share to all thread
#     out = []
#     with Progress(SpinnerColumn(), TextColumn("[bold]Fetch Jira"),
#                   BarColumn(), TextColumn("{task.completed}/{task.total}")) as bar:
#         task = bar.add_task("fetch", total=len(keys))
#         with ThreadPoolExecutor(max_workers=workers) as pool:
#             futs = [pool.submit(fetch_one, client, k) for k in keys]
#             for fut in as_completed(futs):
#                 out.append(fut.result())
#                 bar.advance(task)
#     return out
#
# from datetime import datetime
#
# EMOJI = {"RK": "🟢", "GL": "🟡", "CR": "🟣", "Lain-Lain": "⚪"}
#
#
# def wa_message(ok: list[dict], bad: list[dict], cnt: Counter, max_list: int = 20) -> str:
#     total = len(ok) or 1
#     now = datetime.now().strftime("%d %b %Y %H:%M")
#     rk = sorted((r for r in ok if r["group"] == "RK"), key=lambda x: x["key"])
#
#     lines = [
#         "*📊 Rekap Kategori Tiket Data Request*",
#         f"_Update: {now} WIB_",
#         "",
#         "*Ringkasan*",
#     ]
#     for g in GROUPS:
#         lines.append(f"{EMOJI[g]} {g}: *{cnt[g]}* ({cnt[g] / total:.1%})")
#     lines += [
#         f"━━━━━━━━━━━━",
#         f"📁 Total: *{len(ok)}* tiket",
#         f"✅ RK: *{cnt['RK']}* | 📦 Lainnya: *{len(ok) - cnt['RK']}*",
#     ]
#     if bad:
#         lines.append(f"⚠️ Gagal fetch: *{len(bad)}*")
#
#     if rk:
#         lines += ["", "*Detail Tiket RK*"]
#         for i, r in enumerate(rk[:max_list], 1):
#             lines.append(f"{i}. *{r['key']}* ({r['status']})")
#             lines.append(f"   _{r['summary'][:60]}_")
#         if len(rk) > max_list:
#             lines.append(f"_...dan {len(rk) - max_list} tiket lain_")
#
#     if bad:
#         lines += ["", "*Gagal Fetch*"]
#         lines += [f"• {r['key']}" for r in bad[:max_list]]
#
#     lines += ["", "_Sumber: Jira EDM-DAP_"]
#     return "\n".join(lines)
#
# def report(rows: list[dict], out_dir: str):
#     con = Console()
#     ok = [r for r in rows if "error" not in r]
#     bad = [r for r in rows if "error" in r]
#     for r in ok:
#         r["group"] = classify(r["key"], r["summary"])
#     cnt = Counter(r["group"] for r in ok)
#     total = len(ok) or 1
#
#     # summary
#     t = Table(title="Ringkasan Kategori", header_style="bold cyan")
#     t.add_column("Kategori")
#     t.add_column("Jumlah", justify="right")
#     t.add_column("%", justify="right")
#     for g in GROUPS:
#         t.add_row(f"[{COLOR[g]}]{g}[/]", str(cnt[g]), f"{cnt[g] / total:.1%}")
#     t.add_row("[bold]Total[/]", f"[bold]{len(ok)}[/]", "100%")
#     con.print(t)
#     con.print(Panel(
#         f"[bold green]RK: {cnt['RK']}[/]   |   [bold]Lainnya: {len(ok) - cnt['RK']}[/]"
#         + (f"   |   [red]Gagal: {len(bad)}[/]" if bad else ""),
#         expand=False,
#     ))
#
#     # RK detail
#     d = Table(title="Detail Tiket RK", header_style="bold green")
#     for c in ("Key", "Summary", "Status", "Created", "Assignee"):
#         d.add_column(c, overflow="fold")
#     for r in sorted((x for x in ok if x["group"] == "RK"), key=lambda x: x["key"]):
#         d.add_row(r["key"], r["summary"][:70], r["status"], r["created"], r["assignee"])
#     con.print(d)
#
#     # error
#     if bad:
#         e = Table(title="Gagal Fetch", header_style="bold red")
#         e.add_column("Key")
#         e.add_column("Error", overflow="fold")
#         for r in bad:
#             e.add_row(r["key"], r["error"][:120])
#         con.print(e)
#
#     # save
#     os.makedirs(out_dir, exist_ok=True)
#     result = {g: sorted(r["key"] for r in ok if r["group"] == g) for g in GROUPS}
#     result["_ringkasan"] = {g: cnt[g] for g in GROUPS} | {"total": len(ok), "gagal": len(bad)}
#     path = os.path.join(out_dir, "hasil_kategori.json")
#     with open(path, "w", encoding="utf-8") as f:
#         json.dump(result, f, indent=2, ensure_ascii=False)
#
#     msg = wa_message(ok, bad, cnt)
#     wa_path = os.path.join(out_dir, "whatsapp_message.txt")
#     with open(wa_path, "w", encoding="utf-8") as f:
#         f.write(msg)
#     con.print(Panel(msg, title="WhatsApp Message", border_style="green", expand=False))
#     con.print(f"[dim]Saved: {wa_path}[/]")
#     con.print(f"[dim]Saved: {path}[/]")
#
#
# def main():
#     p = argparse.ArgumentParser(description="Count RK vs rest from Jira tickets.")
#     p.add_argument("issue_key", nargs="*", help="Jira keys or range ERA23-1..ERA23-9")
#     p.add_argument("--file", help="TXT file with keys")
#     p.add_argument("--workers", type=int, default=10, help="Parallel fetch")
#     p.add_argument("--out", default="jira_snapshots", help="Output folder")
#     args = p.parse_args()
#
#     keys = load_issue_keys(args, p)
#     rows = fetch_all(keys, args.workers)
#     report(rows, args.out)
#
#
# if __name__ == "__main__":
#     main()
