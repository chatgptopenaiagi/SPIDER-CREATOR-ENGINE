# Human time recovered

```text
HUMAN_TIME_RECOVERED = BASELINE_HUMAN_ACTIVE_TIME - SCE_ASSISTED_HUMAN_ACTIVE_TIME
```

All model values use seconds. `TimeMeasurements` keeps baseline and assisted human
active time separate from machine execution and total elapsed time. Setup, review,
and repair are separately recorded subsets of assisted human time. They are not
automatically added a second time. Concurrent machine and human activity may overlap.

Unknown values serialize as JSON `null`; a recovery result requires both active-time
measurements. Negative results remain negative. Values must be finite and nonnegative,
and known measurements require a source. The computed difference may be negative.

```python
from sce.core.models import TimeMeasurements

measured = TimeMeasurements(
    baseline_human_active_seconds=600,
    assisted_human_active_seconds=720,
    review_seconds=120,
    measurement_source="Illustrative example only; not a project measurement",
)
assert measured.human_time_recovered_seconds == -120
```

This example is arithmetic, not a productivity claim. SCE v0.1 has no measured human
baseline or assisted active-time study. Its observed build durations cannot establish
recovered human time. A later measurement workflow should record task comparability,
baseline method, measurement intervals, estimates versus observations, and uncertainty.
