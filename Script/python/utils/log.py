from datetime import datetime


def activity_logger (**val):
    with open(
        r'C:\Users\Iykra03\Documents\Iykra_alif\Script\python\jira_snapshots\apply_errors.log',
        "a", encoding="utf-8") as f:
        f.write(
            f"{datetime.now()} | {val.get('key','')} | "
            f"{type(val.get('log','')).__name__}: {val.get('log','')}\n")
