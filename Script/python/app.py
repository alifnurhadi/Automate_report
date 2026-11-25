import argparse

from utils.paths import SQL_DIR

# rk query
with open(SQL_DIR / 'rekening_koran.sql', 'r', encoding="utf-8") as rk_read:
    rk = rk_read.read()

def main(category: str):
    # RK -> execute the RK query
    # GL -> execute the GL query (TODO)
    # CR -> execute the CR query (TODO)
    if category == 'RK':
        print(rk)
    else:
        print(f'category {category} not implemented yet')


if __name__=='__main__':
    parser = argparse.ArgumentParser(
        prog='Auto_RK',
        description='Automate an fetching a data from datalake'
    )

    parser.add_argument('category', choices=['RK', 'GL', 'CR'], help='Kind of adhoc request')
    args = parser.parse_args()
    main(args.category)
