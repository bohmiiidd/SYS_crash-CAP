import sys
import os 
import subprocess
import shutil
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.text import Text
from time import sleep
import re
import datetime
from rich.table import Table
from rich import box


console = Console()

class SwapManager:
    def __init__(self):
        self.disks = []

    def run_cmd(self, cmd, check=True):
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if check and result.returncode != 0:
            console.print(f"[bold red]Error running command:[/bold red] {cmd}")
            console.print(f"[red]{result.stderr.strip()}[/red]")
            sys.exit(1)
        return result.stdout.strip()

    def backup_partition_table(self, disk):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"/tmp/partition_table_{disk.replace('/dev/', '')}_{timestamp}.backup"
        console.print(f"Backing up partition table for [bold]{disk}[/bold] to [green]{backup_file}[/green]")
        self.run_cmd(f"sudo sfdisk --dump {disk} > {backup_file}")
        console.print("[bold green]Backup completed.[/bold green]")
        return backup_file

    def list_disks_and_partitions(self):
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            progress.add_task(description="Gathering disk and partition info...", total=None)
            sleep(1)

        lsblk_output = self.run_cmd("lsblk -o NAME,SIZE,TYPE,MODEL,MOUNTPOINT -dn")
        disks = []
        for line in lsblk_output.splitlines():
            name, size, typ, *rest = line.split(None, 4)
            if typ != "disk":
                continue
            model = rest[0] if rest else ""
            disks.append({'name': name, 'size': size, 'model': model})

        self.disks = disks

        if not disks:
            console.print("[bold yellow]No disks found on the system.[/bold yellow]")
            return

        for idx, disk in enumerate(disks, 1):
            disk_name = disk['name']
            console.print(Panel.fit(f"[bold cyan]{idx}. /dev/{disk_name}[/bold cyan] Size: [magenta]{disk['size']}[/magenta] Model: [yellow]{disk['model']}[/yellow]", title="Disk"))

            partitions = self.run_cmd(f"lsblk /dev/{disk_name} -o NAME,SIZE,TYPE,MOUNTPOINT -ln")
            for part_line in partitions.splitlines():
                pname, psize, ptype, pmount = (part_line.split(None, 3) + [""])[:4]
                if ptype == "part":
                    mount_text = f" Mounted at: [green]{pmount}[/green]" if pmount else ""
                    console.print(f"    [blue]- /dev/{pname}[/blue] Size: {psize}{mount_text}")

            console.print()

    def choose_disk(self):
        if not self.disks:
            console.print("[bold red]No disks available to select.[/bold red]")
            sys.exit(1)
        while True:
            choice = Prompt.ask("\nSelect disk by number to create swap partition on")
            if not choice.isdigit():
                console.print("[red]Please enter a valid number.[/red]")
                continue
            idx = int(choice) - 1
            if 0 <= idx < len(self.disks):
                selected = f"/dev/{self.disks[idx]['name']}"
                confirm = Confirm.ask(f"You selected [bold green]{selected}[/bold green]. Are you sure?")
                if confirm:
                    return selected
                else:
                    console.print("[yellow]Let's select again.[/yellow]")
            else:
                console.print("[red]Number out of range. Try again.[/red]")

    def validate_size(self, size_str):
        pattern = r'^\d+(\.\d+)?(MiB|GiB|M|G|MB|GB)$'
        return bool(re.match(pattern, size_str, re.IGNORECASE))

    def get_free_space_gib(self, disk):
        # Uses parted to find free unallocated space on the disk (largest free chunk in GiB)
        parted_output = self.run_cmd(f"sudo parted -m {disk} unit GiB print free")
        free_spaces = []
        for line in parted_output.splitlines():
            fields = line.split(":")
            if len(fields) >= 5 and fields[4] == "free":
                try:
                    size_gib = float(fields[3].replace("GiB", ""))
                    free_spaces.append(size_gib)
                except Exception:
                    pass
        if not free_spaces:
            return 0.0
        return max(free_spaces)

    def check_free_space(self, disk, size_str):
        try:
            num = float(re.findall(r'\d+(?:\.\d+)?', size_str)[0])
            unit = re.findall(r'(MiB|GiB|M|G|MB|GB)', size_str, re.IGNORECASE)[0].lower()
        except (IndexError, ValueError):
            return False, 0

        size_gib = num / 1024 if unit in ['m', 'mb', 'mib'] else num
        free_gib = self.get_free_space_gib(disk)

        if size_gib > free_gib:
            return False, free_gib * 1024  # return in MiB
        return True, free_gib * 1024


    def create_swap_partition(self, disk, size):
        console.print(Panel(f"[bold red]WARNING:[/bold red] This will modify the partition table on [bold]{disk}[/bold]. This can cause data loss if done incorrectly.", style="red"))
        proceed = Confirm.ask("Do you want to continue?")
        if not proceed:
            console.print("[bold yellow]Aborted by user.[/bold yellow]")
            sys.exit(0)

        backup_file = self.backup_partition_table(disk)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task(f"Creating swap partition on {disk}...", total=None)
            sleep(1)

            part_list = self.run_cmd(f"lsblk -ln -o NAME {disk}")
            parts_before = [line.strip() for line in part_list.splitlines()]

            parted_print = self.run_cmd(f"sudo parted -m {disk} unit GiB print")
            last_end = 0.0
            for line in parted_print.splitlines():
                if line.startswith("#") or line.startswith(disk):
                    continue
                fields = line.split(":")
                if len(fields) > 3:
                    try:
                        end_gib = float(fields[2].replace('GiB', ''))
                        if end_gib > last_end:
                            last_end = end_gib
                    except Exception:
                        pass

            num = float(re.findall(r'\d+(\.\d+)?', size)[0])
            unit = re.findall(r'(MiB|GiB|M|G|MB|GB)', size, re.IGNORECASE)[0].lower()
            size_gib = num / 1024 if unit in ['m', 'mb', 'mib'] else num

            start = last_end
            end = last_end + size_gib
            disk_size_bytes = int(self.run_cmd(f"lsblk -b -n -o SIZE {disk}"))
            disk_size_gib = disk_size_bytes / (1024**3)
            if end > disk_size_gib:
                progress.stop()
                console.print(f"[bold red]Error:[/bold red] Not enough space on disk for swap partition of size {size}.")
                sys.exit(1)

            cmd = f"sudo parted -s {disk} mkpart primary linux-swap {start}GiB {end}GiB"
            self.run_cmd(cmd)

            progress.update(task, description="Refreshing partition list...")
            sleep(1)

            part_list_after = self.run_cmd(f"lsblk -ln -o NAME {disk}").splitlines()
            new_parts = [p for p in part_list_after if p not in parts_before]
            if not new_parts:
                progress.stop()
                console.print("[bold red]Failed to detect new partition.[/bold red]")
                sys.exit(1)
            swap_partition = f"/dev/{new_parts[-1]}"

            console.print(f"[bold green]Created partition:[/bold green] {swap_partition}")

            progress.update(task, description="Formatting swap partition...")
            self.run_cmd(f"sudo mkswap {swap_partition}")

            progress.update(task, description="Enabling swap partition...")
            self.run_cmd(f"sudo /sbin/swapon {swap_partition}")

            progress.update(task, description="Updating /etc/fstab...")
            with open('/etc/fstab', 'r') as f:
                fstab = f.read()
            if swap_partition not in fstab:
                with open('/etc/fstab', 'a') as f:
                    f.write(f"\n{swap_partition} none swap sw 0 0\n")
                console.print(f"[bold green]Added {swap_partition} to /etc/fstab.[/bold green]")
            else:
                console.print(f"[yellow]{swap_partition} already present in /etc/fstab.[/yellow]")

            progress.update(task, description="[bold green]Swap setup complete![/bold green]")
            sleep(1)

        console.print(Panel("[bold green]Swap partition created and enabled successfully![/bold green]", style="green"))

    def run(self):
        self.list_disks_and_partitions()
        self.choose_disk_and_size_and_create()

    def choose_disk_and_size_and_create(self):
        disk = self.choose_disk()
        while True:
            size = Prompt.ask("Enter the size of the swap partition (e.g., 2GiB, 512MiB)")
            if not self.validate_size(size):
                console.print("[red]Invalid size format. Use e.g. 2GiB or 512MiB.[/red]")
                continue
            valid, free_mib = self.check_free_space(disk, size)
            if not valid:
                console.print(f"[red]Error:[/red] Not enough free space or no allocated space on {disk}. Available ~{int(free_mib)} MiB.")
                free_row = self.run_cmd(f"sudo parted -m {disk} unit MiB print free")
                console.print(f"[red]no free row find[/red]\n{free_row}\n[green]please allocate free space for the swap first [/green]")
                ch = input("(go back? y/n) # ")
                if ch.lower() == "y":
                    console.print("[blue]instead of swap partition you can swap file[/blue]")
                    return
                continue
            confirm = Confirm.ask(f"Confirm to create a swap partition of size {size} on {disk}?")
            if confirm:
                break

        self.create_swap_partition(disk, size)





class SwapFileManager:
    def __init__(self):
        self.swap_file_path = "/swapfile"
        self.size = "1G"
        self.size_bytes = 0
        self.fs_type = None
        self.debug_mode = False
        self.retry_count = 0
        self.max_retries = 2

    def debug_log(self, message):
        if self.debug_mode:
            console.print(f"[blue][DEBUG][/blue] {message}")

    def run_cmd(self, cmd, check=True, timeout=None):
        self.debug_log(f"Executing: {cmd}")
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            if result.returncode != 0:
                self.debug_log(f"Command failed (code {result.returncode}): {cmd}")
                self.debug_log(f"Stderr: {result.stderr.strip()}")
                if check:
                    console.print(f"[bold red]Error running command:[/bold red] {cmd}")
                    console.print(f"[red]{result.stderr.strip()}[/red]")
                    raise subprocess.CalledProcessError(result.returncode, cmd)
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            raise

    def validate_size(self, size_str):
        return bool(re.match(r'^\d+(\.\d+)?(MiB|GiB|M|G|MB|GB)$', size_str, re.IGNORECASE))

    def convert_to_bytes(self, size_str):
        try:
            num_match = re.findall(r'\d+(?:\.\d+)?', size_str)
            unit_match = re.findall(r'(MiB|GiB|M|G|MB|GB)', size_str, re.IGNORECASE)
            if not num_match or not unit_match:
                raise ValueError("Invalid size format.")
            num = float(num_match[0])
            unit = unit_match[0].lower()
            if unit in ['g', 'gb', 'gib']:
                return int(num * 1024**3)
            elif unit in ['m', 'mb', 'mib']:
                return int(num * 1024**2)
        except Exception as e:
            self.debug_log(f"Size conversion error: {e}")
        return 0
    @staticmethod
    def parse_size_to_kib(size_str):
        size_str = size_str.strip().upper()
        if size_str.endswith("G"):
            return int(float(size_str[:-1]) * 1024 * 1024)
        elif size_str.endswith("M"):
            return int(float(size_str[:-1]) * 1024)
        elif size_str.endswith("K"):
            return int(float(size_str[:-1]))
        elif size_str.endswith("B"):
            return 0  # 0 bytes = 0 KiB
        else:
            return int(float(size_str))  # Assume KB

    def detect_filesystem(self):
        try:
            mount_point = self.run_cmd(f"df --output=target {self.swap_file_path} | tail -1")
            fs_type = self.run_cmd(f"df -T {mount_point} | tail -1 | awk '{{print $2}}'")
            self.debug_log(f"Detected filesystem: {fs_type} for {self.swap_file_path}")
            return fs_type.lower()
        except Exception as e:
            self.debug_log(f"Filesystem detection failed: {e}")
            return "unknown"

    def verify_swap_file(self):
        try:
            output = self.run_cmd(f"file {self.swap_file_path}", check=False)
            return "swap file" in output.lower()
        except:
            return False

    def cleanup_swap_file(self):
        try:
            self.run_cmd(f"sudo swapoff {self.swap_file_path}", check=False)
        except subprocess.CalledProcessError as e:
            if "Invalid argument" in str(e):
                self.debug_log(f"swapoff not needed or invalid: {e}")
            else:
                raise
        self.run_cmd(f"sudo rm -f {self.swap_file_path}", check=False)

    def standard_swap_creation(self):
        steps = [
            ("Allocating space", f"sudo fallocate -l {self.size} {self.swap_file_path}"),
            ("Setting permissions", f"sudo chmod 0600 {self.swap_file_path}"),
            ("Formatting swap", f"sudo mkswap {self.swap_file_path}"),
            ("Enabling swap", f"sudo swapon {self.swap_file_path}")
        ]

        timeout_seconds = 30
        fallback_to_btrfs = False

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                      TimeElapsedColumn(), transient=True) as progress:
            task = progress.add_task("[cyan]Creating standard swapfile...", total=len(steps))

            for description, cmd in steps:
                progress.update(task, description=description)
                try:
                    self.debug_log(f"Executing with timeout: {cmd}")
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout_seconds)
                    if result.returncode != 0:
                        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)

                except subprocess.TimeoutExpired:
                    self.debug_log(f"Timeout exceeded for: {cmd}")
                    console.print(f"[yellow]Timeout exceeded for {description}, switching to Btrfs method...[/yellow]")
                    fallback_to_btrfs = True
                    break

                except subprocess.CalledProcessError as e:
                    if "fallocate" in cmd.lower():
                        progress.update(task, description="Allocating space (dd fallback)...")
                        try:
                            block_size = "1M"
                            block_count = int(self.size_bytes / (1024**2))
                            self.run_cmd(f"sudo dd if=/dev/zero of={self.swap_file_path} "
                                         f"bs={block_size} count={block_count} status=progress", timeout=timeout_seconds)
                        except subprocess.TimeoutExpired:
                            console.print("[yellow]DD allocation timed out, switching to Btrfs method...[/yellow]")
                            fallback_to_btrfs = True
                            break
                    else:
                        raise e

                progress.advance(task)

            if fallback_to_btrfs:
                self.cleanup_swap_file()
                self.btrfs_swap_creation()
            else:
                progress.update(task, description="[green]Swapfile ready![/green]")

    def btrfs_swap_creation(self):
        steps = [
            ("Creating empty file", f"sudo truncate -s 0 {self.swap_file_path}"),
            ("Disabling CoW", f"sudo chattr +C {self.swap_file_path}"),
            ("Allocating space", f"sudo fallocate -l {self.size} {self.swap_file_path}"),
            ("Setting permissions", f"sudo chmod 0600 {self.swap_file_path}"),
            ("Formatting swap", f"sudo mkswap {self.swap_file_path}"),
            ("Enabling swap", f"sudo swapon {self.swap_file_path}")
        ]

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                      TimeElapsedColumn(), transient=True) as progress:
            task = progress.add_task("[cyan]Creating Btrfs swapfile...", total=len(steps))

            for description, cmd in steps:
                progress.update(task, description=description)
                try:
                    self.run_cmd(cmd)
                except subprocess.CalledProcessError as e:
                    if "swapon" in cmd and "Invalid argument" in str(e):
                        if self.retry_count < self.max_retries:
                            self.retry_count += 1
                            self.debug_log(f"Retrying swap creation ({self.retry_count})...")
                            self.cleanup_swap_file()
                            return self.btrfs_swap_creation()
                        else:
                            console.print("[red]Maximum retries reached. Swap creation failed.[/red]")
                            raise
                    raise
                progress.advance(task)

            progress.update(task, description="[green]Swapfile ready![/green]")

    def update_fstab(self):
        try:
            with open('/etc/fstab', 'r') as f:
                fstab = f.read()
            if self.swap_file_path not in fstab:
                with open('/etc/fstab', 'a') as f:
                    f.write(f"\n{self.swap_file_path} none swap sw 0 0\n")
                return "Added"
            return "Already present"
        except Exception as e:
            self.debug_log(f"Failed to update fstab: {e}")
            if "Permission denied" in str(e):
                console.print("[red]Permission denied while writing /etc/fstab. Try running with sudo.[/red]")
            return "Failed"

    def ask_user_inputs(self):
        console.print(Panel("[bold cyan]Swap File Configuration[/bold cyan]"))
        self.swap_file_path = Prompt.ask("Enter swap file path", default="/swapfile")
        self.debug_mode = Confirm.ask("Enable debug mode?", default=False)
        self.size = Prompt.ask("Enter swap size (e.g., 1G, 512M)", default="1G")
        while not self.validate_size(self.size):
            console.print("[red]Invalid size format. Examples: 1G, 512M, 2GiB[/red]")
            self.size = Prompt.ask("Enter swap size")

        self.size_bytes = self.convert_to_bytes(self.size)
        if self.size_bytes < 64 * 1024**2:
            console.print("[red]Size too small (minimum 64MB)[/red]")
            sys.exit(1)

        self.fs_type = self.detect_filesystem()
        console.print(f"[yellow]Detected filesystem: {self.fs_type}[/yellow]")

    def create_swap_file(self):
        try:
            self.ask_user_inputs()

            console.print(Panel(
                f"[bold]Swap File Path:[/bold] {self.swap_file_path}\n"
                f"[bold]Size:[/bold] {self.size}\n"
                f"[bold]Filesystem:[/bold] {self.fs_type}",
                title="[cyan]Swap Configuration Summary[/cyan]"
            ))

            if os.path.exists(self.swap_file_path):
                if self.verify_swap_file():
                    console.print("[green]Valid swap file already exists.[/green]")
                    if not Confirm.ask("Recreate swap file?"):
                        return
                else:
                    console.print("[yellow]Existing file is not a valid swap file[/yellow]")
                self.cleanup_swap_file()

            try:
                if self.fs_type == "btrfs":
                    console.print("[yellow]Using Btrfs-specific swap creation method[/yellow]")
                    self.btrfs_swap_creation()
                else:
                    console.print("[yellow]Using standard swap creation method[/yellow]")
                    self.standard_swap_creation()
            except subprocess.CalledProcessError as e:
                if "swapon" in str(e.cmd).lower() and e.returncode == 255:
                    self.debug_log("Swapon failed with code 255 — initiating Btrfs-style creation as fallback")
                    console.print("[red]swapon failed with exit code 255.[/red]\n[green]Retrying with Btrfs-specific method...[/green]")
                    self.cleanup_swap_file()
                    self.btrfs_swap_creation()
                else:
                    raise e

            fstab_status = self.update_fstab()
            if fstab_status == "Failed":
                console.print("[yellow]You can manually add this line to /etc/fstab:[/yellow]")
                console.print(f"[cyan]{self.swap_file_path} none swap sw 0 0[/cyan]")

            console.print(Panel(
                f"[bold green]✓ Swap creation successful![/bold green]\n"
                f"[bold]Path:[/bold] {self.swap_file_path}\n"
                f"[bold]Size:[/bold] {self.size}\n"
                f"[bold]Filesystem:[/bold] {self.fs_type}\n"
                f"[bold]fstab:[/bold] {fstab_status}\n\n"
                f"[yellow]Verify with:[/yellow] [cyan]swapon --show[/cyan]\n"
                f"[yellow]Check usage:[/yellow] [cyan]free -h[/cyan]",
                title="[green]Swap File Status[/green]",
                border_style="green"
            ))

        except Exception as e:
            console.print(Panel(
                f"[bold red]✗ Swap creation failed![/bold red]\n"
                f"[red]Error: {str(e)}[/red]\n\n"
                f"[yellow]You can try:[/yellow]\n"
                f"1. Check disk space with [cyan]df -h[/cyan]\n"
                f"2. Verify filesystem supports swap files\n"
                f"3. Try manual creation with:\n"
                f"   [cyan]sudo fallocate -l {self.size} {self.swap_file_path}\n"
                f"   sudo chmod 600 {self.swap_file_path}\n"
                f"   sudo mkswap {self.swap_file_path}\n"
                f"   sudo swapon {self.swap_file_path}[/cyan]",
                title="[red]Error[/red]",
                border_style="red"
            ))
            sys.exit(1)



class CacheCleaner:
    def __init__(self):
        self.current_user = os.getenv('USER')
        self.home_dir = os.path.expanduser('~')

    def get_dir_size(self, path):
        """Calculate directory size in MB with error handling"""
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
        return total / (1024 * 1024)  # Convert to MB

    def clean_directory(self, path, name, use_sudo=False):
        """Safely clean a directory with progress feedback"""
        try:
            if use_sudo:
                # Create temp cleanup script for sudo
                temp_script = '/tmp/cache_cleaner.sh'
                with open(temp_script, 'w') as f:
                    f.write(f"""#!/bin/bash
# Safe directory cleaner
for item in {path}/*; do
    if [[ -f "$item" || -L "$item" ]]; then
        rm -f "$item"
    elif [[ -d "$item" ]]; then
        rm -rf "$item"
    fi
done
""")
                os.chmod(temp_script, 0o700)
                subprocess.run(['sudo', temp_script], check=True)
                os.remove(temp_script)
            else:
                # Normal cleaning
                for item in os.listdir(path):
                    item_path = os.path.join(path, item)
                    try:
                        if os.path.isfile(item_path) or os.path.islink(item_path):
                            os.remove(item_path)
                        elif os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                    except Exception as e:
                        console.print(f"  [yellow]⚠ Couldn't delete {item_path}: {str(e)}[/yellow]")
                        continue
            
            console.print(f"  [green]✔ Cleaned {name}[/green]")
            return True
        except Exception as e:
            console.print(f"  [red]✖ Failed to clean {name}: {str(e)}[/red]")
            return False

    def clean_journal_logs(self, use_sudo=False):
        """Special handling for journal logs"""
        try:
            if use_sudo:
                subprocess.run(['sudo', 'journalctl', '--vacuum-size=100M'], check=True)
            else:
                subprocess.run(['journalctl', '--vacuum-size=100M'], check=True)
            console.print("  [green]✔ Rotated journal logs[/green]")
            return True
        except Exception as e:
            console.print(f"  [red]✖ Failed to rotate journal logs: {str(e)}[/red]")
            return False

    def show_and_clean_all_caches(self, force=False):
        """Main cache cleaning interface"""
        # Define all cache locations with metadata
        caches = {
            "System Cache": {
                "path": "/var/cache",
                "system": True,
                "dangerous": False,
                "special_handler": None
            },
            "APT Cache": {
                "path": "/var/lib/apt/lists",
                "system": True,
                "dangerous": True,
                "special_handler": None,
                "warning": "Running 'apt update' afterwards is recommended"
            },
            "User Cache": {
                "path": f"{self.home_dir}/.cache",
                "system": False,
                "dangerous": False,
                "special_handler": None
            },
            "Pip Cache": {
                "path": f"{self.home_dir}/.cache/pip",
                "system": False,
                "dangerous": False,
                "special_handler": None
            },
            "Thumbnail Cache": {
                "path": f"{self.home_dir}/.cache/thumbnails",
                "system": False,
                "dangerous": False,
                "special_handler": None
            },
            "Journal Logs": {
                "path": "/var/log/journal",
                "system": True,
                "dangerous": True,
                "special_handler": self.clean_journal_logs,
                "warning": "Only rotates logs, doesn't delete system logs"
            },
            "Docker Cache": {
                "path": "/var/lib/docker",
                "system": True,
                "dangerous": True,
                "special_handler": None,
                "warning": "May affect running containers"
            }
        }

        # Scan phase
        console.print(Panel("[bold]🔍 Scanning Cache Locations[/bold]", style="blue"))
        scan_results = {}
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            transient=True
        ) as progress:
            task = progress.add_task("Scanning...", total=len(caches))
            
            for name, info in caches.items():
                path = info["path"]
                result = {
                    "exists": False,
                    "size": 0,
                    "accessible": False,
                    "writable": False,
                    "needs_sudo": False,
                    "error": None
                }
                
                if not os.path.exists(path):
                    result["error"] = "Path does not exist"
                    scan_results[name] = result
                    progress.update(task, advance=1)
                    continue
                    
                result["exists"] = True
                
                try:
                    # Check permissions
                    result["accessible"] = os.access(path, os.R_OK)
                    result["writable"] = os.access(path, os.W_OK)
                    result["needs_sudo"] = info["system"] and not result["writable"]
                    
                    # Get size if readable
                    if result["accessible"]:
                        result["size"] = self.get_dir_size(path)
                        
                except Exception as e:
                    result["error"] = str(e)
                
                scan_results[name] = result
                progress.update(task, advance=1)

        # Display results
        table = Table(title="Cache Analysis", box=box.ROUNDED)
        table.add_column("Cache", style="cyan")
        table.add_column("Size", justify="right")
        table.add_column("Status")
        table.add_column("Notes", style="dim")

        total_size = 0
        needs_sudo = False
        
        for name, result in scan_results.items():
            notes = []
            meta = caches[name]
            
            if result["error"]:
                size_text = "N/A"
                status = f"[red]Error: {result['error']}[/red]"
            elif not result["exists"]:
                size_text = "N/A"
                status = "[yellow]Not present[/yellow]"
            else:
                if result["size"] > 0:
                    size_text = f"{result['size']:.2f} MB"
                    total_size += result["size"]
                else:
                    size_text = "0 MB"
                    
                if not result["accessible"]:
                    status = "[red]No Access[/red]"
                elif not result["writable"]:
                    status = "[yellow]Read Only[/yellow]"
                    if result["needs_sudo"]:
                        notes.append("Requires sudo")
                        needs_sudo = True
                else:
                    status = "[green]Writable[/green]"
                    
                if meta["dangerous"]:
                    notes.append("[red]⚠ Caution[/red]")
                if "warning" in meta:
                    notes.append(f"[yellow]{meta['warning']}[/yellow]")
                    
            table.add_row(
                name,
                size_text,
                status,
                "\n".join(notes) if notes else ""
            )

        console.print(table)
        console.print(f"\n[bold]Total cache size: [green]{total_size:.2f} MB[/green][/bold]")

        # Determine what we can clean
        cleanable = []
        for name, result in scan_results.items():
            if result["exists"] and result["accessible"] and (result["writable"] or (force and result["needs_sudo"])):
                cleanable.append((name, caches[name], result["needs_sudo"]))

        if not cleanable:
            console.print("\n[yellow]No caches available for cleaning with current permissions.[/yellow]")
            if needs_sudo:
                console.print("[yellow]Use --force flag to attempt sudo cleanup[/yellow]")
            return

        # Show cleanup plan
        console.print("\n[bold]The following caches will be cleaned:[/bold]")
        for name, info, needs_sudo in cleanable:
            sudo_note = "[yellow] (with sudo)[/yellow]" if needs_sudo and force else ""
            danger_note = "[red] (DANGEROUS)[/red]" if info["dangerous"] else ""
            console.print(f"  - {name}{sudo_note}{danger_note}")

        if needs_sudo and force:
            console.print("\n[bold yellow]⚠ WARNING: Will attempt sudo operations[/bold yellow]")

        if not Confirm.ask("\n[bold]Proceed with cleanup?[/bold]", default=False):
            console.print("[yellow]Cleanup cancelled.[/yellow]")
            return

        # Cleaning phase
        console.print(Panel("[bold]🧹 Cleaning Caches[/bold]", style="blue"))
        cleaned_count = 0
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            transient=True
        ) as progress:
            task = progress.add_task("Cleaning...", total=len(cleanable))
            
            for name, info, needs_sudo in cleanable:
                use_sudo = needs_sudo and force
                
                if info["special_handler"]:
                    success = info["special_handler"](use_sudo)
                else:
                    success = self.clean_directory(info["path"], name, use_sudo)
                
                if success:
                    cleaned_count += 1
                progress.update(task, advance=1)

        # Summary
        console.print(f"\n[bold green]✅ Successfully cleaned {cleaned_count}/{len(cleanable)} locations[/bold green]")
        
        # Post-clean advice
        if any(info["dangerous"] for _, info, _ in cleanable):
            console.print("\n[bold yellow]⚠ WARNING: Some cleaned caches may require follow-up actions[/bold yellow]")
            console.print("[yellow]Consider running system maintenance commands if needed[/yellow]")






