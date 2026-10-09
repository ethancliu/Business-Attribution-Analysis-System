# -*- coding: utf-8 -*-
"""打印全部已注册场景的元数据，供文档与验收核对使用。"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许以 `python scripts/tools/dump_scenarios.py` 方式直接运行
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.analysis.scenarios import registry  # noqa: E402


def main() -> int:
    for s in registry.scenario_metadata():
        print(f'{s["key"]} | {s["name"]} | {s["description"]}')
        print(f'    强关键词: {"、".join(s["strong_keywords"])}')
        print(f'    普通关键词: {"、".join(s["keywords"])}')
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
