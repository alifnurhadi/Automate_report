import json
from pathlib import Path

from read_jira_v2 import jira_access , build_filled_fields , load_issue_keys , parse_args ,write_output
from utils.mapped_data import *





def check_logic(issue:dict , compare_value:dict):
    ...

def apply_changes(args):
    ...

def main():
    args_val = parse_args()
    print(args_val)
    # load_issue_keys(args_val , )

    client , idName = jira_access(SECRET_PATH)

    ticket = client.issue('ERA26-625')

    value = build_filled_fields(ticket ,idName)
    print('\n ', ticket)
    print('\n' , value)

    write_output(value , filename='testingRaw' , save=args_val.no_save)




if __name__ == "__main__":
    main()
