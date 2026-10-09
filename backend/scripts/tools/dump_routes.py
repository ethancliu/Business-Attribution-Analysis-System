# -*- coding: utf-8 -*-
"""从运行中的服务导出接口清单（OpenAPI），供文档核对使用。

用法: .venv\\Scripts\\python.exe -X utf8 scripts\\tools\\dump_routes.py [服务地址]
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def main() -> int:
    with urllib.request.urlopen(f"{BASE}/openapi.json", timeout=10) as resp:
        spec = json.load(resp)
    rows = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            rows.append((path, method.upper(), op.get("summary", "")))
    rows.sort()
    for path, method, summary in rows:
        print(f"{method:6} {path:50} {summary}")
    print(f"\n共 {len(rows)} 个接口")
    return 0


if __name__ == "__main__":
    sys.exit(main())
