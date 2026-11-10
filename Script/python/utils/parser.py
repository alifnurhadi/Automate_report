

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



def parse_json(args:dict):
    data_field = args.get('filled_fields',{})
    pseudocode = data_field.get('Pseudocode','')
    langkah = data_field.get('Langkah Pengerjaan','')
    final_code =  data_field.get('Query Final','')


    structure =  {
    'ticket' : args['key'],
    'title':data_field.get('Summary',''),
    'server':' | '.join(data_field.get('Server','')),
    'database':' | '.join(data_field.get('Database','')),
    'table':' | '.join(data_field.get('Tabel','')),
    'start_wbs' : data_field.get('Data Analyst Start Date',''),
    'end_wbs' : data_field.get('End date',''),
    'description':data_field['Description'],
    'langkah_kerja':_join([pseudocode,langkah,final_code]),
    'disclaimer':data_field.get('Disclaimer',''),
    'group_adhoc':data_field.get('Group AdHoc',[])[0],
    'status':data_field.get('Status','')
    }
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

if __name__ == '__main__':
    print('This only utils tools')
