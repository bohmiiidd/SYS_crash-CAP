#!/usr/bin/env python3
import urwid
import psutil
import time
import threading
import signal
from datetime import datetime

class InteractiveMonitor:
    def __init__(self):
        self.refresh_rate = 2
        self.process_list = []
        self.filter_text = ""
        self.lock = threading.Lock()
        self.offset = 0
        self.max_rows = 20
        self.running = True
        self.start_time = time.time()
        self.sort_column = 'cpu'  # Default sort column
        self.sort_reverse = True  # Default sort order (descending)
        self.selected_pid = None
        self.last_update = time.time()

        # Color palette
        self.palette = [
        ('body', 'light green', 'black'),
        ('header', 'light red,bold', 'black'),
        ('highlight', 'black', 'light green'),
        ('cpu', 'dark green,bold', 'black'),
        ('mem', 'dark magenta,bold', 'black'),
        ('user', 'yellow,bold', 'black'),
        ('pid', 'light red,bold', 'black'),
        ('name', 'light gray', 'black'),
        ('stats', 'light green', 'black'),
        ('table_header_bg', 'light gray', 'black'),
        ('table_header_pid', 'light red,bold', 'black'),
        ('table_header_cpu', 'dark green,bold', 'black'),
        ('table_header_mem', 'dark magenta,bold', 'black'),
        ('table_header_runtime', 'yellow,bold', 'black'),
        ('table_header_user', 'yellow,bold', 'black'),
        ('table_header_name', 'white,bold', 'black'),
        ('separator', 'dark gray', 'black'),
        ('selected', 'black', 'light green'),
        ('critical', 'black,bold', 'dark red'),
        ('warning', 'black,bold', 'yellow'),
        ('ok', 'black,bold', 'dark green'),
        ('footer', 'light red,bold', 'black'),
        ('key', 'light cyan,bold', 'black'),
    ]




        # Header and footer
        self.header = urwid.Text(('header', "[ P R O C ]  [ M O N ]"), align='center')
        self.sys_stats = urwid.Text("", align='center')
        self.filter_label = urwid.Text("")
        self.footer = urwid.Text(('footer', " [q] Quit  [↑↓] Scroll  [←→] Sort  [/] Filter  [c] Clear  [r] Rate  [k] Kill "), align='center')

        # Table header with columns
        self.table_header = urwid.Columns([
            ('weight', 1, urwid.AttrMap(urwid.Text(" PID ", align='right'), 'table_header_pid')),
            ('weight', 1, urwid.AttrMap(urwid.Text(" CPU% ", align='right'), 'table_header_cpu')),
            ('weight', 1, urwid.AttrMap(urwid.Text(" MEM% ", align='right'), 'table_header_mem')),
            ('weight', 2, urwid.AttrMap(urwid.Text(" RUNTIME ", align='right'), 'table_header_runtime')),
            ('weight', 2, urwid.AttrMap(urwid.Text(" USER ", align='left'), 'table_header_user')),
            ('weight', 5, urwid.AttrMap(urwid.Text(" NAME ", align='left'), 'table_header_name')),
        ], dividechars=1)

        # Process rows container
        self.process_walker = urwid.SimpleFocusListWalker([])
        self.process_box = urwid.ListBox(self.process_walker)

        # Box around table for better design
        self.table_box = urwid.LineBox(
        self.process_box,
        title="⚡ PROCESSES ⚡",
        tlcorner='╔', tline='═', lline='║',
        trcorner='╗', rline='║',
        blcorner='╚', bline='═', brcorner='╝'
    )


        self.top_pile = urwid.Pile([
            ('pack', self.header),
            ('pack', self.sys_stats),
            ('pack', self.filter_label),
            ('pack', self.table_header),
            ('weight', 1, self.table_box),
            ('pack', self.footer),
        ])

        self.frame = urwid.Frame(
            body=urwid.AttrMap(self.top_pile, 'body'),
            footer=self.footer
        )

        # Start background update thread
        self.update_thread = threading.Thread(target=self.update_process_list_loop, daemon=True)
        self.update_thread.start()

        self.loop = urwid.MainLoop(
            self.frame,
            unhandled_input=self.handle_input,
            palette=self.palette
        )

        # Handle terminal resize
        signal.signal(signal.SIGWINCH, self.handle_resize)

    def handle_resize(self, signum, frame):
        self.loop.screen_size = None
        self.loop.draw_screen()

    def format_uptime(self, seconds):
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)
        if d > 0:
            return f"{d}d {h:02}h"
        return f"{h:02}:{m:02}:{s:02}"

    def get_process_runtime(self, create_time):
        if create_time is None:
            return "N/A"
        now = time.time()
        return self.format_uptime(now - create_time)

    def update_process_list_loop(self):
        while self.running:
            self.update_process_list()
            time.sleep(self.refresh_rate)

    def update_process_list(self):
        with self.lock:
            self.last_update = time.time()
            
            # Update system stats
            uptime = time.time() - self.start_time
            cpu_percent = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            ram_percent = mem.percent
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent

            stats_text = [
                ('stats', f" Uptime: {self.format_uptime(uptime)} "),
                ('separator', "│"),
                ('cpu', f" CPU: {cpu_percent:.1f}% "),
                ('separator', "│"),
                ('mem', f" RAM: {ram_percent:.1f}% "),
                ('separator', "│"),
                ('stats', f" Disk: {disk_percent:.1f}% "),
                ('separator', "│"),
                ('stats', f" Processes: {len(psutil.pids())} "),
            ]
            self.sys_stats.set_text(stats_text)

            # Update process list
            processes = []
            for p in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent', 'create_time']):
                try:
                    if not self.filter_text or (p.info['name'] and self.filter_text.lower() in p.info['name'].lower()):
                        processes.append(p.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # Sort processes
            if self.sort_column == 'cpu':
                self.process_list = sorted(processes, key=lambda p: p['cpu_percent'], reverse=self.sort_reverse)
            elif self.sort_column == 'mem':
                self.process_list = sorted(processes, key=lambda p: p['memory_percent'], reverse=self.sort_reverse)
            elif self.sort_column == 'pid':
                self.process_list = sorted(processes, key=lambda p: p['pid'], reverse=self.sort_reverse)
            elif self.sort_column == 'name':
                self.process_list = sorted(processes, key=lambda p: p['name'].lower() if p['name'] else "", reverse=self.sort_reverse)
            elif self.sort_column == 'user':
                self.process_list = sorted(processes, key=lambda p: p['username'].lower() if p['username'] else "", reverse=self.sort_reverse)
            elif self.sort_column == 'runtime':
                self.process_list = sorted(processes, key=lambda p: p.get('create_time', 0), reverse=self.sort_reverse)
        
        self.refresh_display()

    def format_process_row(self, p, is_selected=False):
        runtime = self.get_process_runtime(p.get('create_time'))
        cpu_percent = p.get('cpu_percent', 0)
        mem_percent = p.get('memory_percent', 0)
        
        # Apply color based on resource usage
        cpu_attr = 'critical' if cpu_percent > 70 else 'warning' if cpu_percent > 30 else 'cpu'
        mem_attr = 'critical' if mem_percent > 70 else 'warning' if mem_percent > 30 else 'mem'
        
        if is_selected:
            row_attr = 'selected'
            cpu_attr = row_attr
            mem_attr = row_attr
            pid_attr = row_attr
            user_attr = row_attr
            name_attr = row_attr
        else:
            pid_attr = 'pid'
            user_attr = 'user'
            name_attr = 'name'
        
        columns = urwid.Columns([
            ('weight', 1, urwid.Text((pid_attr, f"{p['pid']:>6}"), align='right')),
            ('weight', 1, urwid.Text((cpu_attr, f"{cpu_percent:>5.1f}%"), align='right')),
            ('weight', 1, urwid.Text((mem_attr, f"{mem_percent:>5.1f}%"), align='right')),
            ('weight', 2, urwid.Text(('mem', runtime), align='right')),
            ('weight', 2, urwid.Text((user_attr, f"{(p['username'] or '')[:12]:<12}"), align='left')),
            ('weight', 5, urwid.Text((name_attr, f"{p['name'] or ''}"), align='left')),
        ], dividechars=1)
        
        if is_selected:
            return urwid.AttrMap(columns, 'selected')
        return columns

    def refresh_display(self):
        with self.lock:
            body = self.process_walker
            body.clear()

            visible_procs = self.process_list[self.offset:self.offset+self.max_rows]
            for idx, p in enumerate(visible_procs):
                is_selected = (p['pid'] == self.selected_pid)
                row = self.format_process_row(p, is_selected)
                body.append(row)
                # Add separator line except after last row
                if idx != len(visible_procs) -1:
                    body.append(urwid.AttrMap(urwid.Divider('-'), 'separator'))

            filter_text = f" Filter: '{self.filter_text}' " if self.filter_text else " Filter: None "
            sort_text = f" Sort: {self.sort_column} {'↓' if self.sort_reverse else '↑'} "
            
            footer_parts = [
                ('footer', f" {datetime.now().strftime('%H:%M:%S')} "),
                ('separator', "│"),
                ('footer', filter_text),
                ('separator', "│"),
                ('footer', sort_text),
                ('separator', "│"),
                ('footer', f" Refresh: {self.refresh_rate}s "),
                ('separator', "│"),
                ('footer', f" Processes: {len(self.process_list)}/{len(psutil.pids())} "),
            ]
            
            self.filter_label.set_text(footer_parts)



    def handle_input(self, key):
        if key == 'q':
            self.running = False
            raise urwid.ExitMainLoop()
        elif key == 'up':
            self.offset = max(0, self.offset - 1)
            self.selected_pid = None
            self.refresh_display()
        elif key == 'down':
            if self.offset + self.max_rows < len(self.process_list):
                self.offset += 1
                self.selected_pid = None
                self.refresh_display()
        elif key == 'page up':
            self.offset = max(0, self.offset - self.max_rows)
            self.selected_pid = None
            self.refresh_display()
        elif key == 'page down':
            self.offset = min(max(0,len(self.process_list) - self.max_rows), self.offset + self.max_rows)
            self.selected_pid = None
            self.refresh_display()
        elif key == 'left':
            # Cycle sort columns backward
            columns = ['pid', 'cpu', 'mem', 'runtime', 'user', 'name']
            idx = columns.index(self.sort_column)
            self.sort_column = columns[idx-1 if idx > 0 else len(columns)-1]
            self.update_process_list()
        elif key == 'right':
            # Cycle sort columns forward
            columns = ['pid', 'cpu', 'mem', 'runtime', 'user', 'name']
            idx = columns.index(self.sort_column)
            self.sort_column = columns[(idx+1) % len(columns)]
            self.update_process_list()
        elif key == '/':
            self.open_filter_popup()
        elif key == 'c':
            self.filter_text = ""
            self.offset = 0
            self.update_process_list()
        elif key == 'r':
            self.open_refresh_popup()
        elif key == 'enter':
            if self.selected_pid is not None:
                self.open_process_details()
        elif key == 'k':
            if self.selected_pid is not None:
                self.kill_process()
        elif key in ('1', '2', '3', '4', '5', '6'):
            columns = ['pid', 'cpu', 'mem', 'runtime', 'user', 'name']
            selected_col = columns[int(key)-1]
            if self.sort_column == selected_col:
                self.sort_reverse = not self.sort_reverse
            else:
                self.sort_column = selected_col
                self.sort_reverse = True
            self.update_process_list()
        else:
            # Handle selection with number keys
            try:
                num = int(key)
                if 1 <= num <= len(self.process_walker) // 2 + 1:
                    idx = num - 1
                    if idx < len(self.process_list[self.offset:self.offset+self.max_rows]):
                        self.selected_pid = self.process_list[self.offset + idx]['pid']
                        self.refresh_display()
            except ValueError:
                pass

    def open_filter_popup(self):
        edit = urwid.Edit(" Filter: ", edit_text=self.filter_text)
        apply_button = urwid.Button("Apply")
        cancel_button = urwid.Button("Cancel")

        def on_apply(button):
            self.filter_text = edit.edit_text.strip()
            self.offset = 0
            self.update_process_list()
            self.loop.widget = self.frame

        def on_cancel(button):
            self.loop.widget = self.frame

        urwid.connect_signal(apply_button, 'click', on_apply)
        urwid.connect_signal(cancel_button, 'click', on_cancel)

        pile = urwid.Pile([
            urwid.Divider(),
            edit,
            urwid.Divider(),
            urwid.Columns([apply_button, cancel_button], dividechars=2, focus_column=0)
        ])

        fill = urwid.Filler(pile)
        overlay = urwid.Overlay(fill, self.frame,
                              align='center', width=('relative', 60),
                              valign='middle', height=7)
        self.loop.widget = overlay
        # Focus the Edit widget after popup shows
        def set_focus(loop, user_data):
            loop.widget.base_widget.focus_position = 1

        self.loop.set_alarm_in(0, set_focus)


    def open_refresh_popup(self):
        edit = urwid.Edit(" Refresh rate (seconds): ", edit_text=str(self.refresh_rate))
        apply_button = urwid.Button("Apply")
        cancel_button = urwid.Button("Cancel")

        def on_apply(button):
            try:
                rate = int(edit.edit_text.strip())
                if 0 < rate <= 300:  # Limit to 5 minutes max
                    self.refresh_rate = rate
            except ValueError:
                pass
            self.loop.widget = self.frame

        def on_cancel(button):
            self.loop.widget = self.frame

        urwid.connect_signal(apply_button, 'click', on_apply)
        urwid.connect_signal(cancel_button, 'click', on_cancel)

        pile = urwid.Pile([
            urwid.Divider(),
            edit,
            urwid.Divider(),
            urwid.Columns([apply_button, cancel_button], dividechars=2, focus_column=0)
        ])

        fill = urwid.Filler(pile)
        overlay = urwid.Overlay(fill, self.frame,
                              align='center', width=('relative', 60),
                              valign='middle', height=7)
        self.loop.widget = overlay
        # Focus the Edit widget after popup shows
        def set_focus(loop, user_data):
            loop.widget.base_widget.focus_position = 1

        self.loop.set_alarm_in(0, set_focus)


    def open_process_details(self):
        if not self.selected_pid:
            return

        try:
            p = psutil.Process(self.selected_pid)
            with p.oneshot():
                details = [
                    f"PID: {p.pid}",
                    f"Name: {p.name()}",
                    f"Status: {p.status()}",
                    f"User: {p.username()}",
                    f"CPU: {p.cpu_percent():.1f}%",
                    f"Memory: {p.memory_percent():.1f}%",
                    f"Threads: {p.num_threads()}",
                    f"Created: {datetime.fromtimestamp(p.create_time()).strftime('%Y-%m-%d %H:%M:%S')}",
                    f"Runtime: {self.get_process_runtime(p.create_time())}",
                    f"Exe: {p.exe()}",
                    f"Cmdline: {' '.join(p.cmdline())}" if p.cmdline() else "",
                ]
        except psutil.NoSuchProcess:
            details = ["Process no longer exists"]

        close_button = urwid.Button("Close")
        urwid.connect_signal(close_button, 'click', lambda button: setattr(self.loop, 'widget', self.frame))

        pile = urwid.Pile([
            urwid.Text("\n".join(details)),
            urwid.Divider(),
            close_button
        ])

        fill = urwid.Filler(pile)
        overlay = urwid.Overlay(fill, self.frame,
                              align='center', width=('relative', 80),
                              valign='middle', height=('relative', 80))
        self.loop.widget = overlay

    def kill_process(self):
        if not self.selected_pid:
            return

        text = urwid.Text(f"Kill process {self.selected_pid}?")
        yes_button = urwid.Button("Yes")
        no_button = urwid.Button("No")

        def on_yes(button):
            try:
                p = psutil.Process(self.selected_pid)
                p.terminate()
            except psutil.NoSuchProcess:
                pass
            self.loop.widget = self.frame
            self.update_process_list()

        def on_no(button):
            self.loop.widget = self.frame

        urwid.connect_signal(yes_button, 'click', on_yes)
        urwid.connect_signal(no_button, 'click', on_no)

        pile = urwid.Pile([
            text,
            urwid.Divider(),
            urwid.Columns([yes_button, no_button], dividechars=2, focus_column=0)
        ])

        fill = urwid.Filler(pile)
        overlay = urwid.Overlay(fill, self.frame,
                              align='center', width=('relative', 50),
                              valign='middle', height=7)
        self.loop.widget = overlay



    def run(self):
        self.loop.run()

if __name__ == '__main__':
    ProcessMonitor().run()
