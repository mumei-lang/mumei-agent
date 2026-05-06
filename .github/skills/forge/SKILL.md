---
name: forge
description: Execute Mumei std-library forge tasks with python -m agent forge and inspect forge_log.json.
---

Given one or more forge task specs, generate verified atoms and append or create target std modules.

# Step 1: Inspect forge tasks

Action:
    List `forge_tasks/` or a provided tasks directory. Read task specs for `task_id`, `target_file`, `atoms`, `mode`, and retry/commit settings.

Expectation:
    Task JSON files are valid and point to a Mumei repository containing `std/`.

Result:
    Run a dry-run plan before invoking the LLM.

```bash
python -m agent forge --tasks-dir forge_tasks/ --mumei-repo ../mumei --dry-run
```

# Step 2: Run forge

Action:
    Execute one task or a bounded batch.

Expectation:
    The agent generates candidate code, verifies it with Mumei, applies it to the target std file, and records results in `forge_log.json`.

Result:
    Successful tasks add verified atoms; failed tasks include structured verifier feedback.

```bash
python -m agent forge --tasks-dir forge_tasks/ --mumei-repo ../mumei --max-tasks 1
python -m agent forge --tasks-dir forge_tasks/ --mumei-repo ../mumei --task path/to/task.json
```

# Step 3: Inspect `forge_log.json`

Action:
    Read the forge log and verify touched std modules directly.

Expectation:
    The log records `success`, `failed`, or `skipped`, attempts, target files, atoms added, and errors.

Result:
    Report atoms added, target file paths, verification status, and follow-up tasks.

```bash
python -m json.tool forge_log.json
mumei verify ../mumei/std/<target>.mm --json
```

# Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| tasks_dir | path | no | `forge_tasks/` | Directory of forge task JSON files |
| mumei_repo | path | no | `MUMEI_REPO` or `.` | Mumei checkout with `std/` |
| max_tasks | int | no | all | Maximum tasks to execute |
| task | path | no | | Run a single task spec |
| dry_run | flag | no | off | Preview without LLM or source edits |
| log_path | path | no | `<tasks_dir>/../forge_log.json` | Forge execution log |
