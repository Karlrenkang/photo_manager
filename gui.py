"""Photo Manager V1.1 - GUI Entry Point

Standard GUI interface using CustomTkinter (dark theme).
All core logic reused from core/ modules, zero modifications.

Usage:
    python gui.py
"""

import sys
import os
import queue
import subprocess
import json
from datetime import datetime
from typing import Optional

import customtkinter as ctk
from tkinter import filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui_worker import ScanWorker, MSG_LOG, MSG_PROGRESS, MSG_RESULT, MSG_ERROR, MSG_DONE

# Default paths
DEFAULT_INPUT = ""
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_DB_PATH = os.path.join(BASE_DIR, "storage", "history_db.json")


# ============================================================
# Main Window
# ============================================================
class MainWindow(ctk.CTk):
    """Photo Manager V1.1 GUI - CustomTkinter dark theme."""

    def __init__(self):
        super().__init__()

        # Window settings
        self.title("Photo Manager V1.1")
        self.geometry("780x680")
        self.minsize(680, 600)

        # Appearance
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # State
        self.msg_queue: queue.Queue = queue.Queue()
        self.worker: Optional[ScanWorker] = None
        self.last_scan_time = ""
        self.total_processed = 0

        self._build_ui()
        self._poll_queue()
        self._refresh_status()

    # ── UI Build ──────────────────────────────────────────

    def _build_ui(self):
        """Build the complete GUI layout."""
        # Main container with padding
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=16, pady=12)

        self._build_folder_section(container)
        self._build_action_section(container)
        self._build_progress_section(container)
        self._build_stats_section(container)
        self._build_quick_section(container)
        self._build_history_section(container)
        self._build_statusbar()

    def _build_folder_section(self, parent):
        """Folder selection area."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(frame, text="📁 输入文件夹", font=ctk.CTkFont(size=13)).pack(
            anchor="w", pady=(0, 6)
        )

        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x")

        self.folder_var = ctk.StringVar(value=DEFAULT_INPUT)
        self.folder_entry = ctk.CTkEntry(
            row, textvariable=self.folder_var, height=36,
            font=ctk.CTkFont(size=13),
        )
        self.folder_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            row, text="浏览...", width=80, height=36,
            command=self._browse_folder,
            fg_color="#3B82F6", hover_color="#2563EB",
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            row, text="📂 打开", width=80, height=36,
            command=self._open_folder,
            fg_color="#4B5563", hover_color="#6B7280",
        ).pack(side="left")

    def _build_action_section(self, parent):
        """Action buttons row."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 14))

        self.scan_btn = ctk.CTkButton(
            row, text="▶  开始扫描", height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#3B82F6", hover_color="#2563EB",
            command=self._start_scan,
        )
        self.scan_btn.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkButton(
            row, text="⟳  重置历史", width=120, height=40,
            command=self._reset_history,
            fg_color="#4B5563", hover_color="#6B7280",
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            row, text="📊  刷新状态", width=120, height=40,
            command=self._refresh_status,
            fg_color="#4B5563", hover_color="#6B7280",
        ).pack(side="left")

    def _build_progress_section(self, parent):
        """Progress bar and status."""
        box = ctk.CTkFrame(parent)
        box.pack(fill="x", pady=(0, 14))

        header = ctk.CTkFrame(box, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(12, 8))

        ctk.CTkLabel(header, text="扫描进度", font=ctk.CTkFont(size=12),
                      text_color="#9CA3AF").pack(side="left")
        self.percent_label = ctk.CTkLabel(
            header, text="0%", font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#3B82F6",
        )
        self.percent_label.pack(side="right")

        self.progress_bar = ctk.CTkProgressBar(box, height=8)
        self.progress_bar.pack(fill="x", padx=16, pady=(0, 8))
        self.progress_bar.set(0)

        self.status_label = ctk.CTkLabel(
            box, text="就绪", font=ctk.CTkFont(size=12),
            text_color="#9CA3AF", anchor="w",
        )
        self.status_label.pack(anchor="w", padx=16, pady=(0, 12))

    def _build_stats_section(self, parent):
        """Statistics cards in 2x2 grid."""
        box = ctk.CTkFrame(parent)
        box.pack(fill="x", pady=(0, 14))

        grid = ctk.CTkFrame(box, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=14)

        self.stat_labels = {}
        stats_config = [
            ("total", "扫描总数"),
            ("dup_groups", "重复分组"),
            ("moved_dup", "移入 Duplicates"),
            ("moved_scan", "移入 Scanned"),
        ]

        for i, (key, label) in enumerate(stats_config):
            row, col = divmod(i, 2)
            cell = ctk.CTkFrame(grid, fg_color="#1F2937", corner_radius=8)
            cell.grid(row=row, column=col, padx=(0, 6) if col == 0 else (6, 0),
                      pady=3, sticky="ew")
            grid.columnconfigure(col, weight=1)

            ctk.CTkLabel(cell, text=label, font=ctk.CTkFont(size=11),
                          text_color="#9CA3AF").pack(side="left", padx=12, pady=10)
            val = ctk.CTkLabel(cell, text="0", font=ctk.CTkFont(size=13, weight="bold"),
                                text_color="#FFFFFF")
            val.pack(side="right", padx=12, pady=10)
            self.stat_labels[key] = val

    def _build_quick_section(self, parent):
        """Quick folder open buttons."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 14))

        ctk.CTkButton(
            row, text="📂  打开 Duplicates", height=36,
            command=lambda: self._open_subfolder("Duplicates"),
            fg_color="#374151", hover_color="#4B5563",
            border_width=1, border_color="#4B5563",
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            row, text="  打开 Scanned", height=36,
            command=lambda: self._open_subfolder("Scanned"),
            fg_color="#374151", hover_color="#4B5563",
            border_width=1, border_color="#4B5563",
        ).pack(side="left", fill="x", expand=True, padx=(6, 0))

    def _build_history_section(self, parent):
        """History display and clear button."""
        box = ctk.CTkFrame(parent)
        box.pack(fill="x", pady=(0, 14))

        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(inner, text="History hashes:", font=ctk.CTkFont(size=13),
                      text_color="#9CA3AF").pack(side="left")
        self.history_label = ctk.CTkLabel(
            inner, text="0", font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#FBBF24",
        )
        self.history_label.pack(side="left", padx=(6, 0))

        ctk.CTkButton(
            inner, text="清空历史", width=100, height=32,
            command=self._reset_history,
            fg_color="#EF4444", hover_color="#DC2626",
        ).pack(side="right")

    def _build_statusbar(self):
        """Bottom status bar."""
        bar = ctk.CTkFrame(self, height=32, fg_color="#111827", corner_radius=0)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        self.status_dot = ctk.CTkLabel(
            bar, text="●", font=ctk.CTkFont(size=10),
            text_color="#10B981",
        )
        self.status_dot.pack(side="left", padx=(12, 4))

        self.status_state = ctk.CTkLabel(
            bar, text="就绪", font=ctk.CTkFont(size=11),
            text_color="#9CA3AF",
        )
        self.status_state.pack(side="left")

        ctk.CTkLabel(
            bar, text="V1.1", font=ctk.CTkFont(size=11),
            text_color="#6B7280",
        ).pack(side="left", padx=(14, 0))

        self.status_processed = ctk.CTkLabel(
            bar, text="已处理: 0", font=ctk.CTkFont(size=11),
            text_color="#6B7280",
        )
        self.status_processed.pack(side="right", padx=(0, 12))

        self.status_time = ctk.CTkLabel(
            bar, text="上次扫描: -", font=ctk.CTkFont(size=11),
            text_color="#6B7280",
        )
        self.status_time.pack(side="right", padx=(0, 12))

        self._update_statusbar()

    # ── Actions ───────────────────────────────────────────

    def _browse_folder(self):
        folder = filedialog.askdirectory(initialdir=self.folder_var.get())
        if folder:
            self.folder_var.set(folder)

    def _open_folder(self):
        folder = self.folder_var.get()
        if os.path.isdir(folder):
            if sys.platform == "win32":
                os.startfile(folder)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", folder])

    def _open_subfolder(self, name: str):
        folder = os.path.join(self.folder_var.get(), name)
        if os.path.isdir(folder):
            if sys.platform == "win32":
                os.startfile(folder)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", folder])
        else:
            messagebox.showinfo("提示", f"文件夹不存在: {folder}")

    def _start_scan(self):
        input_folder = self.folder_var.get()
        if not os.path.isdir(input_folder):
            messagebox.showerror("错误", f"文件夹不存在:\n{input_folder}")
            return

        if self.worker and self.worker.is_running():
            self.worker.stop()
            self.scan_btn.configure(text="▶  开始扫描", fg_color="#3B82F6")
            return

        # Reset UI
        self.progress_bar.set(0)
        self.percent_label.configure(text="0%")
        self.status_label.configure(text="正在扫描...")
        for lbl in self.stat_labels.values():
            lbl.configure(text="0")

        self.scan_btn.configure(text="■  终止扫描", fg_color="#EF4444", hover_color="#DC2626")

        self.worker = ScanWorker(input_folder, self.msg_queue, on_complete=self._on_scan_done)
        self.worker.start()

    def _on_scan_done(self):
        pass  # Processed by _poll_queue

    def _reset_history(self):
        if not messagebox.askyesno("确认", "确定要清空所有历史记录吗？\n此操作不可撤销。"):
            return
        try:
            os.makedirs(os.path.dirname(HISTORY_DB_PATH), exist_ok=True)
            with open(HISTORY_DB_PATH, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=2)
            self._refresh_status()
            messagebox.showinfo("完成", "历史记录已清空。")
        except Exception as e:
            messagebox.showerror("错误", f"清空失败: {e}")

    def _refresh_status(self):
        try:
            if os.path.exists(HISTORY_DB_PATH):
                with open(HISTORY_DB_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    count = len(data)
            else:
                count = 0
            self.history_label.configure(text=str(count))
        except Exception:
            self.history_label.configure(text="0")

    # ── Message Queue Polling ─────────────────────────────

    def _poll_queue(self):
        """Poll message queue from worker thread."""
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                msg_type = msg[0]

                if msg_type == MSG_LOG:
                    pass  # Could add log display here

                elif msg_type == MSG_PROGRESS:
                    value, status = msg[1], msg[2]
                    self.progress_bar.set(value)
                    self.percent_label.configure(text=f"{int(value * 100)}%")
                    self.status_label.configure(text=status)

                elif msg_type == MSG_RESULT:
                    result = msg[1]
                    self.stat_labels["total"].configure(text=str(result["total"]))
                    self.stat_labels["dup_groups"].configure(text=str(result["dup_groups"]))
                    self.stat_labels["moved_dup"].configure(text=str(result["moved_dup"]))
                    self.stat_labels["moved_scan"].configure(text=str(result["moved_scan"]))
                    self.total_processed = result["total"]
                    self.last_scan_time = result.get("time", datetime.now().strftime("%Y-%m-%d %H:%M"))
                    self._refresh_status()

                elif msg_type == MSG_ERROR:
                    self.status_label.configure(text="出错")

                elif msg_type == MSG_DONE:
                    success = msg[1]
                    if success:
                        self.status_label.configure(text="完成")
                    else:
                        self.status_label.configure(text="已终止")
                    self.scan_btn.configure(text="▶  开始扫描", fg_color="#3B82F6")

        except queue.Empty:
            pass

        self.after(100, self._poll_queue)

    def _update_statusbar(self):
        """Periodic status bar update."""
        self.status_processed.configure(text=f"已处理: {self.total_processed}")
        self.status_time.configure(text=f"上次扫描: {self.last_scan_time or '-'}")

        if self.worker and self.worker.is_running():
            self.status_dot.configure(text_color="#FBBF24")
            self.status_state.configure(text="扫描中")
        else:
            self.status_dot.configure(text_color="#10B981")
            self.status_state.configure(text="就绪")

        self.after(500, self._update_statusbar)


def main():
    app = MainWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
