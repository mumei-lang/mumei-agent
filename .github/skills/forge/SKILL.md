---
name: forge
description: Execute Mumei std-library forge tasks with python -m agent forge and inspect forge_log.json.
---

Given one or more forge task specs, generate verified atoms and append or create target std modules.

# Devin Secrets Needed

- `LLM_API_KEY` or `OPENAI_API_KEY`: required for live forge generation. Use dry-run mode when no LLM key is available.

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

If the Mumei CLI is not on `PATH`, set `MUMEI_BIN` explicitly:

```bash
MUMEI_BIN=/path/to/mumei python -m agent forge --tasks-dir forge_tasks/ --mumei-repo ../mumei --dry-run
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

For validation without touching the real sibling Mumei checkout, copy `std/` into a scratch directory and point `--mumei-repo` there. When generated code imports std modules such as `std/core`, set `MUMEI_STD_PATH` to the scratch `std/` directory so temp-file verification can resolve imports:

```bash
MUMEI_BIN=/path/to/mumei MUMEI_STD_PATH=/path/to/scratch/std \
  python -m agent forge --task forge_tasks/example.json \
  --mumei-repo /path/to/scratch --log-path /path/to/forge_log.json
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
mumei check ../mumei/std/<target>.mm
mumei verify ../mumei/std/<target>.mm --json
```

If using a scratch checkout, keep `MUMEI_STD_PATH` set for direct checks too:

```bash
MUMEI_STD_PATH=/path/to/scratch/std mumei check /path/to/scratch/std/<target>.mm
MUMEI_STD_PATH=/path/to/scratch/std mumei verify --json /path/to/scratch/std/<target>.mm
```

If `mumei verify --json` exits 0 with `status: passed` but reports `verified: 0` and skipped atoms, report the run as generation/check validation rather than full Z3 proof evidence.

# Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| tasks_dir | path | no | `forge_tasks/` | Directory of forge task JSON files |
| mumei_repo | path | no | `MUMEI_REPO` or `.` | Mumei checkout with `std/` |
| max_tasks | int | no | all | Maximum tasks to execute |
| task | path | no | | Run a single task spec |
| dry_run | flag | no | off | Preview without LLM or source edits |
| log_path | path | no | `<tasks_dir>/../forge_log.json` | Forge execution log |
