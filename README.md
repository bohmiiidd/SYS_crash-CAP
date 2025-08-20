```markdown

                                     # 🚨 CRASH CAP — System Memory Toolkit
                                                                    
                                      /\_/\           ___
                                     = o_o =_______    \ \  -bz7-
                                      __^      __(  \.__) )
                                (@)<_____>__(_____)_____/
```


CRASH CAP is a **Linux memory and process monitoring toolkit** designed to help users track system resources, manage processes, and control swap space efficiently.  

---

## 🔹 Features

### **System Monitoring**
- `mu` — Show memory, CPU, and disk stats  
- `top` — Show top processes by CPU/Memory  
- `users` — Show memory usage by user  
- `swap` — Swap space management  

### **Process Management**
- `pm` — Open process monitor window  
- `up` — List current user's processes  
- `mup <pid>` — Show memory usage of a process  
- `kill <pid>` — Kill process (`--force` for SIGKILL)  

### **Maintenance**
- `clean` — Clean system caches  
- `monitor` — Start/stop memory monitor  
- `clear` — Clear screen  
- `help` — Show help menu  
- `q` — Quit  

---

## 🔹 Swap Management

```

╭───────────────────────────────────────────────────────────────────────╮
│ 🔷 Swap Management Console                                            │
╰───────────────────────────────────────────────────────────────────────╯

````

**Swap Commands:**
- `check` — Check current swap status  
- `sp` — Create swap partition (interactive)  
- `sf` — Create swap file (interactive)  
- `rm` — Remove swap file  
- `help` — Show swap help  
- `q` — Return to main menu  

---

## 🖥️ Installation

1. Clone the repository:

```bash
git clone https://github.com/your-username/CRASH_CAP.git
cd CRASH_CAP
````

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the toolkit:

```bash
python3 run.py
```

---

## ⚙️ Configuration

* `config.json` contains runtime settings such as:

  * `memory_threshold` — Memory usage limit before alerts
  * `check_interval` — Interval (seconds) for monitoring

---

## 📄 License

This project is licensed under the **MIT License** — see [LICENSE.md](LICENSE.md) for details.



> CRASH CAP makes system monitoring and memory management **fast, interactive, and visual** for Linux users.
> <img width="1365" height="649" alt="image" src="https://github.com/user-attachments/assets/6048e087-7216-47d3-9a81-0483fbdbba26" />

