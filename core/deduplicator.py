"""
照片去重工具 - 核心去重模块
实现 MD5 计算和重复文件检测逻辑
"""

import hashlib
from pathlib import Path
from typing import List, Dict, Tuple
import shutil

from utils.file_utils import get_filename


def calculate_md5(file_path: Path) -> str:
    """
    计算文件的 MD5 哈希值

    参数:
        file_path: 文件路径

    返回:
        MD5 哈希值字符串（小写十六进制）
    """
    md5_hash = hashlib.md5()

    try:
        # 以二进制模式读取文件，分块计算 MD5
        with open(file_path, 'rb') as f:
            # 每次读取 8KB
            for chunk in iter(lambda: f.read(8192), b''):
                md5_hash.update(chunk)

        return md5_hash.hexdigest()
    except OSError as e:
        print(f"警告: 无法读取文件 {file_path}: {e}")
        return ""


def group_by_md5(files: List[Path]) -> Dict[str, List[Path]]:
    """
    按 MD5 哈希值分组

    参数:
        files: 文件路径列表

    返回:
        字典，键为 MD5 值，值为相同 MD5 的文件路径列表
    """
    md5_groups = {}

    for file_path in files:
        md5_value = calculate_md5(file_path)

        # 跳过无法读取的文件
        if not md5_value:
            continue

        if md5_value not in md5_groups:
            md5_groups[md5_value] = []

        md5_groups[md5_value].append(file_path)

    return md5_groups


def find_duplicates(files: List[Path]) -> List[Tuple[Path, List[Path]]]:
    """
    找出重复文件

    参数:
        files: 文件路径列表

    返回:
        列表，每个元素是 (保留文件, 重复文件列表) 的元组
    """
    # 先按 MD5 分组
    md5_groups = group_by_md5(files)

    duplicates = []

    for md5_value, file_list in md5_groups.items():
        # 只有一个文件，不是重复
        if len(file_list) <= 1:
            continue

        # 按文件名排序，保留文件名最小的
        sorted_files = sorted(file_list, key=get_filename)
        keep_file = sorted_files[0]
        duplicate_files = sorted_files[1:]

        duplicates.append((keep_file, duplicate_files))

    return duplicates


def move_duplicates(duplicates: List[Tuple[Path, List[Path]]], target_folder: str) -> int:
    """
    将重复文件移动到目标文件夹

    参数:
        duplicates: 重复文件列表，每个元素是 (保留文件, 重复文件列表)
        target_folder: 目标文件夹路径

    返回:
        成功移动的文件数量
    """
    target_path = Path(target_folder)

    # 创建目标文件夹（如果不存在）
    if not target_path.exists():
        target_path.mkdir(parents=True, exist_ok=True)

    moved_count = 0

    for keep_file, duplicate_files in duplicates:
        print(f"\n保留: {keep_file}")

        for dup_file in duplicate_files:
            # 生成目标路径，避免文件名冲突
            target_file = target_path / dup_file.name

            # 如果目标文件已存在，添加序号
            counter = 1
            while target_file.exists():
                stem = dup_file.stem
                suffix = dup_file.suffix
                target_file = target_path / f"{stem}_{counter}{suffix}"
                counter += 1

            try:
                # 移动文件
                shutil.move(str(dup_file), str(target_file))
                print(f"  移动: {dup_file} -> {target_file}")
                moved_count += 1
            except OSError as e:
                print(f"  错误: 无法移动 {dup_file}: {e}")

    return moved_count
