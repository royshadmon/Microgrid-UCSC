# Panel 1 real-time monitor — session summary

- Session start: `2026-05-12T04:55:11+00:00`
- Session end:   `2026-05-12T05:58:33+00:00`
- Total ticks:   365
- Tick interval: 10 s
- Errors:        0

```
=== Panel 1 RNN session summary @ 2026-05-12T05:58:33+00:00 (365 ticks · 63.4 min) ===
Heat Pump:    ON    0 ticks (0.0%)   OFF  365 ticks (100.0%)
              0 off→on transitions   0 on→off transitions
Solar Pump:   ON    0 ticks (0.0%)   OFF  365 ticks (100.0%)
              0 off→on transitions   0 on→off transitions
Inference:    avg 0.46 ms  p50 0.38  p99 1.97  (model only)
Event log:    /Users/harshranjan/microgrid-manager/services/iems/training/reports/realtime_panel1_2026-05-12T0455.jsonl
Errors:       0
Decision thresholds: HP=0.68  SP=0.53
```

## Off→on transitions by local hour

| hour (PT) | heat pump | solar pump |
|---:|---:|---:|
