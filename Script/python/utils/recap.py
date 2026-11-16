import re


# test
# "h3. Nomor Tiket KATA
# DM-26-989
#
# *Unit Kerja:*
# * 00129 -- KC Lubuk Linggau
#
# *Kode Critical Report:*
# ||Kode Critical Report||Periode||
# |GI405|01/12/2025 - 31/12/2025|"

cr_tag = re.compile(r'[a-zA-Z]{2}\d{3}|[a-zA-Z]{2}\s\d{3}')
gl_tag = re.compile(r'\d{12}')


text:str = '''# test
# "h3. Nomor Tiket KATA
# DM-26-989
#
# *Unit Kerja:*
# * 00129 -- KC Lubuk Linggau
#
# *Kode Critical Report:*
# ||Kode Critical Report||Periode||
# |GI405|01/12/2025 - 31/12/2025|"'''
#
txt2 :str = '''Nomor Tiket KATA
DM-26-930

Unit Kerja:

00971 – UNIT SANUR DENPASAR GM
Kode Critical Report:

Kode Critical Report	Periode
GI 307	05/10/2026 - 05/10/2026
TL 506	05/10/2026 - 05/10/2026
GY 460	05/10/2026 - 05/10/2026
LI 310	05/10/2026 - 05/10/2026
GI 303	05/10/2026 - 05/10/2026
'''

result = cr_tag.findall(text)
print(result)

result2 = cr_tag.findall(txt2)
print(result2)
print(len('200030300131'))

def fetchPattern (text:str , group:str):
    cr_tag = re.compile(r'[a-zA-Z]{2}\d{3}|[a-zA-Z]{2}\s\d{3}')
    gl_tag = re.compile(r'\d{12}')


    findings = ''

    return findings
