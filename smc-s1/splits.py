"""时间切分清单与数据哈希（D4）。

只建立切分清单与哈希，不计算任何策略绩效。切分按 15m bar 的
时间顺序：前 50% 训练、随后 20% 验证、最后 30% 最终测试。
5m/1H bar 按时间戳落入同一窗口。最终测试段绩效在冻结前禁止
访问——本模块只输出边界与哈希，不输出、不缓存任何绩效数字。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

SPLIT_FRACTIONS = (0.50, 0.20, 0.30)


def compute_split(timestamps_ms: list[int]) -> dict:
    """纯函数：给定递增时间戳，返回三段边界（下标半开区间）。"""
    n = len(timestamps_ms)
    if n == 0:
        raise ValueError("empty timestamp list")
    if any(b <= a for a, b in zip(timestamps_ms, timestamps_ms[1:])):
        raise ValueError("timestamps must be strictly increasing")
    i1 = n * 50 // 100
    i2 = n * 70 // 100
    return {
        "n_bars": n,
        "train": {"start_idx": 0, "end_idx": i1,
                  "start_ms": timestamps_ms[0],
                  "end_ms": timestamps_ms[i1]},
        "validation": {"start_idx": i1, "end_idx": i2,
                       "start_ms": timestamps_ms[i1],
                       "end_ms": timestamps_ms[i2]},
        "final_test": {"start_idx": i2, "end_idx": n,
                       "start_ms": timestamps_ms[i2],
                       "end_ms": timestamps_ms[-1]},
        "fractions": list(SPLIT_FRACTIONS),
    }


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_split_manifest(cache_dir: Path, out_path: Path) -> dict:
    """只读：对 stitched 缓存文件哈希 + 按 15m 时间戳切分。

    不读取策略、不计算绩效。输出 JSON 只含哈希、计数与边界。
    """
    import numpy as np

    manifest: dict = {"format_version": "smc-split-manifest-v1",
                      "performance_computed": False,
                      "final_test_access": "blocked-until-freeze",
                      "files": {}}
    for name in ("stitched_15m.npz", "stitched_5m.npz",
                 "stitched_1h.npz", "stitched_funding.csv"):
        p = cache_dir / name
        manifest["files"][name] = {"sha256": sha256_file(p),
                                   "bytes": p.stat().st_size}
    d15 = np.load(cache_dir / "stitched_15m.npz")
    t15 = [int(t) for t in d15["t"]]
    manifest["split_15m"] = compute_split(t15)
    manifest["files"]["stitched_15m.npz"]["bars"] = len(t15)
    for name, key in (("stitched_5m.npz", "bars_5m"),
                      ("stitched_1h.npz", "bars_1h")):
        d = np.load(cache_dir / name)
        manifest["files"][name]["bars"] = int(len(d["t"]))
    import csv
    with open(cache_dir / "stitched_funding.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    manifest["files"]["stitched_funding.csv"]["records"] = len(rows)
    manifest["files"]["stitched_funding.csv"]["first_ms"] = rows[0]["fundingTime"]
    manifest["files"]["stitched_funding.csv"]["last_ms"] = rows[-1]["fundingTime"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2) + "\n",
                        encoding="utf-8")
    return manifest
