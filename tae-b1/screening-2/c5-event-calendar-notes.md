# C5 Event Calendar — Assembly Notes (DRAFT)

Exploration window: **2020-01-01 to 2026-10-30, inclusive.**
Status: **draft, not frozen.** No prices, returns, or strategy outcomes were
computed. This file records only how the dates in
`c5-event-calendar-draft.csv` were assembled and verified.

## 1. Counts per series per year

Rows count actual releases whose release date falls inside the window.
A January release covers the previous month's reference period (e.g. the
CPI released 2020-01-14 is the December 2019 CPI); inclusion is by
release date, not reference month.

| Year | FOMC | CPI | NFP | Year total |
|------|------|-----|-----|------------|
| 2020 | 8 | 12 | 12 | 32 |
| 2021 | 8 | 12 | 12 | 32 |
| 2022 | 8 | 12 | 12 | 32 |
| 2023 | 8 | 12 | 12 | 32 |
| 2024 | 8 | 12 | 12 | 32 |
| 2025 | 8 | 11 | 11 | 30 |
| 2026 (to 2026-10-30) | 7 | 10 | 10 | 27 |
| **Total** | **55** | **81** | **81** | **217** |

Short years are explained by the window and by the 2025 cancellations,
not by missing data: 2025 has 11 CPI/NFP rows because the October 2025
releases were cancelled (see §4); 2026 is a partial year ending 2026-10-30.

## 2. Official source pages used

Only `federalreserve.gov` (FOMC) and `bls.gov` (CPI, Employment Situation)
were used. No third-party calendar was used for any date.

FOMC:

```
https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
```
FOMC meeting calendars, 2021–2027 (page last updated 2026-10-28). Used for
all 2021–2026 FOMC rows.

```
https://www.federalreserve.gov/publications/2020-minutes-of-fomc.htm
```
2020 FOMC minutes index, which lists the eight scheduled 2020 meetings.
Used for all 2020 FOMC rows (the calendars page above starts at 2021).

CPI / Employment Situation — BLS annual "Schedule of Selected Releases"
pages:

```
https://www.bls.gov/schedule/2020/
https://www.bls.gov/schedule/2021/
https://www.bls.gov/schedule/2022/home.htm
https://www.bls.gov/schedule/2023/home.htm
https://www.bls.gov/schedule/2024/
https://www.bls.gov/schedule/2025/
https://www.bls.gov/schedule/2026/
```

Revised dates (2025 and 2026 funding lapses) — BLS revised-release-dates
page, last modified 2026-02-12:

```
https://www.bls.gov/bls/2025-lapse-revised-release-dates.htm
```

September 2025 CPI release itself (embargo/release line 8:30 a.m. ET,
Friday, October 24, 2025):

```
https://www.bls.gov/news.release/archives/cpi_10242025.htm
```

Corroborating page for the 2025 lapse (staff recall, release date):

```
https://www.bls.gov/cpi/additional-resources/2025-federal-government-shutdown-impact-cpi-faq.htm
```

Each CSV row carries the `source_url` of the page its date was taken
from. Rows whose dates differ from the original yearly schedule cite the
revised-release-dates page (or, for the September 2025 CPI, the release
itself); all other BLS rows cite the yearly schedule page for their year.

## 3. How FOMC announcement dates were determined

Announcement date = the **second day of the scheduled FOMC meeting**,
because the policy statement is issued at the end of the meeting. Meeting
dates were read from the official calendars above; the announcement date
is the meeting's final day in every case in this window except the
2020-03-15 single-day meeting (see §4).

Excluded, deliberately: the 2025-08-22 notation vote listed on the FOMC
calendar page is a vote, not a meeting, and produces no rate decision; it
has no row. The 2020-03-03 emergency rate cut and the 2020-03-23 notation
vote were unscheduled actions, not part of the eight scheduled 2020
meetings, and have no rows.

## 4. Delays, cancellations, and anomalies

### 4.1 FOMC, March 2020

The regularly scheduled March 17–18, 2020 meeting was cancelled and
replaced by a single-day meeting held **2020-03-15** (a Sunday), with the
statement issued the same day. The event date in the CSV is 2020-03-15.
The March 3, 2020 emergency cut is a separate unscheduled action and is
not counted as one of the eight 2020 meetings.

### 4.2 2025 funding lapse (2025-10-01 to 2025-11-12)

Confirmed by the BLS revised-release-dates page and the shutdown-impact
FAQ. Actual dates in the CSV:

| Release | Originally scheduled | Actual (in CSV) |
|---------|----------------------|-----------------|
| CPI, September 2025 reference | 2025-10-15 | **2025-10-24** (staff recalled 2025-10-09 to 2025-10-24 to produce it for the SSA cost-of-living adjustment; the only release produced during the lapse) |
| Employment Situation, September 2025 reference | 2025-10-03 | **2025-11-20** |
| Employment Situation, November 2025 reference | 2025-12-05 | **2025-12-16** |
| CPI, November 2025 reference | 2025-12-10 | **2025-12-18** |
| Employment Situation, December 2025 reference | 2026-01-09 | 2026-01-09 (unchanged; counted in 2026) |
| CPI, December 2025 reference | 2026-01-13 | 2026-01-13 (unchanged; counted in 2026) |

**Cancelled — no row:** the October 2025 CPI and the October 2025
Employment Situation were **not published** (the BLS revised page lists
"October 2025 CPI — not published" and "October 2025 Employment Situation
— not published"). A cancelled release is not an event; no row was
created for either, and the reference month simply has no event in the
calendar.

### 4.3 2026 funding lapse

Confirmed by the BLS revised-release-dates page. Actual dates in the CSV:

| Release | Originally scheduled | Actual (in CSV) |
|---------|----------------------|-----------------|
| Employment Situation, January 2026 reference | 2026-02-06 | **2026-02-11** |
| CPI, January 2026 reference | 2026-02-11 | **2026-02-13** |

The revised page lists no further revisions after February 2026; all
March–October 2026 dates are as shown on the 2026 schedule page.

### 4.4 Other schedule quirks (dates as officially scheduled, not delays)

- CPI, April 2024 reference, released **2024-05-15** (early release per
  the BLS schedule; not a lapse).
- CPI, October 2023 reference, released **2023-11-14** (per the BLS
  schedule).
- Employment Situation, February 2023 reference, released **2023-03-10**
  (per the BLS schedule).
- Employment Situation, December 2024 reference, released **2025-01-10**
  (per the BLS schedule); counted in 2025 by release date.

### 4.5 Same-date coincidences

One row per event; two events on the same date each keep their own row:

- **2020-06-10**: CPI release and FOMC announcement on the same day.
- **2024-06-12**: CPI release and FOMC announcement on the same day.

### 4.6 Window boundaries (excluded, after 2026-10-30)

- FOMC meeting December 8–9, 2026 (announcement 2026-12-09).
- Employment Situation, October 2026 reference (2026-11-06).
- CPI, October 2026 reference (2026-11-10).

## 5. UNVERIFIED dates

**None.** Every date in the CSV was verified against an official
federalreserve.gov or bls.gov page listed in §2. No date was filled from
a non-official calendar, and no date is marked UNVERIFIED.

## 6. Limitations

- Dates are release/announcement dates only. This calendar says nothing
  about release times of day, about what was released, or about prices.
- If BLS or the Federal Reserve later revises a historical schedule page,
  the CSV's `source_url` values still identify the pages used; any
  discrepancy found later must be recorded as a correction, not silently
  overwritten.
- The 2026 rows cover only releases dated on or before 2026-10-30. The
  calendar must be extended, not edited in place, if the window is
  extended.
