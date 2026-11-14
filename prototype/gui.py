"""Minimal Chinese serial GUI. All filesystem/cleaning work runs off Tk's thread."""
from __future__ import annotations

import argparse
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from prototype.batch import BatchEvent, run


INCREMENTAL_NOTE = '检查变化需完整读盘计算源文件及历史副本的 SHA-256；未变化不等于零耗时。'


class CleanerWindow(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=24)
        self.input_path = tk.StringVar(master)
        self.output_path = tk.StringVar(master)
        self.recursive = tk.BooleanVar(master, True)
        self.phase = tk.StringVar(master, '就绪')
        self.current_file = tk.StringVar(master, '尚未开始')
        self.report_path = tk.StringVar(master)
        self.summary = tk.StringVar(master, INCREMENTAL_NOTE)
        self._messages: queue.Queue[BatchEvent] = queue.Queue()
        self._running = False
        self._stop = threading.Event()
        self._rows: dict[str, dict[str, Any]] = {}
        self._poll_id: str | None = None
        self._build()
        self._poll_id = self.after(40, self._poll)

    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(8, weight=1)
        ttk.Label(self, text='PSD Batch Cleaner', style='Title.TLabel').grid(row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(self, text='PSD / PSB 批量瘦身 · 保留原稿 · 不调用 Photoshop').grid(row=1, column=0, columnspan=3, sticky='w', pady=(4, 22))
        ttk.Label(self, text='输入目录').grid(row=2, column=0, sticky='w', padx=(0, 14))
        self.input_entry = ttk.Entry(self, textvariable=self.input_path)
        self.input_entry.grid(row=2, column=1, sticky='ew', pady=6)
        self.input_browse = ttk.Button(self, text='浏览…', command=lambda: self._browse(self.input_path, True))
        self.input_browse.grid(row=2, column=2, padx=(12, 0))
        ttk.Label(self, text='输出目录').grid(row=3, column=0, sticky='w', padx=(0, 14))
        self.output_entry = ttk.Entry(self, textvariable=self.output_path)
        self.output_entry.grid(row=3, column=1, sticky='ew', pady=6)
        self.output_browse = ttk.Button(self, text='浏览…', command=lambda: self._browse(self.output_path, False))
        self.output_browse.grid(row=3, column=2, padx=(12, 0))
        bar = ttk.Frame(self)
        bar.grid(row=4, column=0, columnspan=3, sticky='ew', pady=(16, 8))
        self.start_button = ttk.Button(bar, text='开始瘦身', style='Accent.TButton', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(bar, text='安全停止', command=self.request_stop, state='disabled')
        self.stop_button.pack(side='left', padx=(8, 0))
        self.recursive_check = ttk.Checkbutton(bar, text='包含子文件夹', variable=self.recursive)
        self.recursive_check.pack(side='left', padx=(12, 0))
        ttk.Label(bar, textvariable=self.phase).pack(side='left', padx=18, fill='x', expand=True)
        self.progress = ttk.Progressbar(bar, mode='indeterminate', length=180)
        self.progress.pack(side='right')
        ttk.Entry(self, textvariable=self.current_file, state='readonly').grid(row=5, column=0, columnspan=3, sticky='ew', pady=4)
        ttk.Label(self, textvariable=self.summary, wraplength=900).grid(row=6, column=0, columnspan=3, sticky='ew', pady=6)
        ttk.Label(self, text='结果（选择文件查看完整路径与错误）').grid(row=7, column=0, columnspan=3, sticky='w', pady=(8, 4))
        table = ttk.Frame(self)
        table.grid(row=8, column=0, columnspan=3, sticky='nsew')
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.results = ttk.Treeview(table, columns=('status', 'source', 'output'), show='headings', height=7)
        for key, title, width in [('status', '结果', 100), ('source', '输入文件', 330), ('output', '输出位置（含历史副本）', 400)]:
            self.results.heading(key, text=title)
            self.results.column(key, width=width, minwidth=80)
        self.results.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(table, orient='vertical', command=self.results.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(table, orient='horizontal', command=self.results.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.results.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.results.bind('<<TreeviewSelect>>', self._show_details)
        self.details = ScrolledText(self, height=4, wrap='word', state='disabled', font=('Microsoft YaHei UI', 10), relief='flat')
        self.details.grid(row=9, column=0, columnspan=3, sticky='ew', pady=(8, 4))
        self.activity = ScrolledText(self, height=4, wrap='word', state='disabled', font=('Microsoft YaHei UI', 10), relief='flat')
        self.activity.grid(row=10, column=0, columnspan=3, sticky='ew', pady=4)
        ttk.Entry(self, textvariable=self.report_path, state='readonly').grid(row=11, column=0, columnspan=3, sticky='ew', pady=(4, 0))

    def _browse(self, variable: tk.StringVar, input_directory: bool) -> None:
        if self._running:
            return
        selected = filedialog.askdirectory(parent=self.winfo_toplevel(), title='选择输入目录' if input_directory else '选择独立输出目录', mustexist=input_directory)
        if selected:
            variable.set(selected)

    def _log(self, text: str) -> None:
        self.activity.configure(state='normal')
        self.activity.insert('end', text + '\n')
        self.activity.see('end')
        self.activity.configure(state='disabled')

    def _set_busy(self, busy: bool) -> None:
        self._running = busy
        for widget in (self.input_entry, self.output_entry, self.input_browse, self.output_browse,
                       self.start_button, self.recursive_check):
            widget.state(['disabled'] if busy else ['!disabled'])
        self.stop_button.state(['!disabled'] if busy else ['disabled'])
        if busy:
            self.progress.configure(mode='indeterminate', value=0)
            self.progress.start(15)
        elif str(self.progress['mode']) == 'indeterminate':
            self.progress.stop()

    def start(self) -> None:
        if self._running:
            return
        source, output = self.input_path.get().strip(), self.output_path.get().strip()
        recursive = self.recursive.get()
        if not source or not output:
            self.phase.set('任务异常')
            self._log('请填写输入目录和独立输出目录。')
            return
        self.results.delete(*self.results.get_children())
        self._rows.clear()
        for area in (self.activity, self.details):
            area.configure(state='normal')
            area.delete('1.0', 'end')
            area.configure(state='disabled')
        self.report_path.set('')
        self.current_file.set('准备检查目录…')
        self.summary.set(INCREMENTAL_NOTE + ' 当前任务参数已锁定。')
        self._log(INCREMENTAL_NOTE)
        self.phase.set('准备中')
        self._stop = threading.Event()
        self._set_busy(True)
        # Capture strings now: even programmatic StringVar edits cannot alter
        # this job. The non-daemon worker is never killed halfway through writing.
        try:
            threading.Thread(target=self._work, args=(source, output, recursive, self._stop), daemon=False).start()
        except Exception as exc:
            self._messages.put(BatchEvent('error', message=str(exc)))

    def request_stop(self) -> None:
        if not self._running or self._stop.is_set():
            return
        self._stop.set()
        self.stop_button.state(['disabled'])
        self.phase.set('请求停止')
        self._log('已请求停止：等待当前文件完成或安全失败；扫描中则等待扫描结束，不再启动下一文件。')

    def _work(self, source: str, output: str, recursive: bool, stop: threading.Event) -> None:
        error_sent = False

        def receive(event: BatchEvent) -> None:
            nonlocal error_sent
            if event.kind == 'error':
                error_sent = True
            self._messages.put(event)

        try:
            run(Path(source).expanduser(), Path(output).expanduser(), recursive=recursive, stop=stop,
                emit=lambda message: None, on_event=receive)
        except Exception as exc:
            # Setup can fail before run emits anything; always deliver one
            # terminal event. No worker path is allowed to call Tk directly.
            if not error_sent:
                self._messages.put(BatchEvent('error', message=str(exc)))

    def _poll(self) -> None:
        try:
            # Bound each drain so bursts of tiny files cannot monopolize Tk.
            for _ in range(100):
                self._handle(self._messages.get_nowait())
        except queue.Empty:
            pass
        self._poll_id = self.after(40, self._poll)

    def _handle(self, event: BatchEvent) -> None:
        if event.kind == 'phase':
            if not self._stop.is_set():
                self.phase.set(event.phase)
            if event.source is not None:
                self.current_file.set(str(event.source))
            self._log(event.phase + (f'：{event.source}' if event.source else ''))
        elif event.kind == 'scanned':
            self.progress.stop()
            self.progress.configure(mode='determinate', maximum=max(event.total or 0, 1), value=0)
            self.summary.set(f'扫描完成：0 / {event.total} 个文件。')
            self._log(f'扫描完成：共 {event.total} 个文件。')
        elif event.kind == 'file' and event.row is not None:
            self.progress.configure(value=event.completed)
            self.summary.set(f'已处理 {event.completed} / {event.total} 个文件；原稿不覆盖。')
            row = event.row
            item = self.results.insert('', 'end', values=(row['status'], row['source'], row['output'] or '未发布'))
            self._rows[item] = row
            self._log(f"{row['status']}：{row['source']}" + (f"；{row['error']}" if 'error' in row else ''))
            self.results.selection_set(item)
            self._show_details()
            if event.report is not None:
                self.report_path.set(str(event.report))
        elif event.kind == 'error':
            self._set_busy(False)
            self.phase.set('任务异常')
            self.summary.set('任务无法继续；已完成的输出保留，请查看错误信息。')
            self._log('任务异常：' + event.message)
        elif event.kind in ('finished', 'stopped'):
            self._set_busy(False)
            failed = sum(row['status'] == '失败' for row in self._rows.values())
            partial = sum(row['status'] == '部分清理' for row in self._rows.values())
            reused = sum(row['status'] == '未变化' for row in self._rows.values())
            if event.kind == 'stopped':
                self.phase.set('已停止')
                self.summary.set(f'已停止：处理 {event.completed} / {event.total} 个文件，未处理 {(event.total or 0) - event.completed} 个；失败 {failed} 个，部分清理 {partial} 个。')
            else:
                self.phase.set('处理结束（存在失败）' if failed else '处理结束（存在部分清理）' if partial else '处理完成')
                self.summary.set(f'本轮 {event.completed} / {event.total} 个文件，失败 {failed} 个，部分清理 {partial} 个。' if self._rows else '本轮扫描范围内没有可处理的 PSD / PSB 文件（0 / 0）。')
            if self._rows:
                self.summary.set(self.summary.get() + f' 历史复用 {reused} 个，不在本轮重复复制；实际输出以逐文件路径为准。')
            self.report_path.set(str(event.report or ''))
            self._log(self.phase.get() + '；' + self.summary.get())

    def _show_details(self, event: object = None) -> None:
        selection = self.results.selection()
        if not selection or selection[0] not in self._rows:
            return
        row = self._rows[selection[0]]
        text = f"状态：{row['status']}"
        if row['status'] == '未变化':
            text += '\n复用历史副本：源内容、规则和输出校验一致；本轮未重复清理或复制。'
        if row.get('error'):
            text += '\n错误：' + row['error']
        text += f"\n输入：{row['source']}\n输出：{row['output'] or '未发布'}"
        if row.get('issues'):
            text += '\n' + '\n'.join(row['issues'])
        self.details.configure(state='normal')
        self.details.delete('1.0', 'end')
        self.details.insert('1.0', text)
        self.details.configure(state='disabled')

    def request_close(self) -> None:
        if self._running:
            self._log('本轮仍在处理，请点击“安全停止”或等待本轮结束后再关闭窗口；不会中断正在写入的文件。')
            return
        self.winfo_toplevel().destroy()

    def destroy(self) -> None:
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
        super().destroy()


def create_window() -> tuple[tk.Tk, CleanerWindow]:
    """Build the same application window for the entry point and UI acceptance."""
    root = tk.Tk()
    root.title('PSD Batch Cleaner · PSD 批量瘦身')
    root.geometry('1060x760')
    root.minsize(780, 650)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=('Microsoft YaHei UI', 10))
    style.configure('TFrame', background='#f4f6fa')
    style.configure('TLabel', background='#f4f6fa', foreground='#243247')
    style.configure('Title.TLabel', font=('Microsoft YaHei UI', 22, 'bold'), foreground='#152744')
    style.configure('TButton', padding=(12, 6))
    style.configure('Accent.TButton', background='#2563eb', foreground='white')
    style.map('Accent.TButton', background=[('disabled', '#cbd5e1'), ('active', '#1d4ed8')])
    style.configure('Treeview', rowheight=26)
    style.configure('Treeview.Heading', background='#e5ecf6')
    app = CleanerWindow(root)
    app.pack(fill='both', expand=True)
    root.protocol('WM_DELETE_WINDOW', app.request_close)
    return root, app


def main() -> None:
    argparse.ArgumentParser(description='PSD Batch Cleaner 中文串行窗口（可选包含子文件夹）').parse_args()
    root, _ = create_window()
    root.mainloop()


if __name__ == '__main__':
    main()
