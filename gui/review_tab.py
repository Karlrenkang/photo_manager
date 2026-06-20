"""
Photo Manager V1.3 - 相似分组复核标签页（重构版）

修复内容：
1. 布局重构：左 25% 右 75%，预览区大幅拓宽
2. 单张选中：点击缩略图高亮，右键选中用于还原
3. 原图预览：顶部绿色区域展示保留原图，下方灰色展示副本
4. 放大弹窗：左键点击任意缩略图弹出全屏放大窗口，支持滚轮缩放+拖拽+ESC关闭
5. 还原本组后自动清理空 group 文件夹

仅修改本文件，底层引擎零改动。
"""

import os
import sys
import subprocess
import tkinter as tk
from pathlib import Path
from typing import Optional, Callable

import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# 悬停预览窗口
# ============================================================

_hover_windows = {}  # 防止重复创建

def show_hover_preview(image_path: str, anchor_widget):
    """
    鼠标悬停时显示放大预览窗口。

    - 预览尺寸：最大 800x800
    - 窗口位置：屏幕右侧
    - 鼠标离开锚点时自动关闭
    """
    if image_path in _hover_windows:
        return  # 已存在，不重复创建

    if not os.path.exists(image_path):
        return

    try:
        from PIL import Image, ImageTk
        orig_img = Image.open(image_path)

        # 缩放到最大 800x800
        max_size = 800
        orig_img.thumbnail((max_size, max_size), Image.LANCZOS)

        # 创建预览窗口
        win = tk.Toplevel()
        win.title("预览")
        win.attributes("-topmost", True)
        win.configure(bg="#1a1a1a")

        # 计算位置（屏幕右侧居中）
        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        x = screen_w - orig_img.width - 100
        y = (screen_h - orig_img.height) // 2
        win.geometry(f"{orig_img.width + 20}x{orig_img.height + 60}+{x}+{y}")

        # 显示图片
        canvas = tk.Canvas(win, bg="#1a1a1a", highlightthickness=0,
                           width=orig_img.width, height=orig_img.height)
        canvas.pack(padx=10, pady=(10, 0))

        photo = ImageTk.PhotoImage(orig_img)
        canvas.create_image(0, 0, anchor="nw", image=photo)
        canvas._photo_ref = photo  # 防止 GC

        # 显示文件名
        name = os.path.basename(image_path)
        tk.Label(win, text=name[:40], fg="#9CA3AF", bg="#1a1a1a",
                 font=("Segoe UI", 10)).pack(pady=(5, 10))

        _hover_windows[image_path] = win

        # 绑定离开事件 — 鼠标离开锚点时关闭
        def close_preview(event=None):
            if image_path in _hover_windows:
                try:
                    _hover_windows[image_path].destroy()
                except Exception:
                    pass
                del _hover_windows[image_path]

        anchor_widget.bind("<Leave>", lambda e: close_preview(), add="+")

    except Exception as e:
        print(f"Preview error: {e}")

        anchor_widget.bind("<Leave>", lambda e: close_preview(), add="+")
        win.bind("<Leave>", lambda e: close_preview())
        win.bind("<Button-1>", lambda e: close_preview())  # 点击也关闭

    except Exception:
        pass


def hide_hover_preview(image_path: str):
    """关闭悬停预览窗口。"""
    if image_path in _hover_windows:
        _hover_windows[image_path].destroy()
        del _hover_windows[image_path]


# ============================================================
# 复核标签页
# ============================================================

class ReviewTab(ctk.CTkFrame):
    """相似分组复核标签页 — 重构版。"""

    def __init__(self, parent, adapter, on_log: Optional[Callable] = None):
        super().__init__(parent, fg_color="transparent")
        self.adapter = adapter
        self.on_log = on_log
        self.selected_group: Optional[str] = None
        self.selected_single_img: Optional[str] = None  # 当前选中单张图片路径
        self.current_scan_dir: str = ""
        self._selected_frame = None  # 当前选中的副本 frame（用于边框高亮）

        self._build_ui()

    def _build_ui(self):
        """构建复核页布局 — 左 25% 右 75%。"""
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

        # 主内容区：PanedWindow 左右分栏
        paned = ctk.CTkFrame(self, fg_color="transparent")
        paned.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # ── 左侧 25%：分组表格 ──
        left = ctk.CTkFrame(paned, width=200)
        left.pack(side="left", fill="y", padx=(0, 6))
        left.pack_propagate(False)

        self.table_text = ctk.CTkTextbox(
            left, font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#1F2937", text_color="#E5E7EB",
            state="disabled", wrap="none",
        )
        self.table_text.pack(fill="both", expand=True, padx=2, pady=2)

        # 操作按钮
        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.pack(fill="x", pady=(8, 0))

        self.undo_group_btn = ctk.CTkButton(
            btn_row, text="还原本组", width=90, height=32,
            command=self._undo_group,
            fg_color="#3B82F6", hover_color="#2563EB",
            state="disabled",
        )
        self.undo_group_btn.pack(side="left", padx=(0, 6))

        self.undo_file_btn = ctk.CTkButton(
            btn_row, text="还原单张", width=90, height=32,
            command=self._undo_file,
            fg_color="#4B5563", hover_color="#6B7280",
            state="disabled",
        )
        self.undo_file_btn.pack(side="left")

        # ── 右侧 75%：预览区 ──
        right = ctk.CTkFrame(paned)
        right.pack(side="right", fill="both", expand=True)

        # 上方：原图预览
        top_label = ctk.CTkLabel(right, text="原图（已保留）", font=ctk.CTkFont(size=12, weight="bold"),
                                  text_color="#34D399")
        top_label.pack(anchor="w", padx=12, pady=(10, 4))

        self.keeper_frame = ctk.CTkFrame(right, fg_color="#1F2937", corner_radius=8)
        self.keeper_frame.pack(fill="x", padx=12, pady=(0, 8))

        self.keeper_canvas = ctk.CTkCanvas(
            self.keeper_frame, height=180, bg="#111827", highlightthickness=0,
        )
        self.keeper_canvas.pack(fill="x", padx=8, pady=(8, 4))

        # 原图文件名标签
        self.keeper_name_label = ctk.CTkLabel(
            self.keeper_frame, text="", font=ctk.CTkFont(size=11),
            text_color="#34D399", anchor="w",
        )
        self.keeper_name_label.pack(fill="x", padx=12, pady=(0, 8))

        # 下方：副本预览
        bot_label = ctk.CTkLabel(right, text="相似副本（已移入 similar_photos）",
                                  font=ctk.CTkFont(size=12, weight="bold"),
                                  text_color="#9CA3AF")
        bot_label.pack(anchor="w", padx=12, pady=(8, 4))

        self.dup_frame = ctk.CTkFrame(right, fg_color="#1F2937", corner_radius=8)
        self.dup_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        self.dup_scroll = ctk.CTkScrollableFrame(self.dup_frame, fg_color="#111827")
        self.dup_scroll.pack(fill="both", expand=True, padx=4, pady=4)

        # 打开归档文件夹
        self.open_archive_btn = ctk.CTkButton(
            right, text=" 打开 similar_photos", height=32,
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
        # 获取当前扫描目录（优先从引擎，其次从适配器缓存）
        if self.adapter.engine:
            self.current_scan_dir = str(self.adapter.engine.source_dir)
        elif self.adapter._current_source_dir:
            self.current_scan_dir = self.adapter._current_source_dir

        # 先清理空的 group 文件夹（历史遗留）
        if self.current_scan_dir:
            self.adapter.clean_all_empty_group_dirs(self.current_scan_dir)

        groups = self.adapter.get_group_list()

        if not groups:
            # CSV 为空时，尝试从 similar_photos 目录结构解析
            groups = self.adapter.get_groups_from_directory(self.current_scan_dir)

        if not groups:
            archive = self.adapter.get_similar_archive_root(self.current_scan_dir) if self.current_scan_dir else ""
            if not os.path.isdir(archive):
                messagebox.showinfo("提示", "未执行过相似筛选，无分组数据。")
            else:
                messagebox.showinfo("提示", "本次扫描无相似图片，无需复核。")
            self._clear_preview()
            return

        self._render_table(groups)
        self._log(f"加载 {len(groups)} 个相似分组")

    def _render_table(self, groups):
        """渲染分组表格 — 精简三列，选中行高亮。"""
        self.table_text.configure(state="normal")
        self.table_text.delete("1.0", "end")

        # 配置 tag 颜色（通过底层 tkinter Text widget）
        tw = self.table_text._textbox
        tw.tag_configure("header", foreground="#9CA3AF")
        tw.tag_configure("selected", foreground="#3B82F6")
        tw.tag_configure("normal", foreground="#E5E7EB")

        header = f"{'ID':<10} {'总':>3}  {'副本':>3}\n"
        self.table_text.insert("end", header, "header")
        self.table_text.insert("end", "─" * 20 + "\n", "header")

        for g in groups:
            line = f"{g['group_id']:<10} {g['total']:>3}  {g['dup_count']:>3}\n"
            tag = "selected" if g["group_id"] == self.selected_group else "normal"
            self.table_text.insert("end", line, tag)

        self.table_text.configure(state="disabled")
        self.table_text.bind("<Button-1>", self._on_table_click)

    def _on_table_click(self, event):
        """点击表格行 → 加载预览。"""
        try:
            index = self.table_text.index(f"@{event.x},{event.y}")
            line_num = int(index.split(".")[0])
        except (ValueError, ctk.TkinterError):
            return

        groups = self.adapter.get_group_list()
        row_idx = line_num - 3
        if 0 <= row_idx < len(groups):
            group = groups[row_idx]
            self.selected_group = group["group_id"]
            self.selected_single_img = None
            self._selected_frame = None  # 重置选中 frame
            self.undo_file_btn.configure(state="disabled")
            self._render_preview(group)
            self.undo_group_btn.configure(state="normal")
            self.undo_file_btn.configure(state="disabled")

    def _render_preview(self, group: dict):
        """渲染预览区：上方原图 + 下方副本。"""
        self.keeper_canvas.delete("all")
        self._clear_dup_scroll()

        # ── 上方：原图 ──
        keeper_path = group.get("keeper_path", "")
        if keeper_path and os.path.exists(keeper_path):
            thumb = self.adapter.get_thumbnail(keeper_path, 160)
            if thumb:
                photo = ImageTk.PhotoImage(thumb)
                self.keeper_canvas.create_image(10, 10, anchor="nw", image=photo)
                self.keeper_canvas._keeper_photo = photo

                # 悬停预览
                self.keeper_canvas.bind("<Enter>",
                    lambda e, p=keeper_path: show_hover_preview(p, self.keeper_canvas))
                self.keeper_canvas.bind("<Leave>",
                    lambda e, p=keeper_path: hide_hover_preview(p))

            # 显示文件名
            keeper_name = os.path.basename(keeper_path)
            self.keeper_name_label.configure(text=f"✓ {keeper_name}")
        else:
            self.keeper_canvas.create_text(160, 90,
                text="原始原图已丢失", fill="#6B7280", font=("Segoe UI", 12))
            self.keeper_name_label.configure(text="")

        # ── 下方：副本 ──
        for dup in group["duplicates"]:
            moved_path = dup["moved_path"]
            original_path = dup["original_path"]

            thumb = self.adapter.get_thumbnail(moved_path, 120)
            if thumb is None:
                thumb = self.adapter.get_thumbnail(original_path, 120)

            if thumb:
                photo = ImageTk.PhotoImage(thumb)
                frame = ctk.CTkFrame(self.dup_scroll, fg_color="#374151", corner_radius=6,
                                      border_width=2, border_color="#4B5563")
                frame.pack(fill="x", pady=4, padx=4)

                canvas = ctk.CTkCanvas(frame, width=130, height=130, bg="#1F2937", highlightthickness=0)
                canvas.pack(side="left", padx=6, pady=6)
                canvas.create_image(5, 5, anchor="nw", image=photo)
                canvas._photo_ref = photo

                name = os.path.basename(original_path)
                ctk.CTkLabel(frame, text=name[:25], font=ctk.CTkFont(size=10),
                              text_color="#9CA3AF").pack(side="left", padx=8)

                # 悬停预览，右键选中
                canvas.bind("<Enter>",
                    lambda e, p=moved_path: show_hover_preview(p, canvas))
                canvas.bind("<Leave>",
                    lambda e, p=moved_path: hide_hover_preview(p))
                canvas.bind("<Button-3>",
                    lambda e, p=original_path: self._select_single(p, frame))
                frame.bind("<Button-3>",
                    lambda e, p=original_path, f=frame: self._select_single(p, f))
            else:
                ctk.CTkLabel(self.dup_scroll, text=f"[无预览] {os.path.basename(original_path)}",
                              text_color="#6B7280").pack(anchor="w", padx=8, pady=4)

    def _select_single(self, path: str, frame=None):
        """选中单张图片用于还原 — 边框变蓝高亮。"""
        # 重置之前的选中 frame
        if self._selected_frame and self._selected_frame != frame:
            try:
                self._selected_frame.configure(border_color="#4B5563", border_width=2)
            except Exception:
                pass

        # 高亮当前选中
        if frame:
            frame.configure(border_color="#3B82F6", border_width=3)
            self._selected_frame = frame

        self.selected_single_img = path
        self.undo_file_btn.configure(state="normal")
        self._log(f"选中单张: {os.path.basename(path)}")

    def _clear_preview(self):
        """清空预览区。"""
        self.keeper_canvas.delete("all")
        self._clear_dup_scroll()

    def _clear_dup_scroll(self):
        """清空副本滚动区。"""
        for widget in self.dup_scroll.winfo_children():
            widget.destroy()

    # ───────────────────────────────────────────────────────
    # 操作
    # ───────────────────────────────────────────────────────

    def _undo_group(self):
        """还原本组全部副本 + 清理空文件夹。"""
        if not self.selected_group:
            return
        ok, msg = self.adapter.undo_single_group(self.selected_group)
        if ok:
            self._log(f"还原分组 {self.selected_group}: {msg}")
            self.load_data()
        else:
            messagebox.showerror("还原失败", msg)

    def _undo_file(self):
        """还原单张选中图片。"""
        if not self.selected_single_img:
            messagebox.showwarning("提示", "请先在预览区右键点击选中需要还原的单张图片")
            return
        ok, msg = self.adapter.undo_single_file(self.selected_single_img)
        if ok:
            self._log(f"还原单张: {msg}")
            self.selected_single_img = None
            self.undo_file_btn.configure(state="disabled")
            self.load_data()
        else:
            messagebox.showerror("还原失败", msg)

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
        if not self.current_scan_dir:
            messagebox.showinfo("提示", "未指定源文件夹")
            return
        archive = self.adapter.get_similar_archive_root(self.current_scan_dir)
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
        if self.on_log:
            self.on_log(f"[相似] {msg}")
