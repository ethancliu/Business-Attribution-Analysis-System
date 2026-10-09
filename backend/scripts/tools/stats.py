# -*- coding: utf-8 -*-
"""通用统计脚本（shell_exec 工具白名单脚本）。

用法:
    python -I stats.py sum 12 34 56
    python -I stats.py describe '[1,2,3,4,5]'
    python -I stats.py change 11165000 8278000

输出为 JSON，便于分析引擎直接解析为结构化证据。
"""

from __future__ import annotations

import json
import statistics
import sys


def cmd_sum(values: list[float]) -> dict:
    return {"op": "sum", "count": len(values), "result": round(sum(values), 4)}


def cmd_describe(values: list[float]) -> dict:
    if not values:
        return {"op": "describe", "count": 0}
    return {
        "op": "describe",
        "count": len(values),
        "sum": round(sum(values), 4),
        "mean": round(statistics.fmean(values), 4),
        "median": round(statistics.median(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "stdev": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0,
    }


def cmd_change(base: float, current: float) -> dict:
    if base == 0:
        return {"op": "change", "change_pct": 0.0, "note": "基准值为 0，无法计算变化率"}
    return {
        "op": "change",
        "base": base,
        "current": current,
        "delta": round(current - base, 4),
        "change_pct": round((current - base) / base * 100, 4),
        "ratio": round(current / base, 4),
    }


def main() -> int:
    argv = sys.argv[1:]
    if not argv:
        print(json.dumps({"error": "缺少子命令：sum / describe / change"}, ensure_ascii=False))
        return 1

    op = argv[0]
    try:
        if op == "sum":
            result = cmd_sum([float(x) for x in argv[1:]])
        elif op == "describe":
            raw = " ".join(argv[1:]).strip()
            if raw.startswith("["):
                values = [float(x) for x in json.loads(raw)]
            else:
                values = [float(x) for x in argv[1:]]
            result = cmd_describe(values)
        elif op == "change":
            if len(argv) < 3:
                print(json.dumps({"error": "change 需要两个参数：基准值 当前值"}, ensure_ascii=False))
                return 1
            result = cmd_change(float(argv[1]), float(argv[2]))
        else:
            print(json.dumps({"error": f"未知子命令：{op}"}, ensure_ascii=False))
            return 1
    except (ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": f"参数解析失败：{exc}"}, ensure_ascii=False))
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
