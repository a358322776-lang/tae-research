#!/usr/bin/env python3
"""最小只读连通性探针：固定 4 个请求，不重试，不保存响应体。

探针（均为公开、无 key、无签名）：
  1. 镜像 ping：https://www.binance.com/fapi/v1/ping
  2. 镜像 klines（limit=5）：ETHUSDT 1h
  3. 镜像 fundingRate（limit=5）：ETHUSDT
  4. 直连 fapi ping：https://fapi.binance.com/fapi/v1/ping（预期 451，记录时点状态）
输出 JSON 到 stdout；不写任何数据文件，不改生产配置。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_engine import FAPI_PING, MIRROR_FUNDING, MIRROR_KLINES, MIRROR_PING, probe

PROBES = [
    MIRROR_PING,
    f"{MIRROR_KLINES}?symbol=ETHUSDT&interval=1h&limit=5",
    f"{MIRROR_FUNDING}?symbol=ETHUSDT&limit=5",
    FAPI_PING,
]


def main() -> int:
    results = [probe(url) for url in PROBES]
    print(json.dumps({"probes": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
