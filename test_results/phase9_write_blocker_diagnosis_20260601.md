# Phase 9 — nilm_disaggregated write blocker (err_16) diagnosis

Date: 2026-06-01

## Symptom
nilm_disaggregated writes stopped 2026-05-28 23:54 (legacy loop). New MATNilm
loop also quarantines. par_nilm_disaggregated_2026_06_00 has 0 rows; 1926
err_16 files in operator /app/AnyLog-Network/data/error/.

## Diagnosis (conclusive — operator materialization layer, NOT migration/data)
1. Payload correct: no insert_timestamp; ts as "YYYY-MM-DD HH:MM:SS.ffffff" (no Z).
2. Table schema correct: ts/window_* = `timestamp without time zone`.
3. Streaming PUT returns HTTP 200 {"AnyLog.status":"Success"}.
4. Quarantined .err_16 rows show AnyLog re-serialized ts -> "2026-06-02T02:15:23.000000Z"
   (ISO-T + trailing Z), which fails coercion into `timestamp without time zone`.
5. Direct `psql -U demo -d customers INSERT ...` of the same row SUCCEEDS.
   => Per the runbook, success of the direct insert confirms it is the AnyLog
      JSON->SQL materialization layer (err_16), not the data.

## Scope
Pre-existing AnyLog operator infrastructure issue, independent of the model
migration. Began at the 05-28 partition roll (worked in par_..._2026_05_01).
No payload change fixes it (legacy used identical ts format).

## NOT attempted (needs user sign-off — CLAUDE.md rule 1)
Operator repartition / policy reinsert / operator restart. These have
previously caused long recovery sequences.

## Inference side: VERIFIED WORKING
Loop runs MATNilm dual-head ONNX + additive/mutex/battery rules, generates
correct per-appliance predictions every 30s (see --dry-run output). Only the
AnyLog materialization of those rows is blocked.
