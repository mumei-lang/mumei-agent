# Intent Tracking

Intent tracking compares a specification before and after refinement so the
agent can warn when a satisfiability fix may drift away from the user's
original requirements.

## Concepts

- **Intent change**: A change to `requires`, `ensures`, or `effects`.
- **Drift score**: A `0.0` to `1.0` preservation score. `1.0` means unchanged
  intent; lower values indicate weakened, removed, or violated intent.
- **Intent preservation threshold**: `AgentConfig.intent_drift_threshold`
  defaults to `0.7`. Results below the threshold emit warnings.
- **Traceability integration**: `SpecCodeMapping.intent_drift_score` lets
  spec-to-code visualizations show which generated-code regions are affected by
  drift-prone spec changes.

## Configuration

```bash
ENABLE_INTENT_TRACKING=true
INTENT_DRIFT_THRESHOLD=0.7
```

## Usage

```python
from agent.config import AgentConfig
from agent.intent_tracker import IntentTracker

tracker = IntentTracker(AgentConfig())
result = tracker.track_intent_drift(
    {"requires": "x >= 0 && x < 100", "ensures": "result >= 0"},
    {"requires": "x >= 0", "ensures": "result >= 0"},
)

if not result.intent_preserved:
    print(result.warnings)
```

During `run_refinement_loop()`, intent tracking runs after each refined spec is
produced. Warnings are logged when the drift score falls below the configured
threshold or when a required field is removed.
