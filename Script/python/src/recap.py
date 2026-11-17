

from utils.parser import fetchJiraFieldDescription , fetchPeriod , normalizeTablename

txt:str = '''# test
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

txt3 = """
h3. Nomor Tiket KATA\n
DM-26-859\n\n
*Nomor Rekening:*\n
||Nomor Rekening||Periode||\n|
483401032973531|30/11/2020 - 31/12/2021|
483401032989731|30/11/2020 - 31/12/2021|
483401032923131|30/11/2020 - 31/12/2021|
"""


if __name__ == "__main__":

    result =fetchJiraFieldDescription(txt , adhoc = 'Rekening Koran')
    result2 =fetchJiraFieldDescription(txt2 , adhoc = 'Critical Report')
    result3 =fetchJiraFieldDescription(txt3 , adhoc = 'Rekening Koran')
    period = fetchPeriod(txt)
    period2 = fetchPeriod(txt2)
    period3 = fetchPeriod(txt3)
    print([normalizeTablename(x) for x in result+result2+result3 ])
    print(period)
    print(period2)
    print(period3)
