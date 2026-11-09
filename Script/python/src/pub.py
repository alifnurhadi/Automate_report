#import
import argparse
import json
import random
from time import sleep


def create_task():

    tasks = random.randint(1000,9999)
    job = random.choices(['Norm','Hard'] , [0.7, 0.3])


    print('creating job')
    sleep(2)

    job_name:str = job[0] + ' ' + str(tasks)
    job_desc:str = f'SELECT { random.choice(['a','b','c'])} FROM TABLE { random.choice(['A','B','C'])} '

    return {
        'name':job_name,
        'description':job_desc
    }


def main():

    path = r'C:\Users\Iykra03\Documents\Iykra_alif\Docs/msg.json'


    while 1:
        with open(path , 'r' , encoding='utf-8') as msg:
            list_of_tasks = json.load(msg)
        print(len(list_of_tasks))
        if len(list_of_tasks['message']) < 3 :
            n = random.randint(2,10)
            for _ in range(n):
                tugas = create_task()
                list_of_tasks['message'].append(tugas)

                with open(path , 'w') as wrt :
                    json.dump(list_of_tasks , wrt , indent=4)
            print('finished..')
            sleep(2)
        else:
            print('Subs in consume mode')
            sleep(10)

if __name__ == "__main__":

    pars = argparse.ArgumentParser()
    pars.add_argument('--lt' , type=int ,default=1)


    arg  = pars.parse_args()
    print(arg.lt)
    main()
