#!/usr/bin/env python3
"""使用Aspose.CAD免费API进行DWG转DXF"""

import requests
import time
from pathlib import Path


def convert_dwg_to_dxf_aspose():
    """使用Aspose.CAD免费API"""
    dwg_path = Path("docs/references/村庄规划总图/金田村村庄规划工程文件/3.村庄建设项目布局规划图/03金田村建设项目布局规划图.dwg")
    output_path = Path("docs/gis/jintian_dxf/03金田村建设项目布局规划图.dxf")

    # Aspose.CAD免费API端点
    url = "https://api.aspose.cloud/v3.0/cad/convert"

    print(f"上传DWG文件: {dwg_path}")
    print(f"文件大小: {dwg_path.stat().st_size / 1024:.1f} KB")

    try:
        with open(dwg_path, 'rb') as f:
            files = {'file': (dwg_path.name, f, 'application/octet-stream')}
            data = {'format': 'dxf'}

            print("正在上传转换...")
            response = requests.post(
                url,
                files=files,
                data=data,
                timeout=120
            )

            if response.status_code == 200:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                print(f"转换成功! 保存到: {output_path}")
                return True
            else:
                print(f"API返回错误: {response.status_code}")
                print(f"响应: {response.text[:500]}")
                return False

    except Exception as e:
        print(f"转换失败: {e}")
        return False


def convert_with_convertio():
    """使用Convertio API（需要API Key）"""
    print("\n手动在线转换:")
    print("  1. 访问 https://convertio.co/dwg-dxf/")
    print("  2. 上传DWG文件")
    print("  3. 等待转换完成")
    print("  4. 下载DXF文件到 docs/gis/jintian_dxf/")


def convert_with_anyconv():
    """使用anyconv.com"""
    print("\n或使用 https://anyconv.com/dwg-to-dxf-converter/")


def main():
    print("DWG转DXF - 在线转换")
    print("=" * 50)

    # 尝试Aspose API
    if convert_dwg_to_dxf_aspose():
        print("\n转换完成!")
        return

    # 提供手动方案
    convert_with_convertio()
    convert_with_anyconv()


if __name__ == '__main__':
    main()