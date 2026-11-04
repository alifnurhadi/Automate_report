import argparse

# rk query
with open ('../sql/rekening_koran.sql','r', encoding="utf-8") as rk_read:
    rk = rk_read.read()

def main():
    # Cek input for what kind of category
    #
    # if RK execute the RK query
    #
    # if GL execute the GL query
    #
    # if CR execute the CR query

    print('hello, user')


if __name__=='__main__':
    parser = argparse.ArgumentParser(
        prog='Auto_RK',
        description='Automate an fetching a data from datalake'
    )

    parser.add_argument()
    main()
