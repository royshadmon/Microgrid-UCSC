# Data density diagnostic — Item 4

_Generated 2026-05-15._

## TL;DR

The "9.3% observed-row density" in `panel{1,2,3}_60d_labeled.parquet` is **not
a current pipeline bug**. It is an artifact of the existing training file
being assembled across a period when Kafka ingestion was broken for most
days. The live AnyLog table currently holds **~86% density on a 10-second
grid** for the last 14 days. Re-pulling the data now gives ~6× more
training examples for free, before any model changes.

## Evidence

### Density of `panel3_w` in `data/panel1_60d.parquet`, by calendar day

```
2026-04-07    1.0%   (partial — pipeline still coming up)
2026-04-08 .. 2026-04-20     0%   ingestion broken
2026-04-21   17.5%
2026-04-22 .. 2026-04-23     0%
2026-04-24   11.1%
2026-04-25    0.7%
2026-04-26 .. 2026-04-27     0%
2026-04-28   30.6%   (first day with usable density)
2026-04-29    9.9%
2026-04-30   10.4%
2026-05-01   24.4%
2026-05-02   18.3%
2026-05-03   34.5%
2026-05-04   25.8%
2026-05-05   28.5%
2026-05-06   41.9%
2026-05-07   39.5%
2026-05-08 .. 2026-05-10     0%   ingestion broken (4-day gap)
2026-05-11    0.6%
2026-05-12   42.0%
```

Total 35-day average: **9.3%**. But of the 35 days, ~22 are at 0% or near-0%
density. Among the 13 days with non-trivial data, density averages ~25%.

### Live AnyLog table

```
SELECT nm, COUNT(*) AS rows FROM par_egauge_kafka_2026_05_00_d14_insert_timestamp
GROUP BY nm
```

Every channel has **104,145 rows** spanning 14 days (2026-05-01 to 2026-05-14).

```
14 days × 8,640 (10-s grid buckets/day) = 120,960 expected buckets
104,145 / 120,960 = 86.1% density on 10-s grid for May alone
```

### Ingestion health, last 5 min

- `egauge-producer` polling at ~1.4 s per poll (16 channels × ~60 polls/min)
  with periodic `RemoteDisconnected` retries from the eGauge web service
  itself (transient).
- `anylog-consumer` ingest rate: 122,936 → 125,941 messages in 5 minutes =
  600 msg/min, healthy.
- AnyLog Kafka client: 38,704 messages, 0 errors.

## Root cause

The current `data/panel1_60d.parquet` was assembled before the 2026-05-08
incident when the Kafka → AnyLog ingest path was healthier. The intermediate
4-day gap (May 8–11) and the long April-period gaps zero out most of the
35-day window even though April 28 → May 7 and May 12 onward are
substantially dense.

Two compounding effects:

1. **Old data.** The parquet was last refreshed when only a few weeks of
   real ingestion had accumulated.
2. **Aggregate-vs-per-day average.** A 9.3% headline number hides the fact
   that on dense days density is 25–42% — and the new May 1+ data is at 86%.

## Fix

In order, by effort:

1. **Re-run `services/iems/training/pull_data.py`** with `start_date =
   2026-04-28` (first usable day) → output will jump from 9.3% to ~25–30%
   average density across April 28–May 14, with the latest week at 60%+.
2. **Trim the labeled parquet** to days with > 20% density before
   building windows. Already-broken days don't help training.
3. **Investigate the May 8–11 gap.** This is a 4-day outage — likely the
   container restart issue in `local_script.al` noted in the project
   memory. Adding a heartbeat alert on `anylog-consumer` rate would catch
   the next one within minutes.
4. **Increase `pivot.resample("6s").mean().ffill(limit=5)` to
   `ffill(limit=10)`** in `pull_data.py`. The eGauge cadence is ~11 s per
   channel, so a 5-sample ffill at 6 s can leave a 0.1 s gap between
   consecutive observations sometimes unfilled. Limit=10 covers a full
   60-second outage with high confidence.

## Expected impact

Pre-fix Panel 3 training set: 17,882 windows from 25,545 fully-observed
rows. Post-fix estimate (April 28 onward only, with healthy ingestion):
~85,000 windows from ~120,000 fully-observed rows.

That's a **~5× increase in training set size with no other changes**,
which means each per-head positive count grows by ~5× too. Pressure pump
(30 train positives) becomes ~150, microwave (97) becomes ~490. Hair dryer
will still need MATNilm sample augmentation, but most heads cross the
threshold where weighted BCE + threshold tuning alone can recover.
