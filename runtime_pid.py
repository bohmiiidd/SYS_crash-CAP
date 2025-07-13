import os 
import time 



def list_processes():
    pids = [pid for pid in os.listdir('/proc') if pid.isdigit()]
    processes = []
    for pid in pids:
        try:
            with open(f'/proc/{pid}/comm', 'r') as f:
                name = f.read().strip()
            processes.append((pid, name))
        except Exception as e:
            continue
    return processes

def main():
    while True:
        os.system('clear') 
        processes = list_processes()
        print(f"{'PID':>6}  {'Process Name'}")
        print('-' * 30)
        for pid, name in processes:
            print(f"{pid:>6}  {name}")
        time.sleep(2)

if __name__ == "__main__":
    main()




