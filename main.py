#!/usr/bin/env python3
import subprocess
import psutil
import os
import signal
import time
import json
from rich.prompt import Confirm, Prompt
from collections import defaultdict
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.panel import Panel
from rich import box
from rich.table import Table
from pathlib import Path
import shutil
from swap_manager import SwapManager, SwapFileManager, CacheCleaner
from runtime_pid import InteractiveMonitor
import platform
import getpass
import sys

# Initialize Rich console for styling and layout
console = Console(record=True)
PID_FILE = ".memory_monitor.pid"

class CrashCap:
    def __init__(self):
        self.config = self.load_config()
        self.THRESHOLD = self.config.get("memory_threshold", 80)
        self.CHECK_INTERVAL = self.config.get("check_interval", 5)
        self.swap_mgr = SwapManager()
        self.swap_file_mgr = SwapFileManager()
        self.current_user = getpass.getuser()
        self.system_os = platform.system()
        self.cleaner = CacheCleaner()


    def animated_banner(self):
        """Display animated banner with system information"""
        console.clear()
        console.print(Panel.fit(
            f"[bold red]🚨 CRASH CAP — System Memory Toolkit[/bold red]\n"
            f"[dim]OS: {self.system_os} | User: {self.current_user}[/dim]",
            style="bold green",
            box=box.DOUBLE_EDGE
        ))
        console.print("""
    /\_/\           ___
   = o_o =_______    \ \  -bz7-
    __^      __(  \.__) )
(@)<_____>__(_____)____/
""")
        time.sleep(0.5)

    def load_config(self, path="config.json"):
        """
        Loads configuration parameters from a JSON file.
        Returns a dictionary containing settings such as memory threshold and check interval.
        
        Args:
            path (str): Path to the config JSON file (default is "config.json").
        """
        with open(path) as f:
            return json.load(f)


    def parse_swap_lines(self, lines):
        """Parse swap information with rich formatting"""
        if not lines or all(line.strip() == '' for line in lines):
            return "[yellow]⚠ No active swap found[/yellow]"

        table = Table(box=box.ROUNDED, header_style="bold magenta")
        table.add_column("Device", style="cyan")
        table.add_column("Type")
        table.add_column("Size", justify="right")
        table.add_column("Used", justify="right")
        table.add_column("Priority", justify="right")

        total_size = 0
        total_used = 0

        for line in lines:
            parts = line.split()
            if len(parts) < 5:
                continue

            try:
                # Convert size and used values from KB to MB
                size_kb = self.swap_file_mgr.parse_size_to_kib(parts[2])
                used_kb = self.swap_file_mgr.parse_size_to_kib(parts[3])
                size_mb = size_kb / 1024
                used_mb = used_kb / 1024
                total_size += size_mb
                total_used += used_mb

                table.add_row(
                    parts[0],
                    "Partition" if parts[0].startswith('/dev/') else "File",
                    f"{size_mb:.1f} MB",
                    f"{used_mb:.1f} MB",
                    parts[4]
                )
            except Exception as e:
                console.print(f"[red]⚠ Error parsing swap line: {e}[/red]")

        summary = Panel(
            f"[bold]Total Swap:[/bold] {total_size:.1f} MB | "
            f"[bold]Used:[/bold] {total_used:.1f} MB | "
            f"[bold]Free:[/bold] {total_size - total_used:.1f} MB",
            style="blue"
        )

        # Return both table and summary as a tuple for display
        return table, summary

    def check_swap_status(self):
        """
        Check if any swap is enabled and return a formatted report string.
        First try 'swapon' command; if not found, fallback to reading /proc/swaps.
        Returns a tuple (table, summary) or error string.
        """
        try:
            # Try swapon command first
            result = subprocess.run(['swapon', '--noheadings', '--raw'], capture_output=True, text=True, check=True)
            lines = result.stdout.strip().split('\n')
            return self.parse_swap_lines(lines)

        except FileNotFoundError:
            # swapon not found, fallback to /proc/swaps
            try:
                with open("/proc/swaps", "r") as f:
                    lines = f.readlines()[1:]  # skip header line
                # /proc/swaps columns: Filename Type Size Used Priority
                # Compose lines to fit parse_swap_lines expectations
                parsed_lines = []
                for line in lines:
                    parts = line.split()
                    if len(parts) < 5:
                        continue
                    parsed_line = f"{parts[0]} {parts[1]} {parts[2]} {parts[3]} {parts[4]}"
                    parsed_lines.append(parsed_line)
                return self.parse_swap_lines(parsed_lines)

            except FileNotFoundError:
                return "[red]❌ /proc/swaps not found. Are you running Linux?[/red]"
            except PermissionError:
                return "[red]❌ Permission denied reading /proc/swaps. Try running as root.[/red]"
            except Exception as e:
                return f"[red]❌ Failed to check swap status via /proc/swaps fallback: {e}[/red]"

        except subprocess.CalledProcessError:
            return "[red]❌ Failed to check swap status. Are you running on Linux?[/red]"

    def get_dir_size(self, path):
        """Calculate directory size with improved error handling"""
        total = 0
        try:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        if entry.is_file():
                            total += entry.stat().st_size
                        elif entry.is_dir():
                            total += self.get_dir_size(entry.path)
                    except (PermissionError, FileNotFoundError):
                        continue
        except (PermissionError, FileNotFoundError):
            return 0
        return total / (1024 * 1024)  # in MB

    def show_and_clean_all_caches(self):
        
        self.cleaner.show_and_clean_all_caches()
    
    def get_system_stats(self):
        """Get comprehensive system statistics"""
        stats = {}
        
        # CPU
        stats['cpu'] = psutil.cpu_percent(interval=1)
        stats['cpu_cores'] = psutil.cpu_count()
        stats['cpu_load'] = os.getloadavg()[0] if hasattr(os, 'getloadavg') else 'N/A'
        
        # Memory
        mem = psutil.virtual_memory()
        stats['mem_total'] = mem.total / (1024 ** 3)
        stats['mem_used'] = mem.used / (1024 ** 3)
        stats['mem_percent'] = mem.percent
        
        # Disk
        disk = psutil.disk_usage('/')
        stats['disk_total'] = disk.total / (1024 ** 3)
        stats['disk_used'] = disk.used / (1024 ** 3)
        stats['disk_percent'] = disk.percent
        
        return stats

    def display_system_stats(self):
        """Display system stats in a beautiful panel"""
        stats = self.get_system_stats()
        
        cpu_panel = Panel(
            f"[bold]CPU:[/bold] {stats['cpu']}% used\n"
            f"Cores: {stats['cpu_cores']} | Load: {stats['cpu_load']}",
            title="Processor",
            border_style="yellow"
        )
        
        mem_panel = Panel(
            f"[bold]Memory:[/bold] {stats['mem_percent']}% used\n"
            f"Used: {stats['mem_used']:.1f} GB / {stats['mem_total']:.1f} GB",
            title="Memory",
            border_style="cyan"
        )
        
        disk_panel = Panel(
            f"[bold]Disk:[/bold] {stats['disk_percent']}% used\n"
            f"Used: {stats['disk_used']:.1f} GB / {stats['disk_total']:.1f} GB",
            title="Storage",
            border_style="magenta"
        )
        
        console.print(cpu_panel, mem_panel, disk_panel, sep="\n")

    def memory_by_user(self):
        """Show memory usage by user in a table"""
        user_mem = defaultdict(float)
        for proc in psutil.process_iter(['username', 'memory_info']):
            try:
                mem_mb = proc.info['memory_info'].rss / 1024 ** 2
                user_mem[proc.info['username']] += mem_mb
            except (psutil.NoSuchProcess, TypeError):
                continue

        table = Table(title="Memory Usage by User", box=box.ROUNDED)
        table.add_column("User", style="green")
        table.add_column("Memory Used", justify="right")
        
        for user, mem in sorted(user_mem.items(), key=lambda x: x[1], reverse=True):
            table.add_row(user, f"{mem:.2f} MB")
            
        console.print(table)

    def get_top_processes(self, n=5, sort_by='memory'):
        """Get top processes sorted by specified metric"""
        procs = []
        attrs = ['pid', 'name', 'memory_percent', 'cpu_percent', 'username']
        
        for p in psutil.process_iter(attrs):
            try:
                procs.append(p.info)
            except psutil.NoSuchProcess:
                pass
                
        if sort_by == 'memory':
            procs.sort(key=lambda x: x['memory_percent'], reverse=True)
        else:  # cpu
            procs.sort(key=lambda x: x['cpu_percent'], reverse=True)
            
        return procs[:n]

    def display_top_processes(self, n=5):
        """Display top memory-consuming processes"""
        procs = self.get_top_processes(n)
        table = Table(title=f"Top {n} Memory Processes", box=box.ROUNDED)
        table.add_column("PID", style="cyan")
        table.add_column("Name")
        table.add_column("User")
        table.add_column("Memory %", justify="right")
        table.add_column("CPU %", justify="right")
        
        for proc in procs:
            table.add_row(
                str(proc['pid']),
                proc['name'] or '',
                proc['username'] or '',
                f"{proc['memory_percent']:.2f}",
                f"{proc['cpu_percent']:.2f}"
            )
            
        console.print(table)

    def open_process_monitor(self):
        """Open an interactive process monitor"""
        monitor = InteractiveMonitor()
        monitor.run()

    def get_process_memory(self, pid):
        """Get detailed memory info of a process"""
        try:
            proc = psutil.Process(pid)
            mem = proc.memory_info()
            console.print(f"[bold]PID {pid} - {proc.name()}[/bold]")
            console.print(f"RSS: {mem.rss / (1024**2):.2f} MB")
            console.print(f"VMS: {mem.vms / (1024**2):.2f} MB")
            console.print(f"Shared: {mem.shared / (1024**2):.2f} MB")
        except psutil.NoSuchProcess:
            console.print(f"[red]Process with PID {pid} not found.[/red]")
        except Exception as e:
            console.print(f"[red]Error retrieving process memory: {e}[/red]")

    def list_user_processes(self):
        """List all processes for the current user"""
        user = self.current_user
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'username']):
            if p.info['username'] == user:
                procs.append(p.info)

        table = Table(title=f"Processes for user {user}", box=box.ROUNDED)
        table.add_column("PID", style="cyan")
        table.add_column("Name")
        table.add_column("Username")

        for proc in procs:
            table.add_row(str(proc['pid']), proc['name'] or '', proc['username'] or '')

        console.print(table)

    def kill_process(self, pid, force=False):
        """Kill a process by PID"""
        try:
            proc = psutil.Process(pid)
            if force:
                proc.kill()
                console.print(f"[red]Process {pid} killed forcefully.[/red]")
            else:
                proc.terminate()
                console.print(f"[yellow]Process {pid} terminated.[/yellow]")
        except psutil.NoSuchProcess:
            console.print(f"[red]Process {pid} not found.[/red]")
        except Exception as e:
            console.print(f"[red]Failed to kill process {pid}: {e}[/red]")

    def print_swap_help(self):
        """Display swap management help"""
        help_text = """
    [bold]Swap Management Commands:[/bold]

    [green]check[/green]    - Check current swap status
    [green]sp[/green]       - Create swap partition (interactive)
    [green]sf[/green]       - Create swap file (interactive)
    [green]rm[/green]       - Remove swap file
    [green]help[/green]     - Show this help
    [green]q[/green]        - Return to main menu
"""
        console.print(Panel(help_text, title="Swap Help", border_style="cyan"))

    def swap_control(self):
        """Interactive swap management console"""
        self.animated_banner()
        console.print(Panel("[bold blue]🔷 Swap Management Console[/bold blue]", border_style="blue"))

        while True:
            cmd = Prompt.ask(
                "[bold cyan]Swap>[/bold cyan]",
                choices=["check", "sp", "sf", "rm", "help", "q", "clear"],
                show_choices=False
            ).lower()

            if cmd == 'q':
                break
            elif cmd == 'clear':
                console.clear()
                self.animated_banner()
                console.print(Panel("[bold blue]🔷 Swap Management Console[/bold blue]", border_style="blue"))
            elif cmd == 'help':
                self.print_swap_help()
            elif cmd == 'check':
                # Fix here: check_swap_status() returns tuple or string
                result = self.check_swap_status()
                if isinstance(result, tuple):
                    table, summary = result
                    console.print(table)
                    console.print(summary)
                else:
                    console.print(result)  # error message string
            elif cmd == 'sp':
                self.swap_mgr.run()
            elif cmd == 'sf':
                self.swap_file_mgr.create_swap_file()
            elif cmd == 'rm':
                self.swap_file_mgr.cleanup_swap_file()

    def print_main_help(self):
        """Display beautiful help menu"""
        help_text = """
[bold]CRASH CAP — Linux Memory & Process Toolkit[/bold]

[bold cyan]System Monitoring:[/bold cyan]
  [green]mu[/green]        - Show memory, CPU, and disk stats
  [green]top[/green]       - Show top processes by CPU/Memory
  [green]users[/green]     - Show memory usage by user
  [green]swap[/green]      - Swap space management

[bold cyan]Process Management:[/bold cyan]
  [green]pm[/green]        - Open process monitor window
  [green]up[/green]        - List current user's processes
  [green]mup <pid>[/green] - Show memory usage of process
  [green]kill <pid>[/green] - Kill process (add --force to SIGKILL)

[bold cyan]Maintenance:[/bold cyan]
  [green]clean[/green]     - Clean system caches
  [green]monitor[/green]   - Start/stop memory monitor
  [green]clear[/green]     - Clear screen
  [green]help[/green]      - Show this help
  [green]q[/green]         - Quit
"""
        console.print(Panel(help_text, title="Help Menu", border_style="blue"))

    def monitor_memory(self):
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
                if usage >= self.THRESHOLD:
                    notify(f"⚠️ Memory usage > {THRESHOLD}% ({usage:.1f}%)")
                time.sleep(self.CHECK_INTERVAL)
        except KeyboardInterrupt:
            pass
        finally:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)

    def start_monitor(self):
        if os.path.exists(PID_FILE):
            with open(PID_FILE) as f:
                pid = int(f.read())
            if psutil.pid_exists(pid):
                console.print(f"[bold red]Monitor already running with PID {pid}[/bold red]")
                return

        pid = os.fork()
        if pid == 0:
            self.monitor_memory()
            sys.exit(0)
        else:
            console.print(f"[green]Memory monitor started in background with PID {pid}[/green]")

    def stop_monitor(self):
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


    def main_loop(self):
        """Main interactive loop"""
        self.animated_banner()
        self.print_main_help()

        while True:
            try:
                user_input = Prompt.ask("[bold red]Command>[/bold red]").strip()
                if not user_input:
                    continue

                parts = user_input.split()
                cmd = parts[0].lower()

                if cmd == 'q':
                    break
                elif cmd == 'mu':
                    self.display_system_stats()
                elif cmd == 'top':
                    self.display_top_processes(5)
                elif cmd == 'users':
                    self.memory_by_user()
                elif cmd == 'pm':
                    self.open_process_monitor()
                    #subprocess.Popen(["xterm", "-e", "top"])
                    #continue
                elif cmd == 'mup' and len(parts) == 2 and parts[1].isdigit():
                    self.get_process_memory(int(parts[1]))
                elif cmd == 'up':
                    self.list_user_processes()
                elif cmd == 'kill':
                    if len(parts) == 2 and parts[1].isdigit():
                        self.kill_process(int(parts[1]))
                    elif len(parts) == 3 and parts[1].isdigit() and parts[2] == '--force':
                        self.kill_process(int(parts[1]), force=True)
                    else:
                        console.print("[red]Usage: kill <pid> [--force][/red]")
                elif cmd == 'swap':
                    self.swap_control()
                elif cmd == 'clean':
                    self.show_and_clean_all_caches()
                elif cmd == 'monitor':
                    if len(parts) == 1:
                        console.print("[red]Usage: monitor start|stop[/red]")
                    elif parts[1] == 'start':
                        self.start_monitor()
                    elif parts[1] == 'stop':
                        self.stop_monitor()
                elif cmd == 'clear':
                    console.clear()
                    self.animated_banner()
                elif cmd in ['help', 'h']:
                    self.print_main_help()
                else:
                    console.print("[red]Unknown command. Type 'help' for options.[/red]")

            except KeyboardInterrupt:
                if Confirm.ask("\n[red]Quit CRASH CAP?[/red]", default=False):
                    break
                else:
                    continue
            except Exception as e:
                console.print(f"[red]Error: {str(e)}[/red]")

if __name__ == "__main__":
    try:
        crash_cap = CrashCap()
        crash_cap.main_loop()
    except Exception as e:
        console.print(f"[red]Fatal error: {str(e)}[/red]")
    finally:
        console.print("\n[bold green]🚀 CRASH CAP session ended[/bold green]")
