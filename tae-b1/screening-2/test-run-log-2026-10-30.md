=== C5 test run log ===
Date (CST): 2026-10-30 12:27:06
Repo HEAD (pre-push): 1e0f283

--- revision-unit-tests.py ---
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

--- c5-e2e-tests.py ---
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
ok: E2E full hold matches 12 settlements, not an average
ok: E2E stop on D+3 matches only 6 settlements, nothing after
ok: E2E stop on D+2 matches only 3 settlements
ok: E2E short leg receives funding (negative funding cost)
ok: E2E missing settlement record excludes the leg, never fills 0
ok: E2E each leg uses its own asset funding history
ALL C5 END-TO-END TESTS PASSED
