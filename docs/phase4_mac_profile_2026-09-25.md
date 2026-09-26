# Phase 4 Mac profile

Command:

```text
PYTHONPATH=src python scripts/profile_phase4.py --iterations 100
```

Result: 100 natural-image plan builds, 2,200 events, 102,469 calls, 0.229 s
profiled wall time, and 71,106 peak traced bytes. The dominant cumulative
paths were plan construction, natural-image ordering, frame-offset creation,
dataclass replacement, and stable JSON serialization. This is a desktop
software profile only; it is not a Pi timing or memory acceptance result.
