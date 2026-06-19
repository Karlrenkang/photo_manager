"""
Photo Manager V1.3 - 设置持久化模块

将相似度档位、上次输入目录等配置持久化到 settings.json。
配置文件位于 %APPDATA%/PhotoManager/settings.json。

容错设计：
- JSON 损坏 / 文件不存在 / 字段缺失 → 返回默认配置 + 重写文件，程序不崩溃。
"""

import os
import json
from pathlib import Path


# 默认配置
_DEFAULT_SETTINGS = {
    "similarity_level": "high",   # 默认高严格档位
    "last_input_dir": "",         # 上次选择的文件夹路径
}

# 配置文件路径：%APPDATA%/PhotoManager/settings.json
_APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
_SETTINGS_DIR = os.path.join(_APPDATA, "PhotoManager")
SETTINGS_PATH = os.path.join(_SETTINGS_DIR, "settings.json")


def load_settings() -> dict:
    """
    读取设置文件。

    异常兜底：
    - 文件不存在 → 返回默认配置
    - JSON 解码失败 → 返回默认配置 + 重写文件
    - 必要字段缺失 → 返回默认配置 + 重写文件

    Returns:
        配置字典 {"similarity_level": str, "last_input_dir": str}
    """
    try:
        if not os.path.exists(SETTINGS_PATH):
            return _DEFAULT_SETTINGS.copy()

        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 校验必要字段
        if "similarity_level" not in data or "last_input_dir" not in data:
            raise ValueError("缺少必要字段")

        # 校验档位值合法性
        if data["similarity_level"] not in ("high", "medium", "low"):
            raise ValueError(f"无效档位: {data['similarity_level']}")

        return data

    except (json.JSONDecodeError, FileNotFoundError, ValueError, Exception):
        # 任何异常 → 返回默认配置并写入磁盘
        default = _DEFAULT_SETTINGS.copy()
        save_settings(default)
        return default


def save_settings(data: dict) -> bool:
    """
    写入设置文件。

    Args:
        data: 配置字典

    Returns:
        True 成功，False 失败
    """
    try:
        os.makedirs(_SETTINGS_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def get_similarity_level() -> str:
    """快捷获取当前保存的相似度档位。"""
    return load_settings().get("similarity_level", "high")


def get_last_input_dir() -> str:
    """快捷获取上次选择的输入目录。"""
    return load_settings().get("last_input_dir", "")
