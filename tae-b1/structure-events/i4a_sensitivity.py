"""TAE 实验设计审查 · 任务二：I4-A 失效阈值敏感度（零盈亏）。

只读复用普查口径，不改原脚本、不改生产代码、不算盈亏。
普查实现（events_census.py 的 i4a_first_invalid，逐字复刻并加追踪）：
- 1H tie 摆动点（swings_tie：等于 max/min 也算），k=2 确认。
- 种子：b0 时最新已确认摆动低/高（idx ≤ last_at_b0 − 2，
  last_at_b0 = 收盘 ≤ b0_close 的最后一根 1H）。
- 现行读法 new：摆动 bar 收盘 > b0_close 且 idx ≤ k−2 的摆动点
  纳入 Θ；Θ（多头）= max（种子，全部 new 摆动低），空头取 min。
- 评价在 1H 收盘上做：多头 close ≤ Θ 即失效，吸收态；盘中不算。
- 另一读法 new_alt：摆动 bar 的确认根（idx+2）收盘 > b0_close
  即纳入（含 b0 前最后两根内形成、b0 后才确认者）；种子不变。
  该读法下 Θ 只可能更高（多头）/更低（空头），失效只可能更多。
本脚本输出：失效深度分布、鞭打率、Θ 棘轮统计、另一读法对照，
并以普查 i4a 字段为复制门（序列内失效数与失效时刻须逐项一致）。
"""
import csv
import sys
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/files/tae-b1")
sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/hidden_files")
from b1_lib import swings_tie  # noqa: E402 只读复用

B1 = "/home/hatch/workspace/goals/100u-200u/files/tae-b1"
SE = f"{B1}/structure-events"

d15 = np.load(f"{B1}/data_cache/stitched_15m.npz")
d1h = np.load(f"{B1}/data_cache/stitched_1h.npz")
t15, o15 = d15["t"], d15["ohlc"]
t1h, o1h = d1h["t"], d1h["ohlc"]
c15 = o15[:, 3]
c1h = o1h[:, 3]
t15_close = t15 + 900_000
t1h_close = t1h + 3_600_000
n15, n1h = len(t15), len(t1h)

tr1 = np.full(n1h, np.nan)
for i in range(1, n1h):
    tr1[i] = max(o1h[i][1] - o1h[i][2], abs(o1h[i][1] - o1h[i - 1][3]),
                 abs(o1h[i][2] - o1h[i - 1][3]))
atr1 = np.full(n1h, np.nan)
for i in range(13, n1h):
    atr1[i] = float(np.nanmean(tr1[i - 13:i + 1]))

hi_all, lo_all = swings_tie(o1h)
hi_idx = np.array([i for i, _ in hi_all])
hi_val = np.array([v for _, v in hi_all])
lo_idx = np.array([i for i, _ in lo_all])
lo_val = np.array([v for _, v in lo_all])


def scan_theta(b0_close, end_close, direction, reading):
    """连续扫描 (b0_close, end_close] 内的 1H 收盘，返回：
    (theta_trace, first_invalid)。
    theta_trace: list[(k, close_ms, theta_or_None, close)]，theta 为
    该根评价时（更新后）的 Θ；first_invalid: (k, close_ms, close,
    theta, depth_atr) 或 None。"""
    k0 = int(np.searchsorted(t1h_close, b0_close, side="right"))
    k1 = int(np.searchsorted(t1h_close, end_close, side="right")) - 1
    if k1 < k0:
        return [], None
    last_at_b0 = int(np.searchsorted(t1h_close, b0_close, side="right")) - 1
    if direction == "long":
        idx_arr, val_arr = lo_idx, lo_val
        agg = max
    else:
        idx_arr, val_arr = hi_idx, hi_val
        agg = min
    conf = [v for idx, v in zip(idx_arr, val_arr) if idx <= last_at_b0 - 2]
    theta = agg(conf) if conf else None
    trace = []
    first_inv = None
    for k in range(k0, k1 + 1):
        if reading == "current":
            new = [v for idx, v in zip(idx_arr, val_arr)
                   if idx <= k - 2 and int(t1h[idx]) + 3_600_000 > b0_close]
        else:  # alt：确认根收盘 > b0_close
            new = [v for idx, v in zip(idx_arr, val_arr)
                   if idx <= k - 2 and int(t1h_close[idx + 2]) > b0_close]
        if new:
            cand = agg(new)
            theta = cand if theta is None else agg([theta, cand])
        cl = float(c1h[k])
        trace.append((k, int(t1h_close[k]), theta, cl))
        if first_inv is None and theta is not None:
            hit = (direction == "long" and cl <= theta) or \
                  (direction == "short" and cl >= theta)
            if hit:
                a = float(atr1[k])
                depth = ((theta - cl) / a if direction == "long"
                         else (cl - theta) / a) if a and not np.isnan(a) else None
                first_inv = (k, int(t1h_close[k]), cl, theta, depth)
    return trace, first_inv


def whipsaw_15m(T_inv, theta, direction):
    """失效 1H 收盘后 12/48 根 15m 内收盘是否回到 Θ 之上（Θ 冻结）。
    返回 (w12, w48, trunc12, trunc48)，缺数据时对应项为 None。"""
    m = int(np.searchsorted(t15_close, T_inv, side="left"))
    if m >= n15 or int(t15_close[m]) != T_inv:
        return None, None, True, True
    out = []
    for L in (12, 48):
        if m + L >= n15:
            out.append(None)
            continue
        seg = c15[m + 1:m + L + 1]
        if direction == "long":
            out.append(bool(np.any(seg > theta)))
        else:
            out.append(bool(np.any(seg < theta)))
    return out[0], out[1], m + 12 >= n15, m + 48 >= n15


def main():
    rows = []
    with open(f"{SE}/events_census.csv") as fh:
        for r in csv.DictReader(fh):
            rows.append(r)
    rec = [r for r in rows if r["outcome"] == "reclaimed"]
    out = []
    mism = Counter()
    for r in rec:
        j = int(r["b0_idx"])
        term = j + int(r["reclaim_lag_bars"])
        d = r["dir"]
        b0_close = int(t15[term - int(r["reclaim_lag_bars"])] + 900_000) \
            if False else int(t15[j]) + 900_000
        term_close = int(t15[term]) + 900_000
        end48_close = int(t15[term + 48]) + 900_000
        trace, inv = scan_theta(b0_close, end48_close, d, "current")
        _, inv_alt = scan_theta(b0_close, end48_close, d, "alt")
        # 复制门：序列内失效数与失效时刻与普查一致
        inv_during = inv is not None and inv[1] <= term_close
        if int(inv_during) != int(r["i4a_invalidated_during"]):
            mism["during_flag"] += 1
        if inv_during:
            from datetime import datetime, timezone
            ts = datetime.fromtimestamp(inv[1] / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M")
            if ts != r["i4a_invalidation_time_utc"]:
                mism["during_time"] += 1
        inv_post = inv is not None and inv[1] > term_close
        if int(inv_post) != int(r["post48_i4a_invalidated"]):
            mism["post48_flag"] += 1
        # 棘轮：序列内窗口 (b0_close, term_close] 的 Θ 变化
        seq_trace = [(k, tc, th, cl) for (k, tc, th, cl) in trace if tc <= term_close]
        increases = 0
        cum_atr = 0.0
        prev = None
        # 种子 Θ（b0 时）
        last_at_b0 = int(np.searchsorted(t1h_close, b0_close, side="right")) - 1
        if d == "long":
            seed_c = [v for idx, v in zip(lo_idx, lo_val) if idx <= last_at_b0 - 2]
            seed = max(seed_c) if seed_c else None
        else:
            seed_c = [v for idx, v in zip(hi_idx, hi_val) if idx <= last_at_b0 - 2]
            seed = min(seed_c) if seed_c else None
        prev = seed
        for (k, tc, th, cl) in seq_trace:
            if th is None or prev is None:
                prev = th
                continue
            if (d == "long" and th > prev) or (d == "short" and th < prev):
                increases += 1
                a = float(atr1[k])
                if a and not np.isnan(a):
                    cum_atr += abs(th - prev) / a
            prev = th
        # 收复时刻 argmax 摆动的新旧：Θ 由最新已确认摆动决定否
        last_eval = seq_trace[-1][0] if seq_trace else last_at_b0
        if d == "long":
            conf_all = [(idx, v) for idx, v in zip(lo_idx, lo_val) if idx <= last_eval - 2]
            theta_rec = max([v for _, v in conf_all]) if conf_all else None
        else:
            conf_all = [(idx, v) for idx, v in zip(hi_idx, hi_val) if idx <= last_eval - 2]
            theta_rec = min([v for _, v in conf_all]) if conf_all else None
        if conf_all and theta_rec is not None:
            latest_idx = max(idx for idx, _ in conf_all)
            arg_idx = max(idx for idx, v in conf_all if v == theta_rec) \
                if d == "long" else max(idx for idx, v in conf_all if v == theta_rec)
            arg_is_latest = int(arg_idx == latest_idx)
        else:
            arg_is_latest = ""
        # 鞭打：以首次失效（序列内或收复后）为准
        w12 = w48 = ""
        if inv is not None:
            w12, w48, _, _ = whipsaw_15m(inv[1], inv[3], d)
        row = {
            "seq_id": r["seq_id"], "dir": d,
            "inv_during": int(inv_during),
            "inv_post48": int(inv_post),
            "inv_time_utc": inv[1] if inv else "",
            "inv_theta": inv[3] if inv else "",
            "inv_depth_atr": inv[4] if inv else "",
            "inv_alt_during": int(inv_alt is not None and inv_alt[1] <= term_close),
            "inv_alt_post48": int(inv_alt is not None and inv_alt[1] > term_close),
            "inv_alt_time_utc": inv_alt[1] if inv_alt else "",
            "ratchet_increases": increases,
            "ratchet_cum_atr": round(cum_atr, 4),
            "theta_seed": seed if seed is not None else "",
            "theta_at_reclaim": theta_rec if theta_rec is not None else "",
            "argmax_is_latest": arg_is_latest,
            "whipsaw12": "" if w12 == "" else int(w12),
            "whipsaw48": "" if w48 == "" else int(w48),
        }
        out.append(row)
    fields = list(out[0].keys())
    with open(f"{SE}/i4a_sensitivity.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(out)
    print(f"rows={len(out)} mismatches={dict(mism)}")

    def summ(name, sub):
        n = len(sub)
        if n == 0:
            print(f"{name}: n=0")
            return
        depths = np.array([float(x["inv_depth_atr"]) for x in sub
                           if x["inv_depth_atr"] != ""], dtype=float)
        print(f"{name}: n={n} depth median={np.median(depths):.3f} "
              f"q1={np.percentile(depths, 25):.3f} q3={np.percentile(depths, 75):.3f} "
              f"mean={depths.mean():.3f} max={depths.max():.3f}")
        for thr in (0.1, 0.25, 0.5):
            print(f"   depth<{thr}: {(depths < thr).mean():.1%} "
                  f"({int((depths < thr).sum())}/{len(depths)})")
        for col in ("whipsaw12", "whipsaw48"):
            vals = [int(x[col]) for x in sub if x[col] != ""]
            print(f"   {col}: {sum(vals)}/{len(vals)} = {sum(vals) / len(vals):.1%}")

    during = [x for x in out if x["inv_during"] == 1]
    post = [x for x in out if x["inv_during"] == 0 and x["inv_post48"] == 1]
    print(f"during={len(during)} post48={len(post)} "
          f"not_during={sum(1 for x in out if x['inv_during'] == 0)}")
    summ("现行读法·序列内首次失效", during)
    summ("现行读法·收复后首次失效", post)
    summ("现行读法·全部首次失效", during + post)
    # 另一读法对照
    alt_during = sum(1 for x in out if x["inv_alt_during"] == 1)
    alt_post = sum(1 for x in out if x["inv_alt_during"] == 0 and x["inv_alt_post48"] == 1)
    cur_during = len(during)
    cur_post = len(post)
    print(f"另一读法对照：序列内失效 {cur_during} -> {alt_during} "
          f"(+{alt_during - cur_during})；收复后新失效 {cur_post} -> {alt_post} "
          f"(+{alt_post - cur_post})；未失效总数 "
          f"{sum(1 for x in out if x['inv_during'] == 0 and x['inv_post48'] == 0)} -> "
          f"{sum(1 for x in out if x['inv_alt_during'] == 0 and x['inv_alt_post48'] == 0)}")
    # 棘轮
    inc = np.array([x["ratchet_increases"] for x in out])
    cum = np.array([x["ratchet_cum_atr"] for x in out])
    arg = [x["argmax_is_latest"] for x in out if x["argmax_is_latest"] != ""]
    print(f"棘轮（序列内窗口）：上调次数 mean={inc.mean():.2f} median={np.median(inc):.0f} "
          f"max={inc.max()}；累计上调 mean={cum.mean():.3f} ATR median={np.median(cum):.3f} "
          f"max={cum.max():.3f}")
    print(f"收复时刻 Θ 由最新已确认摆动决定：{sum(arg)}/{len(arg)} = {sum(arg) / len(arg):.1%}")


def latest_seed_scan():
    """诊断：种子改取「最新已确认摆动」（最大 idx，而非最大 value）
    时的失效计数对照；其余与现行读法相同。另输出种子偏离、
    argmax 摆动年龄、首根失效占比等机制诊断。"""
    rows = []
    with open(f"{SE}/events_census.csv") as fh:
        for r in csv.DictReader(fh):
            rows.append(r)
    rec = [r for r in rows if r["outcome"] == "reclaimed"]
    n_during = n_post = 0
    seed_gaps = []
    arg_ages = []
    first_bar_inv = 0
    first_bar_inv_cur = 0
    n_during_cur = 0
    never = []
    lat_depths = []
    lat_w12 = []
    lat_w48 = []
    lat_inc = []
    lat_cum = []
    for r in rec:
        j = int(r["b0_idx"])
        term = j + int(r["reclaim_lag_bars"])
        d = r["dir"]
        b0_close = int(t15[j]) + 900_000
        term_close = int(t15[term]) + 900_000
        end48_close = int(t15[term + 48]) + 900_000
        last_at_b0 = int(np.searchsorted(t1h_close, b0_close, side="right")) - 1
        if d == "long":
            idx_arr, val_arr = lo_idx, lo_val
        else:
            idx_arr, val_arr = hi_idx, hi_val
        # 现行种子偏离：种子 Θ − b0 收盘（ATR 单位）
        conf = [(idx, v) for idx, v in zip(idx_arr, val_arr) if idx <= last_at_b0 - 2]
        seed_cur = (max(v for _, v in conf) if d == "long"
                    else min(v for _, v in conf)) if conf else None
        a_b0 = float(atr1[last_at_b0])
        if seed_cur is not None and a_b0 and not np.isnan(a_b0):
            gap = ((seed_cur - float(c1h[last_at_b0])) / a_b0 if d == "long"
                   else (float(c1h[last_at_b0]) - seed_cur) / a_b0)
            seed_gaps.append(gap)
        if conf:
            best = (max(v for _, v in conf) if d == "long"
                    else min(v for _, v in conf))
            arg_idx = max(idx for idx, v in conf if v == best)
            arg_ages.append(last_at_b0 - arg_idx)
        # 现行读法首根失效（对照）
        _, inv_cur = scan_theta(b0_close, end48_close, d, "current")
        if inv_cur is not None and inv_cur[1] <= term_close:
            n_during_cur += 1
            k0c = int(np.searchsorted(t1h_close, b0_close, side="right"))
            if inv_cur[0] == k0c:
                first_bar_inv_cur += 1
        # 最新种子扫描
        k0 = int(np.searchsorted(t1h_close, b0_close, side="right"))
        k1 = int(np.searchsorted(t1h_close, end48_close, side="right")) - 1
        latest = max(conf, key=lambda p: p[0])[1] if conf else None
        theta = latest
        inv = None
        prev_th = latest
        n_inc = 0
        cum = 0.0
        for k in range(k0, k1 + 1):
            new = [v for idx, v in zip(idx_arr, val_arr)
                   if idx <= k - 2 and int(t1h[idx]) + 3_600_000 > b0_close]
            if new:
                cand = (max(new) if d == "long" else min(new))
                theta = cand if theta is None else (max(theta, cand) if d == "long"
                                                    else min(theta, cand))
            cl = float(c1h[k])
            if int(t1h_close[k]) <= term_close and theta is not None and prev_th is not None:
                if (d == "long" and theta > prev_th) or (d == "short" and theta < prev_th):
                    n_inc += 1
                    a = float(atr1[k])
                    if a and not np.isnan(a):
                        cum += abs(theta - prev_th) / a
            prev_th = theta
            if inv is None and theta is not None and \
                    ((d == "long" and cl <= theta) or (d == "short" and cl >= theta)):
                inv = (k, int(t1h_close[k]), cl, theta)
                a = float(atr1[k])
                if a and not np.isnan(a):
                    lat_depths.append(((theta - cl) / a if d == "long"
                                        else (cl - theta) / a))
                w12, w48, _, _ = whipsaw_15m(int(t1h_close[k]), theta, d)
                if w12 is not None:
                    lat_w12.append(int(w12))
                if w48 is not None:
                    lat_w48.append(int(w48))
        lat_inc.append(n_inc)
        lat_cum.append(round(cum, 4))
        if inv is not None and inv[1] <= term_close:
            n_during += 1
            if inv[0] == k0:
                first_bar_inv += 1
        elif inv is not None:
            n_post += 1
        else:
            never.append(r["seq_id"])
    sg = np.array(seed_gaps)
    ag = np.array(arg_ages)
    print("=== 机制诊断（现行实现）===")
    print(f"种子 Θ − b0 收盘（1H ATR）：median={np.median(sg):.1f} "
          f"q1={np.percentile(sg, 25):.1f} q3={np.percentile(sg, 75):.1f} "
          f"share>0（种子已在现价之上）={(sg > 0).mean():.1%} share>10 ATR={(sg > 10).mean():.1%}")
    print(f"argmax 摆动年龄（1H 根）：median={np.median(ag):.0f} "
          f"q3={np.percentile(ag, 75):.0f} max={ag.max()}；"
          f"年龄>720 根（约 30 天）={(ag > 720).mean():.1%}，>4320 根（约 180 天）={(ag > 4320).mean():.1%}")
    print(f"最新种子读法对照：序列内失效 {n_during}（现行 173），"
          f"收复后新失效 {n_post}（现行 157），永不失效 {len(never)}（现行 2）")
    print(f"现行读法下序列内失效中首根 1H 即失效者：{first_bar_inv_cur}/{n_during_cur}")
    print(f"最新种子读法下序列内失效中首根 1H 即失效者：{first_bar_inv}/{n_during}")
    ld = np.array(lat_depths)
    print(f"最新种子读法·首次失效深度：n={len(ld)} median={np.median(ld):.3f} "
          f"q1={np.percentile(ld, 25):.3f} q3={np.percentile(ld, 75):.3f} "
          f"mean={ld.mean():.3f}；<0.1 ATR={(ld < 0.1).mean():.1%}，"
          f"<0.25 ATR={(ld < 0.25).mean():.1%}，<0.5 ATR={(ld < 0.5).mean():.1%}")
    print(f"最新种子读法·鞭打：12 根 {sum(lat_w12)}/{len(lat_w12)} = "
          f"{sum(lat_w12) / len(lat_w12):.1%}；48 根 {sum(lat_w48)}/{len(lat_w48)} = "
          f"{sum(lat_w48) / len(lat_w48):.1%}")
    li = np.array(lat_inc)
    lc = np.array(lat_cum)
    print(f"最新种子读法·棘轮（序列内窗口）：上调次数 mean={li.mean():.2f} "
          f"median={np.median(li):.0f} max={li.max()}；累计上调 mean={lc.mean():.3f} ATR "
          f"median={np.median(lc):.3f} max={lc.max():.3f}")


if __name__ == "__main__":
    main()
    latest_seed_scan()
