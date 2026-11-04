"""取资金费率快照（最小规模管道验证）。

用法：
  python3 fetch_funding_snapshot.py --symbol ETHUSDT --limit 20
  python3 fetch_funding_snapshot.py --symbol BTCUSDT --limit 20

只读公开接口，无 key、无签名。快照写本地-only state/，永不进仓。
不恢复 CA-1/P4，不做策略回测。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from data_engine import MIRROR_FUNDING
from funding_snapshot import (fetch_funding, next_funding_id,
                              verify_funding_snapshot,
                              write_funding_snapshot)

HERE = Path(__file__).resolve().parent
STATE_DIR = HERE / "state"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--state-dir", default=str(STATE_DIR))
    args = parser.parse_args()

    records = fetch_funding(args.symbol, limit=args.limit)
    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    date_str = time.strftime("%Y%m%d", time.gmtime())
    snapshot_id = next_funding_id(args.state_dir, date_str)
    manifest = write_funding_snapshot(
        args.state_dir, snapshot_id, args.symbol, records,
        MIRROR_FUNDING, fetched_at)
    snap_dir = Path(args.state_dir) / "funding-snapshots" / snapshot_id
    check = verify_funding_snapshot(snap_dir)
    print(json.dumps({
        "snapshot_id": snapshot_id,
        "symbol": args.symbol,
        "n_records": manifest["n_records"],
        "first_funding_time": manifest["first_funding_time"],
        "last_funding_time": manifest["last_funding_time"],
        "data_sha256": manifest["data_sha256"],
        "missing_steps": manifest["missing_steps"],
        "verify_ok": check["ok"],
        "dir": str(snap_dir),
    }, sort_keys=True))
    return 0 if check["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
