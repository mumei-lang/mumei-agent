---
name: health
description: Measure Mumei std proof health with python -m agent health --mumei-repo and interpret health_score.
---

Given a Mumei compiler checkout, measure the verification health of its `std/` library.

# Step 1: Confirm the Mumei repo path

Action:
    Locate a repository containing `std/` and a usable Mumei binary via `MUMEI_BIN` or `--mumei-bin`.

Expectation:
    `--mumei-repo` points to the compiler checkout and `std/**/*.mm` files exist.

Result:
    Proceed to health measurement.

# Step 2: Run health measurement

Action:
    Invoke `python -m agent health --mumei-repo`.

Expectation:
    The tool verifies every std `.mm` file and prints JSON or table output.

Result:
    The report includes `total_files`, `verified_files`, `failed_files`, `total_atoms`, `verified_atoms`, `trusted_atoms`, `todo_count`, `details`, and `health_score`.

```bash
python -m agent health --mumei-repo ../mumei --format json
python -m agent health --mumei-repo ../mumei --format table
```

# Step 3: Interpret `health_score`

Action:
    Read the score and supporting counts.

Expectation:
    `health_score` ranges from `0.0` to `1.0`. It rewards verified atoms and penalizes trusted atoms/TODO density. Any failed file should be treated as a regression for autonomous forge/proliferation workflows.

Result:
    Report baseline, gaps, and whether **proliferate** should run.

# Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| mumei_repo | path | yes | | Mumei checkout containing `std/` |
| mumei_bin | path/string | no | `MUMEI_BIN` or `mumei` | Mumei CLI command |
| format | string | no | `json` | `json` or `table` |
