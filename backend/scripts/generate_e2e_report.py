"""GIS 端对端测试报告生成脚本。

运行后端 pytest 测试套件，捕获结果，生成 markdown 报告：
  - 测试执行时间和命令
  - pytest 输出摘要（通过/失败数）
  - layout_configs.json 快照链接
  - PNG 截图嵌入

用法：
  python scripts/generate_e2e_report.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
REPORT_DIR = PROJECT_ROOT / "docs" / "test-reports"
SNAPSHOT_DIR = BACKEND_ROOT / "test-screenshots"


def run_pytest_suite() -> tuple[int, str]:
    """运行 GIS E2E 测试套件并返回 (returncode, output)。"""
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/test_gis_e2e_real_data.py::TestFullPipelineE2E",
        "tests/test_gis_sse_events.py",
        "tests/test_gis_api_endpoints.py",
        "-v", "--tb=short",
    ]
    print(f"[Report] 运行: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = result.stdout + result.stderr
    return result.returncode, output


def parse_pytest_summary(output: str) -> dict:
    """从 pytest 输出提取通过/失败数。"""
    summary = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "total": 0}
    for line in output.splitlines():
        if " passed" in line and "failed" not in line:
            try:
                summary["passed"] = int(line.split(" passed")[0].split()[-1])
            except (ValueError, IndexError):
                pass
        if " failed" in line:
            try:
                summary["failed"] = int(line.split(" failed")[0].split()[-1])
            except (ValueError, IndexError):
                pass
    summary["total"] = summary["passed"] + summary["failed"]
    return summary


def load_layout_snapshot() -> dict | None:
    """加载 layout_configs 快照。"""
    snapshot_path = SNAPSHOT_DIR / "e2e_full_pipeline.json"
    if not snapshot_path.exists():
        return None
    try:
        with open(snapshot_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Report] 加载快照失败: {e}")
        return None


def render_layout_to_png() -> str | None:
    """调用 render_planning_layout.py 渲染 PNG。"""
    render_script = BACKEND_ROOT / "scripts" / "render_planning_layout.py"
    if not render_script.exists():
        print(f"[Report] 渲染脚本不存在: {render_script}")
        return None

    output_png = SNAPSHOT_DIR / "e2e_layout.png"
    cmd = [sys.executable, str(render_script), "--output", str(output_png)]
    try:
        subprocess.run(cmd, cwd=str(BACKEND_ROOT), check=True, capture_output=True, timeout=120)
        print(f"[Report] PNG 渲染: {output_png}")
        return str(output_png)
    except Exception as e:
        print(f"[Report] PNG 渲染失败: {e}")
        return None


def generate_markdown(
    pytest_output: str,
    pytest_summary: dict,
    snapshot: dict | None,
    png_path: str | None,
) -> str:
    """生成 markdown 报告。"""
    report_date = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().isoformat()

    snapshot_section = ""
    if snapshot:
        layers = snapshot.get("layers", [])
        layer_types = [l.get("layerType", "?") for l in layers]
        snapshot_section = f"""## Layout Configs 快照

- 路径: `backend/test-screenshots/e2e_full_pipeline.json`
- 图层数: {len(layers)}
- 图层类型: {', '.join(layer_types)}
- 生成时间: {snapshot.get('timestamp', 'N/A')}
"""

    png_section = ""
    if png_path:
        png_section = f"""## 布局渲染截图

![布局渲染]({Path(png_path).name})
"""

    # 截取 pytest 输出的最后 50 行
    pytest_tail = "\n".join(pytest_output.splitlines()[-50:])

    return f"""# GIS 端对端测试报告

**生成时间**: {timestamp}
**测试日期**: {report_date}

## 测试结果摘要

| 指标 | 数值 |
|------|------|
| 通过测试 | {pytest_summary['passed']} |
| 失败测试 | {pytest_summary['failed']} |
| 总测试数 | {pytest_summary['total']} |
| 测试状态 | {'✅ 全部通过' if pytest_summary['failed'] == 0 and pytest_summary['total'] > 0 else '❌ 有失败'} |

## 测试套件

| 套件 | 文件 | 测试类 |
|------|------|--------|
| Sprint A | `tests/test_gis_e2e_real_data.py::TestFullPipelineE2E` | full_pipeline 完整流程 |
| Sprint B | `tests/test_gis_sse_events.py::TestSSEEventSequence` | SSE 事件序列 |
| Sprint C | `tests/test_gis_api_endpoints.py::TestGISAPIEndpoints` | API 端点 TestClient |

{snapshot_section}

{png_section}

## Pytest 输出（末尾 50 行）

````
{pytest_tail}
````

## 验证项

- [ ] full_pipeline 自动构建 KG（has_kg = true）
- [ ] planning_zone 图层生成且包含 4 类分区
- [ ] CA refinement 面积守恒（≤ 1% 误差）
- [ ] 验证闭环执行（≤ max_validation_rounds）
- [ ] SSE 事件按顺序推送（building_kg → phase0 → phase1 → generating_* → validation_round_N → complete）
- [ ] API 端点 /api/dev/gis/spatial-layout 返回 success=true
- [ ] API 端点 kg_built=true（传入 reports 触发 KG）

## 运行命令

```bash
# 后端测试
cd backend
python -m pytest tests/test_gis_e2e_real_data.py::TestFullPipelineE2E tests/test_gis_sse_events.py tests/test_gis_api_endpoints.py -v

# 前端 Playwright（需手动启动前后端）
cd frontend
npx tsx scripts/gis-e2e-playwright.ts

# 生成报告
python scripts/generate_e2e_report.py
```
"""


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    print("[Report] 启动 GIS E2E 测试报告生成")

    returncode, pytest_output = run_pytest_suite()
    pytest_summary = parse_pytest_summary(pytest_output)

    snapshot = load_layout_snapshot()
    png_path = render_layout_to_png()

    markdown = generate_markdown(pytest_output, pytest_summary, snapshot, png_path)

    report_date = datetime.now().strftime("%Y-%m-%d")
    report_path = REPORT_DIR / f"{report_date}-gis-e2e.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    print(f"[Report] 报告生成: {report_path}")
    print(f"[Report] 通过: {pytest_summary['passed']}, 失败: {pytest_summary['failed']}")

    return returncode


if __name__ == "__main__":
    sys.exit(main())
