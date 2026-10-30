# C5 探索性回测运行日志（单次运行，2026-10-30）

批准：用户 2026-10-30T09:30:54Z（主聊）批准执行申请 v2，仅授权一次历史探索性回测（v0.8-DRAFT）。不冻结、不实盘、不追加资金。
运行：2026-10-30T09:32:16Z（UTC），耗时 2.7 秒，退出码 0。

## 1. 执行前数据哈希校验（与质量报告 §2 一致）

```
4bc2a45f037c01cebc0d9e2983a2b107c1ebefa853ae07e543bd06d68e8ae3bf  data/klines_BTCUSDT.json
9b2893128ae22c21ee8fda3159997ebd6f1e406e03e270fcef6995b5bc3d3300  data/klines_ETHUSDT.json
3c5e5f7a253c9a19ed03f31ac2c6c83bab3e9b6de4f567017c23b985cde7eafe  data/funding_BTCUSDT.json
9ccfe9340a7ab6b6abc9e7f8030ba9342d4236c524ef2dc52d86950b2ce710e4  data/funding_ETHUSDT.json
ec82ef1c04ddc7a7b44453b721ec9b7907c6dcbea4c521d67f32e767b99e1c7e  c5-event-calendar-draft.csv
```

## 2. 执行前门禁（重新运行，确定性）

ALL REVISION UNIT TESTS PASSED
ALL C5 END-TO-END TESTS PASSED
IMPLEMENTATION VERIFICATION PASSED: engine reproduces e2e price mechanics (7 scenarios) and funding bounds (close + stop days 0/1/3 + mixed-sign prefix extremes).
Verify-only mode: no backtest run.

## 3. 单次运行标准输出（实现内对照门禁＋运行记录）

```
ok: E2E normal long enters D+2 open, exits D+5 close
ok: E2E normal long net = gross - fee - funding(4 days)
ok: E2E intraday stop triggers on D+4 and later prices are ignored
ok: E2E gap-through executes at open with one slip+spread charge
ok: E2E entry-day D+2 intraday move can trigger the stop
ok: E2E stop beats same-day close exit on D+5
ok: E2E dedup skips window-overlapping event, admits later event
ok: E2E missing close excludes the whole event
ok: E2E missing entry open excludes the whole event
ok: E2E complete event returns mean net and contribution
ok: E2E noise filter uses the new 0.26% central round-trip cost
ok: E2E early stop accrues only 1 funding day
ok: E2E short receives funding (net higher by funding vs gross-fee)
ok: E2E slip+spread counted once: diff ~ -0.16%, not -0.32%
ok: E2E short stop triggers on high with upward cost adjustment
ok: E2E D+1 prices cannot change the outcome
ok: E2E direction uses event-day closes only
ok: E2E stop base is the filled entry price, not the raw open
ok: E2E exit happens on D+5 (day index 3); no extension
ok: E2E stopped leg + held leg average into one event observation
ok: E2E missing Low excludes the event, not a no-trigger close
ok: E2E missing High excludes the event, not a no-trigger close
ok: E2E invalid bar (High < Low) excludes the event
ok: E2E D+2 open mismatch with the entry reference excludes the event
ok: E2E close leg matches 11 certain settlements (boundary excluded)
ok: E2E close leg excludes the exit-boundary settlement even if large
ok: E2E stop on D+2 gives funding interval [0, 2] settlements
ok: E2E stop on D+3 gives funding interval [3, 5] settlements
ok: E2E stop on D+5 gives funding interval [9, 11] settlements
ok: E2E short leg funding interval is the negated rate interval
ok: E2E irregular records govern: a 2-settlement day counts 10, not 11
ok: E2E gap over 24h inside the window excludes the leg
ok: E2E each leg uses its own asset funding history
ok: REV7 mixed-sign stop day: bounds are prefix extremes, not endpoints
ok: REV7 interval contains every possible prefix total
ok: REV7 all-negative stop day: bounds are [-0.0002, 0.0]
ok: REV7 short leg: net bounds from signed funding extremes
ok: REV7 close leg with negative rates is the exact (negative) sum
ok: REV7 gap over 24h excludes the leg even with negative rates
ALL C5 END-TO-END TESTS PASSED
IMPLEMENTATION VERIFICATION PASSED: engine reproduces e2e price mechanics (7 scenarios) and funding bounds (close + stop days 0/1/3 + mixed-sign prefix extremes).
RUN COMPLETE in 2.7s: 216 evaluated, 1 pending-excluded, central trades=194.
```

## 4. 运行后复核

- 结果文件 data/c5-exploratory-results.json 已生成（本地封存，不进仓）；216 评估、1 截止日未完成排除（2026-10-28 FOMC）；中央档 194 交易。
- EXECUTION_APPROVED 已恢复为 False；裸运行复核被拒跑门拒绝（见下）。
REFUSED: no fresh execution approval (application v2 still awaiting approval); the script refuses any returns run until approval is recorded by setting EXECUTION_APPROVED = True.
- 程序缺陷记录：运行内 FRED 解析遇空值行崩溃、走 4.18% 回退（见报告 §0／§6）；窗口均值 2.97% 由两次独立拉取计算（n=1707），解析已事后修复，未重跑。
- 执行前门禁修正记录：零成本诊断断言过强已改为记录差异口径（见报告 §0／§10），收益计算前完成。

## 附：门禁完整输出（单元 25 项＋端到端 39 项）

```
ok: C5 threshold 10pct central RT0.26 unfiltered = 1.75%
ok: C5 threshold 20pct central RT0.26 unfiltered = 1.01%
ok: C5 threshold 10pct central RT0.26 filtered40pct = 2.75%
ok: C5 threshold 20pct low RT0.17 unfiltered = 0.92%
ok: C5 threshold 10pct high RT0.50 unfiltered = 1.99%
ok: C5 threshold rises when cost rises
ok: C5 threshold rises when events/year falls
ok: C5 threshold 25 events 10pct central = 1.93%
ok: C5 sample size is event count: 90 events -> N=90, not 180
ok: C5 event obs is the mean of both legs
ok: C5 cross-event lag-1 autocorr of alternating series is -0.75
ok: C5 cross-event lag-1 autocorr of constant series is 0
ok: C5 event-day benchmark is not tradable at entry
ok: C5 placebo / buy-hold / R are tradable at entry
ok: C5 net: slip+spread embedded in prices, fee+funding separate
ok: C5 single-count guard: cost impact ~ -0.16%, not -0.32%
ok: C3 COIN-M 1x net delta equals spot holding (never neutral)
ok: C3 COIN-M 2x can be neutral with N=2*S*P, margin=S
ok: C3 worked example: +10% move -> +$100 on $2000 committed (+5%)
ok: C3 exit-price conversion differs from entry-price conversion
ok: C3 committed capital sums both legs
ok: C3 carry kill-line benchmarks exclude naked spot
ok: C3 1x with entry fee has finite but distant liquidation price ~1990x
ok: C3 2x liquidation boundary at mm=0.5% is 1.99x entry
ok: C3 2x liquidation boundary table: mm 0/1%/2% -> 2.00/1.98/1.96x
ALL REVISION UNIT TESTS PASSED
```

```
ok: E2E normal long enters D+2 open, exits D+5 close
ok: E2E normal long net = gross - fee - funding(4 days)
ok: E2E intraday stop triggers on D+4 and later prices are ignored
ok: E2E gap-through executes at open with one slip+spread charge
ok: E2E entry-day D+2 intraday move can trigger the stop
ok: E2E stop beats same-day close exit on D+5
ok: E2E dedup skips window-overlapping event, admits later event
ok: E2E missing close excludes the whole event
ok: E2E missing entry open excludes the whole event
ok: E2E complete event returns mean net and contribution
ok: E2E noise filter uses the new 0.26% central round-trip cost
ok: E2E early stop accrues only 1 funding day
ok: E2E short receives funding (net higher by funding vs gross-fee)
ok: E2E slip+spread counted once: diff ~ -0.16%, not -0.32%
ok: E2E short stop triggers on high with upward cost adjustment
ok: E2E D+1 prices cannot change the outcome
ok: E2E direction uses event-day closes only
ok: E2E stop base is the filled entry price, not the raw open
ok: E2E exit happens on D+5 (day index 3); no extension
ok: E2E stopped leg + held leg average into one event observation
ok: E2E missing Low excludes the event, not a no-trigger close
ok: E2E missing High excludes the event, not a no-trigger close
ok: E2E invalid bar (High < Low) excludes the event
ok: E2E D+2 open mismatch with the entry reference excludes the event
ok: E2E close leg matches 11 certain settlements (boundary excluded)
ok: E2E close leg excludes the exit-boundary settlement even if large
ok: E2E stop on D+2 gives funding interval [0, 2] settlements
ok: E2E stop on D+3 gives funding interval [3, 5] settlements
ok: E2E stop on D+5 gives funding interval [9, 11] settlements
ok: E2E short leg funding interval is the negated rate interval
ok: E2E irregular records govern: a 2-settlement day counts 10, not 11
ok: E2E gap over 24h inside the window excludes the leg
ok: E2E each leg uses its own asset funding history
ok: REV7 mixed-sign stop day: bounds are prefix extremes, not endpoints
ok: REV7 interval contains every possible prefix total
ok: REV7 all-negative stop day: bounds are [-0.0002, 0.0]
ok: REV7 short leg: net bounds from signed funding extremes
ok: REV7 close leg with negative rates is the exact (negative) sum
ok: REV7 gap over 24h excludes the leg even with negative rates
ALL C5 END-TO-END TESTS PASSED
```
