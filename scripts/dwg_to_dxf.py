#!/usr/bin/env python3
"""DWG转DXF - 使用多种方法"""

import subprocess
import requests
import time
from pathlib import Path


def convert_with_librecad_batch():
    """使用LibreCAD批处理脚本"""
    dwg_path = Path("docs/references/村庄规划总图/金田村村庄规划工程文件/3.村庄建设项目布局规划图/03金田村建设项目布局规划图.dwg")
    output_path = Path("docs/gis/jintian_dxf/03金田村建设项目布局规划图.dxf")

    # 创建LibreCAD批处理脚本
    script_content = f"""
// LibreCAD script to convert DWG to DXF
open("{dwg_path.absolute()}")
saveas("{output_path.absolute()}", "DXF 2018")
quit
"""

    script_path = Path("docs/gis/jintian_dxf/convert.script")
    script_path.write_text(script_content)

    print("请手动使用LibreCAD转换:")
    print(f"  1. 打开LibreCAD")
    print(f"  2. 文件 -> 打开 -> {dwg_path}")
    print(f"  3. 文件 -> 另存为 -> {output_path}")
    print(f"  4. 保存类型选择: DXF 2018")


def convert_with_odafb():
    """尝试使用ODA File Converter"""
    source_dir = Path("docs/references/村庄规划总图/金田村村庄规划工程文件/3.村庄建设项目布局规划图")
    target_dir = Path("docs/gis/jintian_dxf")

    oda_path = Path("C:/Program Files/ODA/ODAFileConverter.exe")
    if not oda_path.exists():
        print("ODA File Converter未安装")
        print("请从 https://www.opendesign.com/guestfiles/oda_file_converter 下载安装")
        return False

    cmd = [
        str(oda_path),
        str(source_dir),
        str(target_dir),
        "*.dwg",
        "ACAD2018",
        "0",
        "0"
    ]

    print(f"运行: {cmd}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    print(result.stderr)
    return result.returncode == 0


def convert_online():
    """在线转换服务"""
    dwg_path = Path("docs/references/村庄规划总图/金田村村庄规划工程文件/3.村庄建设项目布局规划图/03金田村建设项目布局规划图.dwg")
    output_path = Path("docs/gis/jintian_dxf/03金田村建设项目布局规划图.dxf")

    print("\n在线转换方案:")
    print(f"  1. 访问 https://convertio.co/dwg-dxf/")
    print(f"  2. 上传文件: {dwg_path}")
    print(f"  3. 下载转换后的DXF，保存到: {output_path}")
    print(f"  4. 完成后运行: python scripts/extract_dwg_to_geojson.py")


def main():
    print("DWG转DXF转换工具")
    print("=" * 50)

    # 检查目标目录
    target_dir = Path("docs/gis/jintian_dxf")
    target_dir.mkdir(parents=True, exist_ok=True)

    # 检查是否已经有DXF
    existing_dxf = target_dir / "03金田村建设项目布局规划图.dxf"
    if existing_dxf.exists():
        print(f"DXF已存在: {existing_dxf}")
        return

    # 尝试ODA
    if convert_with_odafb():
        print("ODA转换成功!")
        return

    # 提供手动方案
    convert_with_librecad_batch()

    # 提供在线方案
    convert_online()


if __name__ == '__main__':
    main()