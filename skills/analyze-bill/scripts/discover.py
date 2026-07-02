"""账单配置发现工具。

从已解析的账单 JSON 中自动识别所有交易状态、收支方向和商户名称，
通过启发式规则预分类，生成可供人工校对的配置文件供 analyze.py 使用。

用法::

    python discover.py /tmp/analyze_bill_data.json -o /tmp/analyze_bill_config.json
"""

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _categorize_status(status: str) -> str:
    """根据启发式规则自动分类交易状态。

    识别逻辑：
    - 包含「成功」「已」「完成」「存入」「转入」「解冻」「退还」等 → success
    - 包含「失败」「关闭」→ failure
    - 其他 → unknown（需人工确认）
    """
    success_keywords = ["成功", "已", "完成", "存入", "转入", "解冻", "退还"]
    if any(kw in status for kw in success_keywords):
        return "success"
    failure_keywords = ["失败", "关闭"]
    if any(kw in status for kw in failure_keywords):
        return "failure"
    return "unknown"


def _categorize_direction(direction: str) -> str:
    """根据启发式规则自动分类收支方向。

    识别逻辑：
    - 包含「收入」→ income
    - 包含「支出」→ expense
    - 其他 → neutral（不计收支）
    """
    if "收入" in direction:
        return "income"
    if "支出" in direction:
        return "expense"
    return "neutral"


def discover(input_path: str, output_path: str) -> dict[str, Any]:
    """从账单数据中发现并生成分析配置。

    扫描已解析账单中的所有唯一 status、income_expense 和 target 值，
    通过启发式规则自动分类，生成可供人工校对的 JSON 配置文件。

    Args:
        input_path: parse.py 输出的账单 JSON 文件路径。
        output_path: 生成的配置文件输出路径。

    Returns:
        生成的配置字典。
    """
    with open(input_path, "r", encoding="utf-8") as f:
        bills = json.load(f)

    # ---- 1. 交易状态分类 ----
    status_counter = Counter(b["status"] for b in bills)
    status_mapping: dict[str, str] = {}
    for status in sorted(status_counter):
        status_mapping[status] = _categorize_status(status)

    # ---- 2. 收支方向分类 ----
    direction_counter = Counter(b["income_expense"] for b in bills)
    direction_mapping: dict[str, str] = {}
    for direction in sorted(direction_counter):
        direction_mapping[direction] = _categorize_direction(direction)

    # ---- 3. 商户列表（供人工添加别名参考）----
    target_counter = Counter(b["target"] for b in bills)
    all_targets = [
        {"name": name, "count": count}
        for name, count in target_counter.most_common()
    ]

    # ---- 组装配置 ----
    unknown_statuses = [s for s, c in status_mapping.items() if c == "unknown"]
    unknown_directions = [d for d, c in direction_mapping.items() if c == "unknown"]

    config: dict[str, Any] = {
        "_metadata": {
            "total_records": len(bills),
            "unique_statuses": len(status_counter),
            "unique_directions": len(direction_counter),
            "unique_targets": len(target_counter),
            "auto_generated": True,
            "warnings": {
                "unknown_statuses": unknown_statuses,
                "unknown_directions": unknown_directions,
            },
            "note": (
                "自动生成的配置文件。请检查 status_mapping 和 direction_mapping "
                "中标记为 unknown 的项，将其改为正确的分类。"
                "可在 target_aliases 中添加商户别名以实现同名归并。"
            ),
        },
        "status_mapping": status_mapping,
        "direction_mapping": direction_mapping,
        "target_aliases": {},
        "_reference": {
            "all_targets": all_targets,
            "status_distribution": dict(status_counter.most_common()),
            "direction_distribution": dict(direction_counter.most_common()),
        },
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    return config


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python discover.py <账单JSON文件> [-o 输出路径]", file=sys.stderr)
        print("示例: python discover.py /tmp/analyze_bill_data.json -o /tmp/analyze_bill_config.json", file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = "/tmp/analyze_bill_config.json"

    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "-o" and i + 1 < len(args):
            output_path = args[i + 1]
            i += 2
        else:
            i += 1

    if not Path(input_path).exists():
        print(f"错误: 账单数据文件不存在 - {input_path}", file=sys.stderr)
        sys.exit(1)

    config = discover(input_path, output_path)

    # 打印摘要
    print(f"配置文件已生成: {output_path}")
    print(f"  交易状态: {config['_metadata']['unique_statuses']} 种 "
          f"→ 成功 {sum(1 for c in config['status_mapping'].values() if c == 'success')} / "
          f"失败 {sum(1 for c in config['status_mapping'].values() if c == 'failure')} / "
          f"未知 {sum(1 for c in config['status_mapping'].values() if c == 'unknown')}")
    if config["_metadata"]["warnings"]["unknown_statuses"]:
        print(f"  ⚠ 需人工确认的状态: {config['_metadata']['warnings']['unknown_statuses']}")
    print(f"  收支方向: {config['_metadata']['unique_directions']} 种")
    if config["_metadata"]["warnings"]["unknown_directions"]:
        print(f"  ⚠ 需人工确认的方向: {config['_metadata']['warnings']['unknown_directions']}")
    print(f"  商户数量: {config['_metadata']['unique_targets']} 个")
    print(f"  商户别名: 空（可在配置文件中手动添加 target_aliases）")
