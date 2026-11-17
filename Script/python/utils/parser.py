

import json
import re


def describe_field_meta(meta):
    """Turn one entry of editmeta / transition fields into a small readable dict."""
    out = {
        "name": meta.get("name"),
        "required": bool(meta.get("required")),
        "type": (meta.get("schema") or {}).get("type"),
    }
    allowed = meta.get("allowedValues")

    if allowed:
        out["allowed_values"] = [simplify(a) for a in allowed]

    return out

def _text(args):
    if args.__class__ is str:
        return args
    if isinstance(args, (list, tuple)):
        return "\n".join(map(str, args))
    return str(args)

def _join(v):
    if isinstance(v, (list, tuple)):
        return ' | '.join(str(x) for x in v)
    return str(v or '')

def parse_json(args:dict , path):
    jira_field = args.get('filled_fields',{})

    temp_path = path

    with open(temp_path, 'r') as temp:
        map_field = json.load(temp)

    pseudocode = jira_field.get(map_field('Pseudocode'),'')
    langkah = jira_field.get(map_field('Langkah Pengerjaan'),'')
    final_code =  jira_field.get(map_field('Query Final'),'')


    structure = {
        'ticket': args['key'],
        'title': jira_field.get(map_field.get('Summary'), ''),
        'server': ' | '.join(jira_field.get(map_field.get('Server'), '')),
        'database': ' | '.join(jira_field.get(map_field.get('Database'), '')),
        'table': ' | '.join(jira_field.get(map_field.get('Tabel'), '')),
        'start_wbs': jira_field.get(map_field.get('Data Analyst Start Date'), ''),
        'end_wbs': jira_field.get(map_field.get('End date'), ''),
        'description': jira_field.get(map_field.get('Description'), ''),
        'langkah_kerja': _join([pseudocode, langkah, final_code]),
        'disclaimer': jira_field.get(map_field.get('Disclaimer'), ''),
        'group_adhoc': jira_field.get(map_field.get('Group AdHoc'), [])[0].get('value',''),
        'complexity': jira_field.get(map_field.get('Complexity'), '').get('value','') ,
        'status': jira_field.get('status', '').get('name',''),
        # 'filled_fields': jira_field
    }
    print(pseudocode,'\n',langkah,'\n',final_code)
    return structure

def adf_to_text(node):
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_text(n) for n in node)
    if not isinstance(node, dict):
        return ""
    t = node.get("type")
    if t == "text":
        return node.get("text", "")
    if t == "hardBreak":
        return "\n"
    if t == "mention":
        return node.get("attrs", {}).get("text", "")
    inner = adf_to_text(node.get("content", []))
    if t in ("paragraph", "heading", "listItem", "codeBlock", "blockquote"):
        return inner + "\n"
    return inner

def simplify(value):
    def _lower(v):
        return v.lower() if isinstance(v, str) else v
    if value is None:
        return None
    if isinstance(value, dict):
        if value.get("type") == "doc":
            return adf_to_text(value).strip().lower()
        for key in ("displayName", "name", "value", "key", "filename"):
            if key in value:
                return value[key]

        return {k: simplify(v) for k, v in value.items() if k not in ("self", "iconUrl", "avatarUrls")}
    if isinstance(value, list):
        return [_lower(simplify(v)) for v in value]

    return value


def normalizeTablename(text:str):
    '''normalize table name so it can be used to query to a database'''
    hasil = text.strip().lower()

    if ' ' in text:
        return hasil.replace(' ','')
    return hasil

def fetchJiraFieldDescription (text:str , **group)-> list[str]:
    cr_tag = re.compile(r'[a-zA-Z]{2}\d{3}|[a-zA-Z]{2}\s\d{3}')
    gl_tag = re.compile(r'\d{12}')
    rk_tag = re.compile(r'\d{15}')

    adhoc = group.get('adhoc',None)
    assert type(adhoc) == str
    valid_group = {'Critical Report' , 'General Ledger' , 'Rekening Koran'}
    if not adhoc :
        raise KeyError(
            """
            can't process data when key 'adhoc' not exist do put parameter ```adhoc = value in string ```
            available value are ['Critical Report' , 'General Ledger' , 'Rekening Koran']
            """)

    if adhoc not in valid_group:
        raise ValueError("""
            valid available value are ['Critical Report' , 'General Ledger' , 'Rekening Koran']
        """)

    findings = ['']
    match adhoc:
        case 'Critical Report':
            findings = cr_tag.findall(text)
        case 'General Ledger':
            findings = gl_tag.findall(text)
        case 'Rekening Koran':
            findings = rk_tag.findall(text)

    return findings

def fetchPeriod(text:str , format:str = 'dd/mm/yyyy' ,grouped:bool = True ):
    """
    # Default function is to process range of period, if single period set grouped = False
    #
    format available
    - 'dd/mm/yyyy' -> 31/12/2026
    - 'mm/dd/yyyy' -> 12/31/2026
    - 'bbb/yyyy' -> Mar/2026
    """
    announce = """
    FORMAT PASS TO THIS FUNCTION MUST ALIGN TO THE PATTERN BELOW OR WILL GET UNEXPECTED RESULT\n
    format available
    'dd/mm/yyyy' -> 31/12/2026
    'mm/dd/yyyy' -> 12/31/2026
    'bbb/yyyy' -> Mar/2026
    """
    print(announce)
    patternmatchSource = {
        'yyyy' : '%Y',
        'mm':'%m',
        'dd':'%d',
        'bbb':'%b'
    }
    delimiter = '/' if '/' in format else '-'
    periodPattern = format.split(delimiter)

    unknownPattern = periodPattern - patternmatchSource.keys()

    if len(unknownPattern)>0:
        raise ValueError('there are pattern that arent recognized please follow these pattern '+announce)

    pyPattern = delimiter.join([patternmatchSource.get(v) for v in periodPattern])

    pattern_0 = r'\d{2}\/\d{2}\/\d{4}' if len(periodPattern) == 3 else  r'\w{3}\/\d{4}'

    if grouped :
        pattern_0 += f' - {pattern_0}'

    pattern_1 = re.compile(pattern_0)

    result = pattern_1.findall(text)

    return result

if __name__ == '__main__':
    print('This only utils tools')
