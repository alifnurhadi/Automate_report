#import
import json
import random
from time import sleep

from utils.paths import MSG_PATH


def calculate(args:int):

    if not isinstance(args,int):
        return ValueError('type not allowed')
    print('Processing...')
    sleep(random.randint(1,4))
    print('Done..')
    return args * 3


def main():
    path = MSG_PATH


    while 1:
        with open(path , 'r' , encoding='utf-8') as msg_f:
            msg = json.load(msg_f)
        try :
            typeload = random.randint(1,4)
            if typeload > 2:
                print('big data is coming...')
            data = msg['message'].pop(0)

            print(f'Processing...{data['name']}')
            print(data['description'] , '\n')

            with open (path ,'w') as wrt :
                json.dump(msg,wrt ,indent=4)
            sleep(typeload)

        except IndexError :
            print('waiting for task')
            sleep(10)



if __name__ == "__main__":
    main()
