"""
照片去重工具 V1 - 主程序入口
功能：扫描指定文件夹，找出重复图片并移动到 duplicates 文件夹
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from utils.file_utils import scan_images, group_by_size
from core.deduplicator import find_duplicates, move_duplicates


def main():
    """
    主函数：执行照片去重流程
    """
    # 检查命令行参数
    if len(sys.argv) < 2:
        print("用法: python main.py <图片文件夹路径>")
        print("示例: python main.py \"D:/photos\"")
        sys.exit(1)

    # 获取目标文件夹路径
    target_folder = sys.argv[1]

    print(f"开始扫描文件夹: {target_folder}")
    print("-" * 50)

    # 第一步：扫描所有图片文件
    try:
        image_files = scan_images(target_folder)
    except (FileNotFoundError, NotADirectoryError) as e:
        print(f"错误: {e}")
        sys.exit(1)

    print(f"找到 {len(image_files)} 个图片文件")

    if not image_files:
        print("未找到任何图片文件，程序退出")
        sys.exit(0)

    # 第二步：按文件大小分组
    print("\n正在按文件大小分组...")
    size_groups = group_by_size(image_files)

    # 只保留大小相同的文件组（可能有重复）
    potential_duplicates = []
    for size, files in size_groups.items():
        if len(files) > 1:
            potential_duplicates.extend(files)

    print(f"发现 {len(potential_duplicates)} 个文件大小相同，需要进一步检查")

    if not potential_duplicates:
        print("没有发现可能的重复文件，程序退出")
        sys.exit(0)

    # 第三步：计算 MD5 并找出重复文件
    print("\n正在计算文件 MD5 值...")
    duplicates = find_duplicates(potential_duplicates)

    if not duplicates:
        print("未发现重复文件，程序退出")
        sys.exit(0)

    # 统计重复文件数量
    total_duplicates = sum(len(dup_list) for _, dup_list in duplicates)
    print(f"\n发现 {len(duplicates)} 组重复文件，共 {total_duplicates} 个重复文件")

    # 第四步：移动重复文件到 duplicates 文件夹
    duplicates_folder = Path(target_folder) / "duplicates"
    print(f"\n正在移动重复文件到: {duplicates_folder}")
    print("-" * 50)

    moved_count = move_duplicates(duplicates, str(duplicates_folder))

    # 输出结果统计
    print("\n" + "=" * 50)
    print(f"去重完成！")
    print(f"共处理 {len(image_files)} 个图片文件")
    print(f"发现 {len(duplicates)} 组重复")
    print(f"成功移动 {moved_count} 个重复文件到: {duplicates_folder}")
    print("=" * 50)


if __name__ == "__main__":
    main()
