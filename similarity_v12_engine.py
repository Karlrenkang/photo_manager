"""
照片去重工具 V1.2 - 相似图片检测独立引擎

基于感知哈希（pHash）的相似图片检测、分组、移动及撤销功能。
完全独立，不依赖 V1 的 core/、storage/、gui_worker.py 任何模块。

依赖：Pillow, imagehash, shutil, pathlib, csv, dataclasses（标准库）

用法：
    from similarity_v12_engine import SimilarityEngine

    engine = SimilarityEngine(source_dir=r"E:\\photos", similarity_level="high")
    engine.run(progress_callback=on_progress)
    summary = engine.get_summary()
    ok, msg = engine.undo_last_similarity_scan()
"""

import os
import csv
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Callable, Tuple

from PIL import Image
import imagehash


# ============================================================
# 数据结构
# ============================================================

@dataclass
class ImageInfo:
    """图片信息数据类，存储路径、大小、修改时间和感知哈希值。"""
    path: Path          # 完整路径
    size: int           # 文件大小（字节）
    mtime: float        # 修改时间戳
    p_hash: str = ""    # 感知哈希值（hex 字符串）


@dataclass
class SimilarGroup:
    """相似图片分组，包含分组ID、保留原图和需移动的副本列表。"""
    group_id: str                       # 分组ID，如 "group_001"
    keeper: Optional[ImageInfo] = None  # 保留的最优原图
    duplicates: List[ImageInfo] = field(default_factory=list)  # 需移动的副本


# ============================================================
# 并查集（Union-Find）— 用于分组去重
# ============================================================

class UnionFind:
    """
    并查集数据结构，用于将相似图片合并到同一分组。
    避免同一张图片出现在多个组中。
    """

    def __init__(self, n: int):
        """初始化 n 个独立集合。"""
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        """查找根节点（带路径压缩）。"""
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: int, y: int):
        """合并两个集合（按秩合并）。"""
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


# ============================================================
# 相似度档位配置
# ============================================================

# 三档汉明距离阈值：high(严格) / medium(平衡) / low(宽松)
SIMILARITY_THRESHOLDS = {
    "high": 6,    # 汉明距离 ≤ 6，等效 ~90% 相似度
    "medium": 9,  # 汉明距离 ≤ 9，等效 ~85% 相似度
    "low": 19,    # 汉明距离 ≤ 19，等效 ~70% 相似度
}

# 扫描时自动跳过的文件夹名称
SKIP_DIRS = {"duplicates", "scanned", "similar_photos"}

# 支持的图片后缀
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".tiff", ".tif"}


# ============================================================
# 主引擎类
# ============================================================

class SimilarityEngine:
    """
    V1.2 相似图片检测引擎。

    基于感知哈希（pHash）检测相似图片，按汉明距离分组，
    每组保留体积最大的原图，其余副本移入「similar_photos/group_xxx/」目录。

    核心特性：
    - 三档相似度参数控制（high/medium/low）
    - CSV 追加日志（每移动一张立刻写入，防断电丢失）
    - 全局撤销（读 CSV 反向还原）
    - 进度回调接口（对接 GUI 多线程）
    - 内存哈希缓存（避免重复 IO）
    """

    def __init__(self, source_dir: str, similarity_level: str = "high",
                 csv_log_path: Optional[str] = None):
        """
        初始化引擎。

        Args:
            source_dir: 待扫描的源文件夹路径
            similarity_level: 相似度档位 — "high" / "medium" / "low"
            csv_log_path: CSV 日志路径（默认在 source_dir 下）
        """
        self.source_dir = Path(source_dir).resolve()

        # 校验档位参数
        if similarity_level not in SIMILARITY_THRESHOLDS:
            raise ValueError(f"无效的相似度档位: {similarity_level}，可选: {list(SIMILARITY_THRESHOLDS.keys())}")
        self.similarity_level = similarity_level
        self.threshold = SIMILARITY_THRESHOLDS[similarity_level]

        # CSV 日志路径
        if csv_log_path:
            self.csv_path = Path(csv_log_path)
        else:
            self.csv_path = self.source_dir / "similar_move_record.csv"

        # 归档根目录
        self.archive_dir = self.source_dir / "similar_photos"

        # 破损图片日志
        self.broken_log_path = self.source_dir / "broken_image_log.txt"

        # 内存哈希缓存 — 存储全部计算完哈希的图片对象，实例销毁自动释放
        self._img_info_cache: List[ImageInfo] = []

        # 统计结果缓存
        self._summary: Dict = {
            "scan_total": 0,
            "similar_group_count": 0,
            "moved_dup_count": 0,
            "broken_img_count": 0,
        }

        # 前置：自动创建归档根目录
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    # ───────────────────────────────────────────────────────
    # 公开方法
    # ───────────────────────────────────────────────────────

    def run(self, progress_callback: Optional[Callable] = None) -> None:
        """
        一键执行完整相似检测流程。

        流程：备份旧CSV → 扫描 → 哈希 → 分组 → 移动

        Args:
            progress_callback: 可选进度回调函数
                签名: callback(stage: str, current: int, total: int, msg: str)
                stage 取值: "扫描文件" | "计算哈希" | "分组比对" | "移动文件"
        """
        # 多轮日志隔离：备份旧 CSV，新建空白 CSV
        self._backup_old_csv()

        # 第一步：扫描 + 哈希计算（合并为一步，结果存入内存缓存）
        self._scan_and_hash(progress_callback)

        # 第二步：按汉明距离分组（并查集 + 过滤单张组）
        groups = self._find_similar_groups(progress_callback)

        # 第三步：每组选择最优保留 + 移动副本
        self._move_duplicates(groups, progress_callback)

    def get_summary(self) -> Dict:
        """
        获取本次扫描的统计结果。

        Returns:
            结构化统计字典：
            {
                "scan_total": 426,          # 参与扫描总图片
                "similar_group_count": 36,  # 相似分组总数
                "moved_dup_count": 124,     # 已移动副本总数
                "broken_img_count": 3       # 损坏跳过图片数量
            }
        """
        return self._summary.copy()

    def undo_last_similarity_scan(self) -> Tuple[bool, str]:
        """
        全局撤销最近一次相似扫描操作。

        读取 CSV 日志，逐条反向移动副本回到原始路径。
        文件丢失或损坏则记录到 broken_image_log.txt，不中断整体流程。
        撤销完成后自动清理空的分组文件夹。

        Returns:
            (True, "撤销成功，还原 124 个文件")
            (False, "撤销失败：CSV日志不存在")
        """
        # 检查 CSV 日志是否存在
        if not self.csv_path.exists():
            return False, "撤销失败：CSV日志不存在"

        # 读取全部 CSV 记录
        records = []
        try:
            with open(self.csv_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                records = list(reader)
        except Exception as e:
            return False, f"撤销失败：读取CSV出错 - {e}"

        if not records:
            return False, "撤销失败：CSV日志为空"

        restored_count = 0
        broken_count = 0
        broken_entries = []

        # ── 核心撤销逻辑：逐条反向移动 ─
        for record in records:
            original_path = Path(record["original_path"])
            moved_path = Path(record["moved_path"])

            try:
                if not moved_path.exists():
                    # 文件已丢失或损坏
                    broken_entries.append(f"[{record['group_id']}] {moved_path} - 文件不存在")
                    broken_count += 1
                    continue

                # 确保原始目录存在
                original_path.parent.mkdir(parents=True, exist_ok=True)

                # 反向移动：从归档目录移回原始位置
                shutil.move(str(moved_path), str(original_path))
                restored_count += 1

            except PermissionError:
                broken_entries.append(f"[{record['group_id']}] {moved_path} - 权限不足")
                broken_count += 1
            except Exception as e:
                broken_entries.append(f"[{record['group_id']}] {moved_path} - {e}")
                broken_count += 1

        # 记录破损文件到日志
        if broken_entries:
            try:
                with open(self.broken_log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n=== 撤销时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                    for entry in broken_entries:
                        f.write(entry + "\n")
            except Exception:
                pass

        # 撤销完成后：清理空的分组文件夹
        self._cleanup_empty_dirs()

        # 清空 CSV（标记已撤销）
        try:
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["group_id", "original_path", "moved_path", "timestamp"])
        except Exception:
            pass

        # 更新统计
        self._summary["moved_dup_count"] = 0
        self._summary["similar_group_count"] = 0

        # 构建返回消息
        if broken_count > 0:
            msg = f"撤销完成，还原 {restored_count} 个文件，{broken_count} 个文件丢失已记录"
        else:
            msg = f"撤销成功，还原 {restored_count} 个文件"

        return True, msg

    # ───────────────────────────────────────────────────────
    # 内部方法
    # ───────────────────────────────────────────────────────

    def _scan_and_hash(self, progress_callback: Optional[Callable]) -> None:
        """
        扫描源目录并计算感知哈希，结果存入内存缓存。

        自动跳过 duplicates、scanned、similar_photos 三类文件夹。
        损坏图片跳过并计数，不终止流程。
        """
        self._img_info_cache.clear()
        broken = 0

        # ── 第一阶段：扫描文件列表 ──
        image_paths = []
        try:
            for dirpath, dirnames, filenames in os.walk(self.source_dir):
                # 过滤：移除需要跳过的子目录（原地修改 dirnames）
                dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]

                for filename in filenames:
                    ext = Path(filename).suffix.lower()
                    if ext not in IMAGE_EXTENSIONS:
                        continue
                    full_path = Path(dirpath) / filename
                    image_paths.append(full_path)

                    if progress_callback:
                        progress_callback("扫描文件", len(image_paths), 0, f"发现 {filename}")
        except PermissionError:
            pass
        except Exception:
            pass

        total = len(image_paths)
        self._summary["scan_total"] = total

        # ── 第二阶段：逐张计算感知哈希 ──
        for idx, img_path in enumerate(image_paths):
            try:
                stat = img_path.stat()
                img_info = ImageInfo(
                    path=img_path,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                )

                # 计算感知哈希（pHash）
                with Image.open(img_path) as img:
                    img_hash = imagehash.phash(img)
                img_info.p_hash = str(img_hash)

                # 存入内存缓存
                self._img_info_cache.append(img_info)

                if progress_callback:
                    progress_callback("计算哈希", idx + 1, total, f"正在处理 {img_path.name}")

            except Exception:
                # 损坏图片、权限不足等 — 跳过，不终止
                broken += 1
                if progress_callback:
                    progress_callback("计算哈希", idx + 1, total, f"跳过损坏文件 {img_path.name}")

        self._summary["broken_img_count"] = broken

    def _find_similar_groups(self, progress_callback: Optional[Callable] = None) -> List[SimilarGroup]:
        """
        使用并查集按汉明距离将相似图片分组。

        两两比对所有图片的 pHash，距离 ≤ 阈值则合并到同一组。
        分组结束后过滤掉单张图片的组（非相似）。

        Returns:
            过滤后的 SimilarGroup 列表（每组 ≥ 2 张图片）
        """
        images = self._img_info_cache
        n = len(images)

        if n == 0:
            return []

        # 初始化并查集
        uf = UnionFind(n)

        # ─ 两两比对汉明距离 ─
        pair_count = 0
        total_pairs = n * (n - 1) // 2

        for i in range(n):
            for j in range(i + 1, n):
                pair_count += 1

                # 计算汉明距离（XOR 后统计 1 的位数）
                hash_a = images[i].p_hash
                hash_b = images[j].p_hash

                if not hash_a or not hash_b:
                    continue

                distance = self._hamming_distance(hash_a, hash_b)

                if distance <= self.threshold:
                    uf.union(i, j)

                if progress_callback and pair_count % 100 == 0:
                    progress_callback("分组比对", pair_count, total_pairs,
                                      f"已比对 {pair_count}/{total_pairs} 对")

        # ─ 按根节点收集分组 ──
        group_map: Dict[int, List[int]] = {}
        for i in range(n):
            root = uf.find(i)
            if root not in group_map:
                group_map[root] = []
            group_map[root].append(i)

        # ── 构建 SimilarGroup 列表 ──
        raw_groups = []
        for root, indices in group_map.items():
            if len(indices) < 2:
                # 单张图片，非相似，直接丢弃
                continue

            group_images = [images[i] for i in indices]
            # 选择最优保留
            keeper, duplicates = self._select_keeper(group_images)

            group = SimilarGroup(
                group_id=f"group_{len(raw_groups) + 1:03d}",  # 3位数字自增
                keeper=keeper,
                duplicates=duplicates,
            )
            raw_groups.append(group)

        self._summary["similar_group_count"] = len(raw_groups)

        if progress_callback:
            progress_callback("分组比对", total_pairs, total_pairs,
                              f"完成，共 {len(raw_groups)} 个相似分组")

        return raw_groups

    @staticmethod
    def _hamming_distance(hash_a: str, hash_b: str) -> int:
        """
        计算两个 hex 哈希字符串的汉明距离。

        将 hex 转为整数后 XOR，统计结果中 1 的位数。
        """
        try:
            a = int(hash_a, 16)
            b = int(hash_b, 16)
            xor = a ^ b
            return bin(xor).count("1")
        except (ValueError, TypeError):
            return 999  # 无效哈希视为不相似

    @staticmethod
    def _select_keeper(images: List[ImageInfo]) -> Tuple[ImageInfo, List[ImageInfo]]:
        """
        从相似图片组中选择最优保留原图。

        规则：
        1. 文件体积最大 → 保留
        2. 体积相同 → 修改时间最早 → 保留

        Returns:
            (keeper, duplicates_list)
        """
        # 按体积降序排序，体积相同按修改时间升序（最早的在前）
        sorted_images = sorted(images, key=lambda img: (-img.size, img.mtime))
        keeper = sorted_images[0]
        duplicates = sorted_images[1:]
        return keeper, duplicates

    def _move_duplicates(self, groups: List[SimilarGroup],
                         progress_callback: Optional[Callable] = None) -> None:
        """
        将每组中的副本移入「similar_photos/group_xxx/」目录。

        每成功移动一张，立刻追加写入 CSV 日志（防断电丢失）。
        keeper 留在原始目录不移动。
        """
        moved_count = 0

        for group in groups:
            # 创建分组目录
            group_dir = self.archive_dir / group.group_id
            group_dir.mkdir(parents=True, exist_ok=True)

            for dup in group.duplicates:
                try:
                    # 生成目标路径，处理同名冲突
                    dest = self._unique_path(group_dir, dup.path.name)

                    # 执行移动
                    shutil.move(str(dup.path), str(dest))
                    moved_count += 1

                    # ── 核心：每移动一张，立刻追加写入 CSV ──
                    self._append_csv_log(group.group_id, dup.path, dest)

                    if progress_callback:
                        progress_callback("移动文件", moved_count, 0,
                                          f"已移动 {dup.path.name} → {group.group_id}")

                except PermissionError:
                    self._summary["broken_img_count"] += 1
                    if progress_callback:
                        progress_callback("移动文件", moved_count, 0,
                                          f"权限不足跳过 {dup.path.name}")
                except Exception as e:
                    self._summary["broken_img_count"] += 1
                    if progress_callback:
                        progress_callback("移动文件", moved_count, 0,
                                          f"移动失败 {dup.path.name}: {e}")

        self._summary["moved_dup_count"] = moved_count

    def _append_csv_log(self, group_id: str, original_path: Path, moved_path: Path) -> None:
        """
        单条追加写入 CSV 日志。

        使用 append 模式，每移动一张立刻写入并 flush，
        防止断电或程序崩溃导致日志丢失。

        Args:
            group_id: 分组ID
            original_path: 原始完整路径
            moved_path: 移动后路径
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([group_id, str(original_path), str(moved_path), timestamp])
                f.flush()  # 强制刷盘
        except Exception:
            pass

    def _backup_old_csv(self) -> None:
        """
        多轮日志隔离：将旧 CSV 重命名备份，新建空白 CSV。

        保证每次撤销只还原最近一次操作，不会混入历史记录。
        """
        if self.csv_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"similar_move_record_backup_{timestamp}.csv"
            backup_path = self.csv_path.parent / backup_name
            try:
                self.csv_path.rename(backup_path)
            except Exception:
                pass

        # 新建空白 CSV（带表头）
        try:
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["group_id", "original_path", "moved_path", "timestamp"])
        except Exception:
            pass

    def _cleanup_empty_dirs(self) -> None:
        """
        清理空的分组文件夹。

        遍历「similar_photos/」下所有 group_xxx 文件夹：
        - 空文件夹 → 删除
        - 有残留文件的文件夹 → 保留
        """
        if not self.archive_dir.exists():
            return

        try:
            for item in self.archive_dir.iterdir():
                if item.is_dir() and item.name.startswith("group_"):
                    # 检查是否为空目录
                    if not any(item.iterdir()):
                        item.rmdir()
        except Exception:
            pass

    @staticmethod
    def _unique_path(dest_dir: Path, filename: str) -> Path:
        """
        生成不冲突的目标路径。

        若目标已存在同名文件，循环递增 _1/_2/_3 后缀直到路径不存在。
        """
        dest = dest_dir / filename
        if not dest.exists():
            return dest

        stem = dest.stem
        suffix = dest.suffix
        counter = 1
        while True:
            new_name = f"{stem}_{counter}{suffix}"
            dest = dest_dir / new_name
            if not dest.exists():
                return dest
            counter += 1
