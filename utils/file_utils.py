"""
照片去重工具 - 文件工具模块
提供文件扫描、分组等辅助功能
"""

import os
from pathlib import Path
from typing import List, Dict

# 支持的图片格式
SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.heic'}


def scan_images(folder_path: str) -> List[Path]:
    """
    扫描指定文件夹，返回所有支持的图片文件路径列表
    排除 duplicates 文件夹中的文件

    参数:
        folder_path: 要扫描的文件夹路径

    返回:
        包含所有图片文件 Path 对象的列表
    """
    folder = Path(folder_path)

    if not folder.exists():
        raise FileNotFoundError(f"文件夹不存在: {folder_path}")

    if not folder.is_dir():
        raise NotADirectoryError(f"路径不是文件夹: {folder_path}")

    image_files = []

    # 递归遍历文件夹
    for file_path in folder.rglob('*'):
        # 只处理文件
        if file_path.is_file():
            # 排除 duplicates 文件夹中的文件
            # 检查路径的任何部分是否为 'duplicates'
            if 'duplicates' in file_path.parts:
                continue

            # 检查扩展名是否支持
            if file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                image_files.append(file_path)

    return image_files


def group_by_size(files: List[Path]) -> Dict[int, List[Path]]:
    """
    按文件大小分组

    参数:
        files: 文件路径列表

    返回:
        字典，键为文件大小，值为相同大小的文件路径列表
    """
    size_groups = {}

    for file_path in files:
        try:
            size = file_path.stat().st_size

            if size not in size_groups:
                size_groups[size] = []

            size_groups[size].append(file_path)
        except OSError as e:
            # 跳过无法访问的文件
            print(f"警告: 无法读取文件 {file_path}: {e}")
            continue

    return size_groups


def get_filename(file_path: Path) -> str:
    """
    获取文件名（不含路径）

    参数:
        file_path: 文件路径

    返回:
        文件名字符串
    """
    return file_path.name
