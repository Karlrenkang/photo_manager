"""Background worker for running scan operations without freezing the UI."""

import os
import threading
import queue
import sys
from datetime import datetime
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.scanner import scan_folder
from core.index_builder import build_index
from core.group_engine import group_by_md5
from core.deduper import HistoryDB, process_groups
from utils.paths import get_base_dir, get_history_db_path


MSG_LOG = "log"
MSG_PROGRESS = "progress"
MSG_RESULT = "result"
MSG_ERROR = "error"
MSG_DONE = "done"


class ScanWorker:
    """Runs the dedup pipeline in a background thread."""

    def __init__(self, input_folder: str, msg_queue: queue.Queue,
                 on_complete: Optional[Callable] = None):
        self.input_folder = input_folder
        self.msg_queue = msg_queue
        self.on_complete = on_complete
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _log(self, message: str):
        self.msg_queue.put((MSG_LOG, message))

    def _progress(self, value: float, status: str):
        self.msg_queue.put((MSG_PROGRESS, value, status))

    def _run(self):
        try:
            base_dir = get_base_dir()
            db_path = get_history_db_path()
            duplicates_dir = os.path.join(self.input_folder, "Duplicates")
            scanned_dir = os.path.join(self.input_folder, "Scanned")

            # STEP 1: Scan
            self._progress(0.0, "正在扫描图片文件...")
            self._log(f"开始扫描: {self.input_folder}")

            images = scan_folder(self.input_folder)
            total = len(images)
            self._log(f"找到 {total} 个图片文件")

            if total == 0:
                self._log("未找到图片文件")
                self.msg_queue.put((MSG_RESULT, {
                    "total": 0, "dup_groups": 0,
                    "moved_dup": 0, "moved_scan": 0, "errors": [],
                }))
                self.msg_queue.put((MSG_DONE, True))
                return

            if self._stop_event.is_set():
                self._log("扫描已终止")
                self.msg_queue.put((MSG_DONE, False))
                return

            # STEP 2: Index
            self._progress(0.2, "正在建立索引（大小剪枝 + MD5）...")
            self._log("正在建立索引...")
            candidates = build_index(images)
            self._log(f"{len(candidates)} 个文件需要 MD5 比对")

            if self._stop_event.is_set():
                self.msg_queue.put((MSG_DONE, False))
                return

            # STEP 3: Group
            self._progress(0.5, "正在按 MD5 分组...")
            self._log("正在按 MD5 分组...")
            groups = group_by_md5(candidates)
            dup_groups = [g for g in groups if len(g.images) >= 2]
            self._log(f"共 {len(groups)} 组，{len(dup_groups)} 组有重复")

            if self._stop_event.is_set():
                self.msg_queue.put((MSG_DONE, False))
                return

            # STEP 4: Process
            self._progress(0.7, "正在执行去重...")
            self._log("正在执行去重（含历史记录）...")
            history = HistoryDB(db_path)
            moved_dup, moved_scan, error_files = process_groups(
                groups, history, duplicates_dir, scanned_dir
            )

            if self._stop_event.is_set():
                self.msg_queue.put((MSG_DONE, False))
                return

            # STEP 5: Commit history
            self._progress(0.95, "正在提交历史记录...")
            if history.commit():
                self._log("历史记录已保存")
            else:
                self._log("警告: 历史记录保存失败！")

            self._progress(1.0, "完成")
            self._log("去重完成！")

            self.msg_queue.put((MSG_RESULT, {
                "total": total,
                "dup_groups": len(dup_groups),
                "moved_dup": moved_dup,
                "moved_scan": moved_scan,
                "errors": error_files,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }))
            self.msg_queue.put((MSG_DONE, True))

        except Exception as e:
            self._log(f"错误: {e}")
            self.msg_queue.put((MSG_ERROR, str(e)))
            self.msg_queue.put((MSG_DONE, False))

        finally:
            if self.on_complete:
                self.on_complete()
