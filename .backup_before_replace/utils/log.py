from datetime import datetime


def activity_logger (**val):
    with open(
        r'C:\Users\Iykra03\Documents\Iykra_alif\Script\python\jira_snapshots\apply_errors.log',
        "a", encoding="utf-8") as f:
        f.write(
            f"{datetime.now()} | {val.get('key','')} | "
            f"{type(val.get('log','')).__name__}: {val.get('log','')}\n")

def result_logger(val:dict):

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
        r'C:\Users\Iykra03\Documents\Iykra_alif\Script\python\jira_snapshots\result.log',
        "a", encoding="utf-8") as f:
        f.write(msg)
