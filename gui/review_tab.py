"""
Photo Manager V1.3 - 相似分组复核标签页

左侧分组表格 + 右侧缩略图预览。
支持还原本组、还原单张、导出 CSV、打开归档文件夹。

前置校验：无数据时弹窗提示，不显示空白界面。
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional, Callable

import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ReviewTab(ctk.CTkFrame):
    """相似分组复核标签页。"""

    def __init__(self, parent, adapter, on_log: Optional[Callable] = None):
        """
        Args:
            parent: 父容器
            adapter: SimilarAdapter 实例
            on_log: 日志回调 function(msg: str)
        """
        super().__init__(parent, fg_color="transparent")
        self.adapter = adapter
        self.on_log = on_log
        self._selected_group: Optional[str] = None
        self._selected_dup_path: Optional[str] = None

        self._build_ui()

    def _build_ui(self):
        """构建复核页布局。"""
        # 顶部工具栏
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=10, pady=(10, 8))

        ctk.CTkLabel(toolbar, text="相似分组复核", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")

        ctk.CTkButton(
            toolbar, text="刷新", width=80, height=32,
            command=self._refresh,
            fg_color="#4B5563", hover_color="#6B7280",
        ).pack(side="right", padx=(6, 0))

        self.export_btn = ctk.CTkButton(
            toolbar, text="导出 CSV", width=90, height=32,
            command=self._export_csv,
            fg_color="#3B82F6", hover_color="#2563EB",
        )
        self.export_btn.pack(side="right", padx=(6, 0))

        # 主内容区：左侧表格 + 右侧预览
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # ── 左侧：分组表格 ─
        left = ctk.CTkFrame(content, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        self.tree_frame = ctk.CTkFrame(left)
        self.tree_frame.pack(fill="both", expand=True)

        # 用 Text 模拟表格（CustomTkinter 无 Treeview）
        self.table_text = ctk.CTkTextbox(
            self.tree_frame, font=ctk.CTkFont(family="Consolas", size=12),
            fg_color="#1F2937", text_color="#E5E7EB",
            state="disabled", wrap="none",
        )
        self.table_text.pack(fill="both", expand=True, padx=2, pady=2)

        # 操作按钮
        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.pack(fill="x", pady=(8, 0))

        self.undo_group_btn = ctk.CTkButton(
            btn_row, text="还原本组", width=100, height=34,
            command=self._undo_group,
            fg_color="#3B82F6", hover_color="#2563EB",
            state="disabled",
        )
        self.undo_group_btn.pack(side="left", padx=(0, 8))

        self.undo_file_btn = ctk.CTkButton(
            btn_row, text="还原单张", width=100, height=34,
            command=self._undo_file,
            fg_color="#4B5563", hover_color="#6B7280",
            state="disabled",
        )
        self.undo_file_btn.pack(side="left")

        # ── 右侧：缩略图预览 ──
        right = ctk.CTkFrame(content, width=320)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        ctk.CTkLabel(right, text="预览", font=ctk.CTkFont(size=12),
                      text_color="#9CA3AF").pack(anchor="w", padx=12, pady=(10, 6))

        self.preview_label = ctk.CTkLabel(
            right, text="点击左侧分组查看预览",
            font=ctk.CTkFont(size=11), text_color="#6B7280",
            fg_color="#1F2937", corner_radius=8,
        )
        self.preview_label.pack(fill="x", padx=12, pady=(0, 10))

        # 预览图片区域（用 Canvas 显示缩略图）
        self.preview_canvas = ctk.CTkCanvas(
            right, height=400, bg="#111827", highlightthickness=0,
        )
        self.preview_canvas.pack(fill="x", padx=12, pady=(0, 10))

        # 打开归档文件夹按钮
        self.open_archive_btn = ctk.CTkButton(
            right, text="📂 打开 similar_photos", height=34,
            command=self._open_archive,
            fg_color="#374151", hover_color="#4B5563",
            border_width=1, border_color="#4B5563",
        )
        self.open_archive_btn.pack(fill="x", padx=12, pady=(0, 10))

    # ───────────────────────────────────────────────────────
    # 数据加载
    # ───────────────────────────────────────────────────────

    def load_data(self):
        """加载分组数据并刷新表格（带前置校验）。"""
        groups = self.adapter.get_group_list()

        if not groups:
            # 前置校验：无数据
            source_dir = ""
            if self.adapter.engine:
                source_dir = self.adapter.engine.source_dir

            archive = self.adapter.get_similar_archive_root(source_dir) if source_dir else ""

            if not os.path.isdir(archive):
                messagebox.showinfo("提示", "未执行过相似筛选，无分组数据。")
            else:
                messagebox.showinfo("提示", "本次扫描无相似图片，无需复核。")

            self.table_text.configure(state="normal")
            self.table_text.delete("1.0", "end")
            self.table_text.insert("end", "暂无分组数据\n")
            self.table_text.configure(state="disabled")
            return

        self._render_table(groups)
        self._log(f"加载 {len(groups)} 个相似分组")

    def _render_table(self, groups):
        """渲染分组表格。"""
        self.table_text.configure(state="normal")
        self.table_text.delete("1.0", "end")

        # 表头
        header = f"{'分组ID':<12} {'总数':>4}  {'副本':>4}\n"
        self.table_text.insert("end", header, "header")
        self.table_text.insert("end", "─" * 26 + "\n", "separator")

        for g in groups:
            line = f"{g['group_id']:<12} {g['total']:>4}  {g['dup_count']:>4}\n"
            self.table_text.insert("end", line, "row")

        self.table_text.configure(state="disabled")

        # 绑定点击事件
        self.table_text.bind("<Button-1>", self._on_table_click)

    def _on_table_click(self, event):
        """点击表格行 → 加载预览。"""
        try:
            index = self.table_text.index(f"@{event.x},{event.y}")
            line_num = int(index.split(".")[0])
        except (ValueError, ctk.TkinterError):
            return

        groups = self.adapter.get_group_list()
        # 跳过表头(2行)和分隔线
        row_idx = line_num - 3
        if 0 <= row_idx < len(groups):
            group = groups[row_idx]
            self._selected_group = group["group_id"]
            self._render_preview(group)

            # 启用操作按钮
            self.undo_group_btn.configure(state="normal")
            self.undo_file_btn.configure(state="normal")

    def _render_preview(self, group: dict):
        """渲染右侧缩略图预览。"""
        self.preview_canvas.delete("all")

        y_offset = 10
        size = 100

        for i, dup in enumerate(group["duplicates"]):
            moved_path = dup["moved_path"]
            original_path = dup["original_path"]

            # 尝试加载缩略图（优先原始路径，其次移动后路径）
            thumb = self.adapter.get_thumbnail(original_path, size)
            if thumb is None:
                thumb = self.adapter.get_thumbnail(moved_path, size)

            if thumb:
                photo = ImageTk.PhotoImage(thumb)
                self.preview_canvas.create_image(10, y_offset, anchor="nw", image=photo)
                # 保持引用防止 GC
                if not hasattr(self, "_photo_refs"):
                    self._photo_refs = []
                self._photo_refs.append(photo)

                # 文件名标签（灰色 = 已移动）
                name = os.path.basename(original_path)
                self.preview_canvas.create_text(
                    120, y_offset + size // 2,
                    text=name[:20], anchor="w",
                    fill="#9CA3AF", font=("Segoe UI", 9),
                )
            else:
                # 无缩略图，显示占位
                self.preview_canvas.create_text(
                    10, y_offset + size // 2,
                    text="[无预览]", anchor="nw",
                    fill="#6B7280", font=("Segoe UI", 10),
                )

            y_offset += size + 15

            if y_offset > 380:
                break

        if y_offset <= 25:
            self.preview_canvas.create_text(
                160, 200,
                text="无可用预览", fill="#6B7280",
                font=("Segoe UI", 12),
            )

    # ───────────────────────────────────────────────────────
    # 操作
    # ───────────────────────────────────────────────────────

    def _undo_group(self):
        """还原本组全部副本。"""
        if not self._selected_group:
            return
        ok, msg = self.adapter.undo_single_group(self._selected_group)
        if ok:
            self._log(f"还原分组 {self._selected_group}: {msg}")
            self.load_data()
        else:
            messagebox.showerror("还原失败", msg)

    def _undo_file(self):
        """还原单张（当前选中分组的第一个副本）。"""
        groups = self.adapter.get_group_list()
        for g in groups:
            if g["group_id"] == self._selected_group and g["duplicates"]:
                dup = g["duplicates"][0]
                ok, msg = self.adapter.undo_single_file(dup["original_path"])
                if ok:
                    self._log(f"还原单张: {msg}")
                    self.load_data()
                else:
                    messagebox.showerror("还原失败", msg)
                return

    def _export_csv(self):
        """导出分组清单 CSV。"""
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="similar_groups.csv",
        )
        if not path:
            return
        if self.adapter.export_csv(path):
            self._log(f"CSV 已导出: {path}")
            messagebox.showinfo("完成", f"CSV 已导出:\n{path}")
        else:
            messagebox.showerror("导出失败", "写入 CSV 失败")

    def _open_archive(self):
        """打开 similar_photos 文件夹。"""
        source_dir = ""
        if self.adapter.engine:
            source_dir = str(self.adapter.engine.source_dir)
        if not source_dir:
            messagebox.showinfo("提示", "未指定源文件夹")
            return

        archive = self.adapter.get_similar_archive_root(source_dir)
        if os.path.isdir(archive):
            if sys.platform == "win32":
                os.startfile(archive)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", archive])
        else:
            messagebox.showinfo("提示", f"文件夹不存在: {archive}")

    def _refresh(self):
        """刷新数据。"""
        self.adapter.invalidate_cache()
        self.load_data()

    def _log(self, msg: str):
        """发送日志到主界面。"""
        if self.on_log:
            self.on_log(f"[相似] {msg}")
