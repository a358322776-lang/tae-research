"""B2-1H 正式回测运行器（确定性、可复现）——SPEC v1.1 的 1H 重跑。

解释 I2 改判（用户 2026-11-06）：BOS 结构点取 1H 已确认 Pivot；
15m 版 B2（EXP-20261105-001~004）作废。除 BOS 结构点来源外，
与 run_b2.py 完全同口径（参数、成本档、切分、消融、滚动）。

授权：训练集与验证集 only；最终测试集永不打开（SegmentStore
试开 final_test 必须被拒是运行前守卫之一，见 run_b2_1h 前置检查
脚本——本运行器只经 SegmentStore 取 train/validation 边界）。
前置守卫（数据/代码哈希、隔离、旧测试）已在运行前单独执行
并记录，见 B2-1H 报告 §0；本运行器内再验一次数据哈希。

输出：smc-s1/reports/b2-1h/ 下 signals/orders/trades JSONL（首行
为 header 记录，标注 5m proxy execution）与 run_summary.json。
确定性自验：基线训练段跑两次，交易清单哈希必须一致，否则
报错停止。
"""

from __future__ import annotations

import hashlib
import json
import sys
from calendar import monthrange
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from access import SegmentStore  # noqa: E402
from config import SMCConfig  # noqa: E402
from live_engine import (COST_TIERS, load_market_data, run_segment,  # noqa: E402
                         trades_hash)
from metrics import trade_stats  # noqa: E402
from splits import sha256_file  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path.home() / "workspace/goals/100u-200u/files/tae-b1/data_cache"
OUT_DIR = Path(__file__).resolve().parent / "reports" / "b2-1h"
MANIFEST_PATH = Path(__file__).resolve().parent / "reports" \
    / "split-manifest-v1.json"
SPEC_PATH = Path(__file__).resolve().parent / "reports" / "spec-v1.1.json"

MODES = ("baseline", "no-bos", "no-fvg", "no-trend")
EXPERIMENTS = {"baseline": "EXP-20261105-005", "no-bos": "EXP-20261105-006",
               "no-fvg": "EXP-20261105-007", "no-trend": "EXP-20261105-008"}


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = (year * 12 + (month - 1)) + delta
    return idx // 12, idx % 12 + 1


def _month_start_ms(year: int, month: int) -> int:
    dt = datetime(year, month, 1, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _write_jsonl(path: Path, header: dict, rows: list) -> str:
    h = hashlib.sha256()
    with open(path, "w", encoding="utf-8") as f:
        head = json.dumps({"record_kind": "header", **header},
                          sort_keys=True)
        f.write(head + "\n")
        h.update((head + "\n").encode("utf-8"))
        for row in rows:
            line = json.dumps(asdict(row), sort_keys=True)
            f.write(line + "\n")
            h.update((line + "\n").encode("utf-8"))
    return h.hexdigest()


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    store = SegmentStore.from_file(MANIFEST_PATH, caller="b2-1h-run")
    # 守卫：数据哈希。
    for name, info in manifest["files"].items():
        actual = sha256_file(CACHE_DIR / name)
        if actual != info["sha256"]:
            raise SystemExit(f"STOP: data hash mismatch for {name}")
    print("data hashes: OK (4/4)")
    # 守卫：最终测试集访问控制（试开必须被拒）。
    try:
        store.open_segment("final_test", "B2-1H runner guard probe")
        raise SystemExit("STOP: final_test access control failed")
    except Exception as exc:  # FinalTestBlocked
        if type(exc).__name__ != "FinalTestBlocked":
            raise
    print("final_test isolation: OK (denied, logged)")

    data = load_market_data(CACHE_DIR)
    print(f"market data loaded: 15m={len(data.bars_15m)} "
          f"5m={len(data.bars_5m)} 1h={len(data.bars_1h)} "
          f"funding={len(data.funding_records)}")
    cfg = SMCConfig()
    bounds = {seg: store.open_segment(seg, f"B2-1H run {seg}")
              for seg in ("train", "validation")}

    code_hashes = {}
    for rel in ("smc-s1/live_engine.py", "smc-s1/cost_model.py",
                "smc-s1/config.py", "smc-s1/anchor.py",
                "smc-s1/alignment.py", "smc-s1/access.py",
                "smc-s1/signals.py", "smc-s1/execution.py",
                "smc-s1/risk.py", "smc-s1/funding_gate.py",
                "smc-s1/metrics.py", "smc-s1/splits.py",
                "smc-s1/structure.py", "smc-s1/bos.py",
                "smc-s1/fvg.py", "smc-s1/run_b2_1h.py"):
        code_hashes[rel] = hashlib.sha256(
            (REPO_ROOT / rel).read_bytes()).hexdigest()

    summary: dict = {
        "execution": "5m proxy execution (proxy_fill=true); NOT real fills",
        "hypothesis_id": "HYP-20261105-01",
        "round_id": "ROUND-2026-W45",
        "spec_hash": hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest(),
        "manifest_hash": hashlib.sha256(
            MANIFEST_PATH.read_bytes()).hexdigest(),
        "data_hashes": {n: i["sha256"]
                        for n, i in manifest["files"].items()},
        "code_hashes": code_hashes,
        "cost_tiers": [{k: tier[k] for k in
                        ("name", "maker", "taker",
                         "slip_spread_per_side")} for tier in COST_TIERS],
        "runs": {},
    }
    results = {}
    for mode in MODES:
        for segment in ("train", "validation"):
            start, end = bounds[segment]
            res = run_segment(data, segment, start, end, mode, cfg)
            results[(segment, mode)] = res
            header = {"record_kind": "header",
                      "execution": "5m proxy execution",
                      "proxy_fill": True, "segment": segment, "mode": mode,
                      "experiment_id": EXPERIMENTS[mode],
                      "hypothesis_id": "HYP-20261105-01"}
            sig_hash = _write_jsonl(
                OUT_DIR / f"signals_{segment}_{mode}.jsonl", header,
                res.signals)
            ord_hash = _write_jsonl(
                OUT_DIR / f"orders_{segment}_{mode}.jsonl", header,
                res.orders)
            trd_hash = _write_jsonl(
                OUT_DIR / f"trades_{segment}_{mode}.jsonl", header,
                res.trades)
            completed = [t for t in res.trades if t.outcome != "censored"]
            net_c = [t.central["net_r"] for t in completed
                     if t.central.get("net_r") is not None]
            net_s = [t.conservative["net_r"] for t in completed
                     if t.conservative.get("net_r") is not None]
            summary["runs"][f"{segment}/{mode}"] = {
                "experiment_id": EXPERIMENTS[mode],
                "n_bars": res.n_bars, "n_bos": res.n_bos,
                "n_fvg": res.n_fvg, "n_skips": res.n_skips,
                "n_orders": len(res.orders),
                "orders_filled": sum(1 for o in res.orders
                                     if o.status == "filled"),
                "orders_expired": sum(1 for o in res.orders
                                      if o.status == "expired"),
                "orders_pending_at_end": sum(
                    1 for o in res.orders if o.status == "pending_at_end"),
                "n_trades": len(res.trades),
                "n_completed": len(completed),
                "n_censored": len(res.trades) - len(completed),
                "n_cost_unknown": sum(
                    1 for t in completed
                    if t.central.get("net_r") is None),
                "trades_hash": trades_hash(res.trades),
                "signals_file_sha256": sig_hash,
                "orders_file_sha256": ord_hash,
                "trades_file_sha256": trd_hash,
                "central": trade_stats(net_c),
                "conservative": trade_stats(net_s),
            }
            print(f"{segment}/{mode}: orders={len(res.orders)} "
                  f"completed={len(completed)} "
                  f"censored={len(res.trades) - len(completed)} "
                  f"meanR_c={summary['runs'][f'{segment}/{mode}']['central']['mean_net_r']}")

    # 确定性自验：基线训练段重跑，交易清单哈希必须一致。
    start, end = bounds["train"]
    rerun = run_segment(data, "train", start, end, "baseline", cfg)
    det_ok = trades_hash(rerun.trades) == trades_hash(
        results[("train", "baseline")].trades)
    summary["determinism_check"] = {
        "rerun": "baseline/train twice",
        "trades_hash_match": det_ok,
        "trades_hash": trades_hash(results[("train", "baseline")].trades),
    }
    print("determinism check:", "PASS" if det_ok else "FAIL")
    if not det_ok:
        raise SystemExit("STOP: non-deterministic rerun")

    # 滚动样本外验证（SPEC §9，仅训练+验证段内，参数冻结不选参）：
    # 窗口 6 个月、步长 2 个月；计分段为窗口后 2 个月且不重叠。
    import bisect
    t15 = data.t_15m
    val_end_ms = t15[bounds["validation"][1] - 1] + 900000
    windows = []
    y, m = 2020, 1
    while True:
        w0 = _month_start_ms(y, m)
        y2, m2 = _add_months(y, m, 6)
        w1 = _month_start_ms(y2, m2)
        if w0 >= val_end_ms:
            break
        ys, ms = _add_months(y, m, 4)
        scored_start = _month_start_ms(ys, ms)
        i0 = bisect.bisect_left(t15, w0)
        i1 = min(bisect.bisect_left(t15, w1), bounds["validation"][1])
        if i1 - i0 < 100:
            y, m = _add_months(y, m, 2)
            continue
        res = run_segment(data, "rolling", i0, i1, "baseline", cfg)
        scored = [t for t in res.trades
                  if t.outcome != "censored" and t.fill_ms >= scored_start
                  and t.central.get("net_r") is not None]
        stats = trade_stats([t.central["net_r"] for t in scored])
        windows.append({"window_start_idx": i0, "window_end_idx": i1,
                        "window_start_ms": t15[i0],
                        "window_end_ms": t15[i1 - 1] + 900000,
                        "scored_start_ms": scored_start,
                        "n_scored_trades": len(scored),
                        "central": stats})
        y, m = _add_months(y, m, 2)
    summary["rolling_oos"] = windows
    print(f"rolling OOS windows: {len(windows)}")

    (OUT_DIR / "run_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print("records written to", OUT_DIR)
    return summary


if __name__ == "__main__":
    main()
