# CRASH CAP — Memory Crash Capture & Control Panel

🚨 **CRASH CAP** is a terminal-based tool to monitor and manage system memory usage, processes, and caches on Linux systems. It provides real-time stats, alerts on high memory usage, process management commands, and easy cache cleanup — all with an interactive colorful console interface

---

## Features

- Display detailed memory and CPU usage statistics
- Show memory usage aggregated by user
- List top memory-consuming processes and suggest cleanup
- Kill processes gracefully or forcefully by PID
- Monitor memory usage continuously in the background with desktop notifications
- Display and clean various system and user caches safely
- Launch a process monitor in a new terminal window
- Interactive console with colored prompts, animations, and progress spinners

---

## Installation

1. Clone this repository:

   ```bash
   git clone https://github.com/yourusername/crash-cap.git
   cd crash-cap
2. install requirements packages and run :
   ```bash
   pip3 install requirements.txt
   python3 crashcap.py
   ```
3. (Optional) Adjust settings in config.json for memory threshold and check interval.
Configuration

You can customize memory monitoring thresholds and intervals in config.json:
```json
{
  "memory_threshold": 80,
  "check_interval": 5
}
```
memory_threshold: Percentage of memory usage to trigger alerts

check_interval: Seconds between memory usage checks when monitoring

Requirements

    Python 3.7+

    psutil

    rich

    Linux OS (requires /proc filesystem for some functions)

    notify-send command available for desktop notifications (usually via libnotify-bin package)
Notes

    Some cache cleanup operations require root permissions. Run the script with sudo if you encounter permission errors.

    The process monitor launches in xterm — ensure xterm is installed or modify the script to use your preferred terminal emulator.
License

This project is licensed under the MIT License. See the LICENSE file for details.
Author

    Developed by Ahmed Abd

    GitHub: bohmiiidd

    Feel free to open issues or contribute via pull requests.

<img width="1190" height="678" alt="image" src="https://github.com/user-attachments/assets/00e75c29-7de8-4dff-9d2f-8fed2aaff162" />
Contribution

Contributions, bug reports, and feature requests are welcome! Please fork the repository and create a pull request.

