"""
Photo Manager V1.3 - 相似引擎适配器

封装 SimilarityEngine 调用，隔离界面与引擎。
- 后台线程运行扫描，队列传递进度
- 内存缓存分组列表、统计数据、缩略图
- 支持全局撤销、单组还原、单张还原
- 支持中途终止扫描
"""

import os
import csv
import queue
import shutil
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple

from PIL import Image

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from similarity_v12_engine import SimilarityEngine


class SimilarAdapter:
    """
    相似引擎适配器 — GUI 与 SimilarityEngine 之间的桥梁。

    核心职责：
    - 后台线程调用引擎，通过 Queue 推送进度到 GUI
    - 缓存分组列表和统计数据，避免重复解析 CSV
    - 缩略图内存缓存，避免重复解码图片
    - 支持全局/单组/单张还原
    - 支持中途终止扫描
    """

    def __init__(self, progress_queue: queue.Queue):
        """
        Args:
            progress_queue: GUI 主线程轮询的消息队列
        """
        self.progress_queue = progress_queue
        self.engine: Optional[SimilarityEngine] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 内存缓存
        self._cached_group_list: Optional[List[Dict]] = None
        self._cached_summary: Optional[Dict] = None
        self._thumb_cache: Dict[str, Image.Image] = {}

        # 当前扫描参数（用于撤销时重建引擎）
        self._current_source_dir: str = ""
        self._current_level: str = "high"

    # ───────────────────────────────────────────────────────
    # 缓存管理
    # ───────────────────────────────────────────────────────

    def invalidate_cache(self):
        """清除全部缓存（分组、统计、缩略图）。

        触发时机：新扫描、撤销、切换输入文件夹。
        """
        self._cached_group_list = None
        self._cached_summary = None
        self._thumb_cache.clear()

    # ───────────────────────────────────────────────────────
    # 扫描
    # ───────────────────────────────────────────────────────

    def run_scan(self, source_dir: str, level: str) -> None:
        """
        后台线程启动相似扫描。

        进入即清除旧缓存，防止不同相册数据串扰。

        Args:
            source_dir: 源文件夹路径
            level: 相似度档位 "high" / "medium" / "low"
        """
        # 约束：切换相册自动清空旧缓存
        self.invalidate_cache()

        self._current_source_dir = source_dir
        self._current_level = level
        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._scan_worker,
            args=(source_dir, level),
            daemon=True,
        )
        self._thread.start()

    def _scan_worker(self, source_dir: str, level: str):
        """后台扫描工作线程。"""
        try:
            self.engine = SimilarityEngine(source_dir, similarity_level=level)

            # 进度回调 → 转发到 GUI 队列
            def on_progress(stage, current, total, msg):
                if self._stop_event.is_set():
                    return
                self.progress_queue.put(("similar_progress", stage, current, total, msg))

            self.engine.run(progress_callback=on_progress)

            # 扫描完成 → 缓存统计数据
            self._cached_summary = self.engine.get_summary()
            self.progress_queue.put(("similar_done", True, self._cached_summary))

        except Exception as e:
            self.progress_queue.put(("similar_error", str(e)))
            self.progress_queue.put(("similar_done", False, None))

    def stop_scan(self):
        """设置终止标记，安全中断后台扫描线程。"""
        self._stop_event.set()

    def is_running(self) -> bool:
        """检查扫描是否正在进行。"""
        return self._thread is not None and self._thread.is_alive()

    # ───────────────────────────────────────────────────────
    # 撤销
    # ───────────────────────────────────────────────────────

    def undo_all(self) -> Tuple[bool, str]:
        """全局撤销最近一次相似扫描。"""
        if not self.engine:
            return False, "撤销失败：未执行过相似扫描"
        try:
            ok, msg = self.engine.undo_last_similarity_scan()
            if ok:
                self.invalidate_cache()
            return ok, msg
        except Exception as e:
            return False, f"撤销失败：{e}"

    def undo_single_group(self, group_id: str) -> Tuple[bool, str]:
        """
        仅还原指定 group_id 内全部副本。

        从 CSV 筛选该 group_id 的记录，逐条反向移动。
        """
        if not self.engine:
            return False, "撤销失败：未执行过相似扫描"

        csv_path = self.engine.csv_path
        if not csv_path.exists():
            return False, "CSV 日志不存在"

        records = self._read_csv_records(csv_path)
        group_records = [r for r in records if r["group_id"] == group_id]

        if not group_records:
            return False, f"分组 {group_id} 无记录"

        restored = 0
        broken = 0
        for rec in group_records:
            moved = Path(rec["moved_path"])
            original = Path(rec["original_path"])
            try:
                if not moved.exists():
                    broken += 1
                    continue
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(moved), str(original))
                restored += 1
            except Exception:
                broken += 1

        # 从 CSV 中移除已还原的记录
        remaining = [r for r in records if r["group_id"] != group_id]
        self._write_csv_records(csv_path, remaining)

        self.invalidate_cache()

        if broken > 0:
            return True, f"还原 {restored} 个，{broken} 个文件丢失"
        return True, f"还原成功，共 {restored} 个文件"

    def undo_single_file(self, original_path: str) -> Tuple[bool, str]:
        """
        仅还原选中单张副本图片。
        """
        if not self.engine:
            return False, "撤销失败：未执行过相似扫描"

        csv_path = self.engine.csv_path
        if not csv_path.exists():
            return False, "CSV 日志不存在"

        records = self._read_csv_records(csv_path)
        target = None
        for r in records:
            if r["original_path"] == original_path:
                target = r
                break

        if not target:
            return False, "未找到该文件的移动记录"

        moved = Path(target["moved_path"])
        original = Path(target["original_path"])

        try:
            if not moved.exists():
                return False, "文件已不存在，无法还原"
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(moved), str(original))

            # 从 CSV 移除该记录
            remaining = [r for r in records if r["original_path"] != original_path]
            self._write_csv_records(csv_path, remaining)

            self.invalidate_cache()
            return True, f"还原成功：{original.name}"
        except Exception as e:
            return False, f"还原失败：{e}"

    # ───────────────────────────────────────────────────────
    # 数据读取（带缓存）
    # ───────────────────────────────────────────────────────

    def get_group_list(self) -> List[Dict]:
        """
        获取分组列表（带缓存）。

        Returns:
            [{"group_id": "group_001", "total": 3, "keeper": "...", "dup_count": 2, "duplicates": [...]}]
        """
        if self._cached_group_list is not None:
            return self._cached_group_list

        if not self.engine or not self.engine.csv_path.exists():
            return []

        records = self._read_csv_records(self.engine.csv_path)
        groups = self._parse_groups(records)
        self._cached_group_list = groups
        return groups

    def get_summary_data(self) -> Dict:
        """获取统计数据（带缓存）。"""
        if self._cached_summary is not None:
            return self._cached_summary

        if self.engine:
            self._cached_summary = self.engine.get_summary()
            return self._cached_summary

        return {"scan_total": 0, "similar_group_count": 0, "moved_dup_count": 0, "broken_img_count": 0}

    def get_similar_archive_root(self, source_dir: str) -> str:
        """动态获取当前相册的 similar_photos 归档目录路径。"""
        return os.path.join(source_dir, "similar_photos")

    # ───────────────────────────────────────────────────────
    # 缩略图
    # ───────────────────────────────────────────────────────

    def get_thumbnail(self, path: str, size: int = 128) -> Optional[Image.Image]:
        """
        获取缩略图（带内存缓存）。

        Args:
            path: 图片完整路径
            size: 缩略图边长（像素）

        Returns:
            PIL Image 缩略图，或 None（文件不存在/损坏）
        """
        if path in self._thumb_cache:
            return self._thumb_cache[path]

        try:
            if not os.path.exists(path):
                return None

            with Image.open(path) as img:
                img.thumbnail((size, size), Image.LANCZOS)
                thumb = img.copy()

            self._thumb_cache[path] = thumb
            return thumb
        except Exception:
            return None

    # ───────────────────────────────────────────────────────
    # CSV 工具方法
    # ──────────────────────────────────────────────────────

    @staticmethod
    def _read_csv_records(csv_path: Path) -> List[Dict]:
        """读取 CSV 日志全部记录。"""
        records = []
        try:
            with open(csv_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                records = list(reader)
        except Exception:
            pass
        return records

    @staticmethod
    def _write_csv_records(csv_path: Path, records: List[Dict]):
        """覆写 CSV 日志。"""
        try:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["group_id", "original_path", "moved_path", "timestamp"])
                writer.writeheader()
                writer.writerows(records)
        except Exception:
            pass

    def _parse_groups(self, records: List[Dict]) -> List[Dict]:
        """从 CSV 记录解析分组列表。"""
        group_map: Dict[str, Dict] = {}

        for rec in records:
            gid = rec["group_id"]
            if gid not in group_map:
                group_map[gid] = {
                    "group_id": gid,
                    "keeper": "",
                    "duplicates": [],
                }
            group_map[gid]["duplicates"].append({
                "original_path": rec["original_path"],
                "moved_path": rec["moved_path"],
                "timestamp": rec["timestamp"],
            })

        # 计算总数和保留图（未出现在 CSV 中的同组图片即为 keeper）
        groups = []
        for gid, data in sorted(group_map.items()):
            dup_count = len(data["duplicates"])
            total = dup_count + 1  # keeper + duplicates
            groups.append({
                "group_id": gid,
                "total": total,
                "keeper": "",  # keeper 未移动，无路径记录
                "dup_count": dup_count,
                "duplicates": data["duplicates"],
            })

        return groups

    # ───────────────────────────────────────────────────────
    # CSV 导出
    # ──────────────────────────────────────────────────────

    def export_csv(self, dest_path: str) -> bool:
        """导出分组清单 CSV 到指定路径。"""
        groups = self.get_group_list()
        try:
            with open(dest_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["分组ID", "组内总数", "移出副本数", "副本路径"])
                for g in groups:
                    for dup in g["duplicates"]:
                        writer.writerow([g["group_id"], g["total"], g["dup_count"], dup["moved_path"]])
            return True
        except Exception:
            return False
