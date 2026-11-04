#!/usr/bin/env python3
"""取一个公开 klines 快照并写只读冻结（最小必要，单次请求）。

用法：
  python3 research-lab/fetch_snapshot.py --symbol ETHUSDT --interval 1h --limit 100
  python3 research-lab/fetch_snapshot.py --symbol BTCUSDT --interval 1h --limit 100 \
      --state-dir research-lab/state

质量检查失败时不写快照、退出码 2。快照只写本地-only state 目录，永不进仓。
不带任何密钥与签名参数；--base-url 只能是 allowlist 主机（默认镜像）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_engine import (MIRROR_KLINES, drop_unclosed_bars, fetch_klines,
                         next_snapshot_id, write_snapshot)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch one public klines snapshot.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--base-url", default=MIRROR_KLINES)
    parser.add_argument("--state-dir", default="research-lab/state")
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args(argv)

    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    bars = fetch_klines(args.base_url, args.symbol, args.interval,
                        args.limit, timeout=args.timeout)
    # 交易所返回的最后一根常为进行中、未收盘的 bar：取数层丢弃，
    # 质量检查规则本身不放宽；丢弃数记入 manifest，接受记录可审计。
    now_ms = int(time.time() * 1000)
    bars, dropped = drop_unclosed_bars(bars, now_ms)
    if not bars:
        print(json.dumps({"error": "all bars unclosed, snapshot refused",
                          "requested_limit": args.limit,
                          "dropped_unclosed_bars": dropped}),
              file=sys.stderr)
        return 2
    date_str = time.strftime("%Y%m%d", time.gmtime())
    snapshot_id = next_snapshot_id(args.state_dir, date_str)
    manifest = write_snapshot(
        args.state_dir, snapshot_id, args.symbol, args.interval, bars,
        f"{args.base_url}?symbol={args.symbol}&interval={args.interval}&limit={args.limit}",
        fetched_at,
        extra_manifest={"requested_limit": args.limit,
                        "dropped_unclosed_bars": dropped})
    print(json.dumps({
        "snapshot_id": manifest["snapshot_id"],
        "symbol": manifest["symbol"],
        "interval": manifest["interval"],
        "n_bars": manifest["n_bars"],
        "requested_limit": manifest["requested_limit"],
        "dropped_unclosed_bars": manifest["dropped_unclosed_bars"],
        "data_sha256": manifest["data_sha256"],
        "quality_passed": manifest["quality_passed"],
        "gaps": manifest["gaps"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
