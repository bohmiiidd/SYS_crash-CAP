import subprocess
import psutil
import os
import signal
import time
import json
from rich.prompt import Confirm
from collections import defaultdict
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.panel import Panel
from rich import box
from pathlib import Path
import shutil


# Initialize Rich console for styling and layout
console = Console()
PID_FILE = ".memory_monitor.pid"

"""
CRASH CAP — Linux Memory & Process Monitoring Toolkit

This script provides an interactive terminal-based control panel to monitor,
analyze, and manage memory usage and processes on a Linux system. It is
designed for developers or users who want detailed insights
into RAM usage, process activity, and system performance.

🔧 Features:
Real-time memory and CPU statistics
Background memory usage monitoring with notifications
Identify top memory-consuming processes
Memory usage breakdown by user
Process memory inspection by PID
Safe and force process termination
Launches a separate live process monitor window
Cache analyzer: detect and clean system, user, pip, thumbnail, and apt caches


Files Used:
- `config.json`: stores configuration like memory threshold and check interval
- `.memory_monitor.pid`: used to track background monitor process

Author: b7z
"""


def animated_banner():
    console.clear()
    console.print(Panel.fit("[bold red]🚨 CRASH CAP — Capture Memory Crash 🚨[/bold red]", style="bold green", box=box.DOUBLE_EDGE))
    print("""
    /\_/\           ___
   = o_o =_______    \ \  -bz7-
    __^      __(  \.__) )
(@)<_____>__(_____)____/
""")
    time.sleep(1)

def load_config(path="config.json"):
    """
    Loads configuration parameters from a JSON file.
    Returns a dictionary containing settings such as memory threshold and check interval.
    
    Args:
        path (str): Path to the config JSON file (default is "config.json").
    """
    with open(path) as f:
        return json.load(f)

config = load_config()
THRESHOLD = config.get("memory_threshold", 80)
CHECK_INTERVAL = config.get("check_interval", 5)


def get_dir_size(path):
    """
    Calculates the total size of all files in the given directory recursively.
    
    Args:
        path (str): Directory path to measure size.
        
    Returns:
        float: Total size in megabytes (MB).
    """
    total = 0
    for dirpath, dirnames, filenames in os.walk(path, onerror=lambda e: None):
        for f in filenames:
            try:
                fp = os.path.join(dirpath, f)
                if os.path.isfile(fp):
                    total += os.path.getsize(fp)
            except (FileNotFoundError, PermissionError):
                continue
    return total / (1024 * 1024)  # in MB

def show_and_clean_all_caches():
    """
    Detects cache directories on the system, calculates and displays their sizes.
    Prompts the user whether to clean all caches.
    If confirmed, attempts to delete contents of cache directories, and handling permissions.
    """
    cache_paths = {
        "System Cache (/var/cache)": "/var/cache",
        "APT Cache (/var/lib/apt/lists)": "/var/lib/apt/lists",
        "User Cache (~/.cache)": os.path.expanduser("~/.cache"),
        "Pip Cache (~/.cache/pip)": os.path.expanduser("~/.cache/pip"),
        "Thumbnail Cache (~/.cache/thumbnails)": os.path.expanduser("~/.cache/thumbnails"),
        "Journal Logs (/var/log/journal)": "/var/log/journal" if os.path.exists("/var/log/journal") else None
    }
    total = 0
    sizes = {}

    console.print("[bold yellow]\n🔍 Detected cache sizes:[/bold yellow]")
    for name, path in cache_paths.items():
        if os.path.exists(path):
            size = get_dir_size(path)
            sizes[path] = size
            total += size
            console.print(f"🗂️  {name} [dim]({path})[/dim]: [cyan]{size:.2f} MB[/cyan]")

    console.print(f"\n[bold green]🧮 Total cache size: {total:.2f} MB[/bold green]")

    if Confirm.ask("🧹 Clean all these caches?", default=False):
        for name, path in cache_paths.items():
            if os.path.exists(path):
                try:
                    for item in os.listdir(path):
                        item_path = os.path.join(path, item)
                        if os.path.isfile(item_path) or os.path.islink(item_path):
                            os.remove(item_path)
                        elif os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                    console.print(f"✔ [green]Cleaned {name} ({path})[/green]")
                except PermissionError:
                    console.print(f"❌ [red]Permission denied:[/red] {path} — [italic]try using sudo[/italic]")
                except Exception as e:
                    console.print(f"⚠️ [red]Failed to clean {name} ({path})[/red]: {e}")
    else:
        console.print("❎ [yellow]Cache cleanup cancelled.[/yellow]")

def get_cpu_disk_stats():
    """
    Retrieves and displays current CPU and disk usage statistics.
    CPU usage is shown as a percentage of total utilization.
    Disk usage is shown as percentage used on root partition.
    """
    cpu = psutil.cpu_percent(interval=1)
    disk = psutil.disk_usage('/')
    console.print(f"[yellow]CPU Usage:[/yellow] {cpu}%")
    console.print(f"[magenta]Disk Usage:[/magenta] {disk.percent}%")

def memory_by_user():
    """
    Aggregates and displays memory usage per user by summing resident set size (RSS)
    of all processes owned by each user.
    """
    user_mem = defaultdict(float)
    for proc in psutil.process_iter(['username', 'memory_info']):
        try:
            mem_mb = proc.info['memory_info'].rss / 1024 ** 2
            user_mem[proc.info['username']] += mem_mb
        except (psutil.NoSuchProcess, TypeError):
            continue

    console.print("[cyan]Memory usage by user:[/cyan]")
    for user, mem in user_mem.items():
        console.print(f"  [green]{user}[/green]: {mem:.2f} MB RAM used")

def get_top_memory_processes(n=5):
    """
    Retrieves the top n memory-consuming processes sorted by memory percent.
    
    Args:
        n (int): Number of top processes to return (default is 5).
        
    Returns:
        list of dict: Each dict contains pid, name, and memory_percent.
    """

    procs = []
    for p in psutil.process_iter(['pid', 'name', 'memory_percent']):
        try:
            procs.append(p.info)
        except psutil.NoSuchProcess:
            pass
    procs.sort(key=lambda x: x['memory_percent'], reverse=True)
    return procs[:n]

def suggest_cleanup():
    """
    Displays the top memory-consuming processes to suggest candidates for cleanup.
    """
    console.print("\n[bold red]Top memory-consuming processes:[/bold red]")
    top_procs = get_top_memory_processes()
    for p in top_procs:
        console.print(f"  [yellow]PID:[/yellow] {p['pid']} | [cyan]{p['name']}[/cyan] | [green]{p['memory_percent']:.2f}%[/green]")

def notify(msg):
    """
    Sends a desktop notification with the given message using 'notify-send'.
    
    Args:
        msg (str): Message content of the notification.
    """
    if os.geteuid() == 0:
        print("[!] Monitor-crash is a persistent background process that runs until the script exits.")
        print("[!] For security and stability reasons, notifications are disabled when running as root.")
    return
    subprocess.run(["notify-send", "Memory Alert", msg])

def monitor_memory():
    """
    Runs a continuous loop monitoring system memory usage.
    Sends a notification if memory usage exceeds the configured threshold.
    Saves its own PID to a file to enable stop monitoring later.
    """
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    try:
        while True:
            usage = psutil.virtual_memory().percent
            if usage >= THRESHOLD:
                notify(f"⚠️ Memory usage > {THRESHOLD}% ({usage:.1f}%)")
            time.sleep(CHECK_INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)

def start_monitor():
    if os.path.exists(PID_FILE):
        with open(PID_FILE) as f:
            pid = int(f.read())
        if psutil.pid_exists(pid):
            console.print(f"[bold red]Monitor already running with PID {pid}[/bold red]")
            return

    pid = os.fork()
    if pid == 0:
        monitor_memory()
        sys.exit(0)
    else:
        console.print(f"[green]Memory monitor started in background with PID {pid}[/green]")

def stop_monitor():
    """
    Stops the background memory monitoring process by reading its PID from file,
    sending it a termination signal, and removing the PID file.
    """
    if not os.path.exists(PID_FILE):
        console.print("[red]Monitor is not running.[/red]")
        return

    with open(PID_FILE) as f:
        pid = int(f.read())

    if psutil.pid_exists(pid):
        os.kill(pid, signal.SIGTERM)
        console.print(f"[yellow]Stopped memory monitor with PID {pid}[/yellow]")
    else:
        console.print("[red]No running monitor process found.[/red]")

    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)

def open_process_monitor():
    """
    Launches an external process monitor script (runtime_pid.py) in a new xterm window.
    """
    subprocess.Popen(["xterm", "-hold", "-e", "python3", "runtime_pid.py"])

def get_system_memory_usage():
    """
    Reads memory statistics from /proc/meminfo and displays total, used, free,
    and available memory in MB with a progress spinner animation.
    """
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), TimeElapsedColumn(), transient=True) as progress:
        progress.add_task(description="Checking system memory...", total=None)
        time.sleep(1)

    meminfo = {}
    with open("/proc/meminfo", "r") as f:
        for line in f:
            key, val, *_ = line.split()
            meminfo[key.strip(':')] = int(val)

    total = meminfo.get("MemTotal", 0)
    free = meminfo.get("MemFree", 0)
    available = meminfo.get("MemAvailable", 0)
    buffers = meminfo.get("Buffers", 0)
    cached = meminfo.get("Cached", 0)

    used = total - free - buffers - cached

    console.print(f"[bold]Total memory:[/bold] {total // 1024} MB")
    console.print(f"[bold red]Used memory:[/bold red] {used // 1024} MB")
    console.print(f"[bold green]Free memory:[/bold green] {free // 1024} MB")
    console.print(f"[bold yellow]Available memory:[/bold yellow] {available // 1024} MB")

def get_process_memory(pid):
    """
    Displays memory usage information (RSS and percent) for a specific process by PID.
    
    Args:
        pid (int): Process ID to inspect.
    """
    try:
        p = psutil.Process(pid)
        name = p.name()
        mem_info = p.memory_info()
        console.print(f"\n[cyan]Process {pid} ({name}):[/cyan]")
        console.print(f"  RSS: {mem_info.rss / 1024 ** 2:.2f} MB")
        console.print(f"  Memory %: {p.memory_percent():.2f}%")
    except psutil.NoSuchProcess:
        console.print("[red]Process not found[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")

def list_user_processes():
    """
    Lists all active processes owned by the current user.
    Displays PID and process name.
    """
    current_user = psutil.Process().username()
    console.print(f"\n[bold]📋 Active processes owned by: [green]{current_user}[/green][/bold]")
    found = False
    for proc in psutil.process_iter(['pid', 'name', 'username']):
        if proc.info['username'] == current_user:
            console.print(f"  [cyan]PID {proc.info['pid']:<6}[/cyan] {proc.info['name']}")
            found = True
    if not found:
        console.print("[yellow]No user-owned processes found.[/yellow]")

def kill_process(pid, force=False):
    """
    Attempts to terminate a process by PID.
    Prompts for user confirmation before killing.
    Can perform graceful termination (SIGTERM) or forced kill (SIGKILL).
    
    Args:
        pid (int): Process ID to terminate.
        force (bool): If True, send SIGKILL. Otherwise, SIGTERM (default False).
    """
    try:
        p = psutil.Process(pid)
        name = p.name()
        user = p.username()
        console.print(f"\n[red]⚠️  Target: PID {pid} ({name}) — owned by {user}[/red]")
        confirm = input("Are you sure you want to kill this process? (y/N): ").strip().lower()
        if confirm != 'y':
            console.print("[bold]❌ Cancelled.[/bold]")
            return
        if force:
            p.kill()
            console.print(f"[red]💀 Force-killed PID {pid} ({name})[/red]")
        else:
            p.terminate()
            p.wait(timeout=3)
            console.print(f"[green]✅ Terminated PID {pid} ({name})[/green]")
    except psutil.NoSuchProcess:
        console.print("[red]❌ Process not found.[/red]")
    except psutil.AccessDenied:
        console.print("[red]🚫 Access denied. Try running as root.[/red]")
    except Exception as e:
        console.print(f"[red]❌ Error: {e}[/red]")

def print_help():
    console.print(Panel("[bold blue]🧠 CRASH CAP — Command Help[/bold blue]"))
    console.print("[green]pm[/green]                       Open process monitor")
    console.print("[green]mu[/green]                       Show system memory + CPU stats")
    console.print("[green]up[/green]                       List current user's processes")
    console.print("[green]mup <pid>[/green]                Show memory usage of a process")
    console.print("[green]kill <pid>[/green]               Kill process gracefully")
    console.print("[green]kill <pid> --force[/green]       Force kill a process")
    console.print("[green]monitor-crash start|stop[/green] Start or stop memory crash monitor (alert)")
    console.print("[green]cleanup[/green]                  Show top memory processes and clean caches")
    console.print("[green]clear[/green]                    Clear the screen")
    console.print("[green]help[/green] or [green]h[/green]                Show this menu")
    console.print("[green]q[/green]                        Quit\n")

def main():
    animated_banner()
    console.print("\n[bold green]🚨 USAGE: h/help 🚨[/bold green]")


    while True:
        user_input = console.input("[bold red]Command>[/bold red] ").strip()
        parts = user_input.split()
        if not parts:
            continue
        command = parts[0].lower()
        if command == 'q':
            console.print("[cyan]Exiting...[/cyan]")
            break
        elif command == 'pm':
            open_process_monitor()
        elif command == 'mu':
            memory_by_user()
            get_system_memory_usage()
            get_cpu_disk_stats()
        elif command == 'mup' and len(parts) == 2 and parts[1].isdigit():
            get_process_memory(int(parts[1]))
        elif command == 'kill':
            if len(parts) == 2 and parts[1].isdigit():
                kill_process(int(parts[1]), force=False)
            elif len(parts) == 3 and parts[1].isdigit() and parts[2] == '--force':
                kill_process(int(parts[1]), force=True)
            else:
                console.print("[red]Usage: kill <PID> or kill <PID> --force[/red]")
        elif command == 'up':
            list_user_processes()
        elif command == 'monitor-crash' and len(parts) == 2:
            if parts[1] == 'start':
                start_monitor()
            elif parts[1] == 'stop':
                stop_monitor()
            else:
                console.print("[red]Usage: monitor-crash start|stop[/red]")
        elif command == 'cleanup':
            suggest_cleanup()
            show_and_clean_all_caches()
        elif command == 'clear':
            os.system('clear')
            animated_banner()
        elif command in ['help', 'h']:
            print_help()
        else:
            console.print("[red]Unknown command. Type 'help' to see options.[/red]")

if __name__ == "__main__":
    main()
