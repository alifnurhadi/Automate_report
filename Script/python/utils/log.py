from datetime import datetime

from utils.paths import APPLY_ERROR_LOG, RESULT_LOG, SNAPSHOTS_DIR


def activity_logger (**val):
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(
        APPLY_ERROR_LOG,
        "a", encoding="utf-8") as f:
        f.write(
            f"{datetime.now()} | {val.get('key','')} | "
            f"{type(val.get('log','')).__name__}: {val.get('log','')}\n")

def result_logger(val:dict):
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    msg = f"""'key : {val.get('ticket','')}
        desc : {val.get('description','')}
        server : {val.get('server')}
        table :{val.get('table')}
        database : {val.get('database')}
        disclaimer : {val.get('disclaimer')}
        ---
    """
# pengerjaan : {val.get('pengerjaan','')} query :{val.get('query_final','')} pseudo : {val.get('pseudocode','')}

    with open(
        RESULT_LOG,
        "a", encoding="utf-8") as f:
        f.write(msg)
