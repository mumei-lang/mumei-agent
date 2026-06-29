---
name: testing-vstd-forge-expansion
description: Test forge-driven vStd stdlib expansion across mumei-agent and mumei. Use when validating forge_tasks updates, forge_log.json entries, or generated std/*.mm modules.
---
# Testing vStd Forge Expansion

## Devin Secrets Needed

- None for post-generation validation of committed PRs.
- `LLM_API_KEY` only if re-running live forge generation, not for proof-certificate verification or forge-log validation.

## Repos

- `mumei-agent`: contains `forge_tasks/*.json` and `forge_log.json`.
- `mumei`: contains generated or refreshed `std/**/*.mm` modules and the `target/debug/mumei` CLI.

## Validation Flow

1. Confirm target task coverage in `mumei-agent/forge_log.json`:
   - each expected `task_id` is present;
   - each expected entry has `status == "success"`;
   - `error == null`;
   - if a task retained an existing module after a generation-health gate, the entry should explain that in `note`.

2. Run targeted proof-certificate verification from `/home/ubuntu/repos/mumei` with explicit output paths so artifacts do not land unexpectedly in the repo root:

```bash
rm -rf /home/ubuntu/mumei-forge-stdlib-evidence
mkdir -p /home/ubuntu/mumei-forge-stdlib-evidence
LLVM_SYS_170_PREFIX=/usr/lib/llvm-17 LIBCLANG_PATH=/usr/lib/x86_64-linux-gnu \
  ./target/debug/mumei verify --proof-cert \
  --output /home/ubuntu/mumei-forge-stdlib-evidence/<module>.proof.json \
  std/<module>.mm
```

For each generated certificate, parse JSON and assert:
- `all_verified == true`;
- the `atoms[*].name` set matches the atoms expected from the forge task/doc update;
- no atom has `z3_check_result` equal to `sat` or `unknown`.

3. Run full std regression from `/home/ubuntu/repos/mumei`:

```bash
failures=0
for f in $(find std -name '*.mm' | sort); do
  echo "===== $f ====="
  if ! LLVM_SYS_170_PREFIX=/usr/lib/llvm-17 LIBCLANG_PATH=/usr/lib/x86_64-linux-gnu \
    ./target/debug/mumei verify "$f"; then
    failures=$((failures+1))
  fi
done
echo "STD_VERIFY_FAILURES=$failures"
test "$failures" -eq 0
```

4. Clean generated verification artifacts before final status:
   - remove repo-root `cross_spec.json` if plain `verify` generated it;
   - keep evidence under `/home/ubuntu/mumei-forge-stdlib-evidence` or another non-repo path;
   - confirm `git status --short` is clean in both repos.

## Reporting

- This is shell-only runtime testing; do not record the browser.
- In the PR test comment, list proof-cert verification, forge-log validation, full std regression, and current CI status.


## Deterministic Forge Task Regression

For a focused deterministic-body forge regression, collect the exact pytest node first if unsure:

```bash
cd /home/ubuntu/repos/mumei-agent
uv run pytest tests/test_forge.py --collect-only -q | grep core_guards
```

For `vstd_core_guards.json`, the verified focused node is:

```bash
cd /home/ubuntu/repos/mumei-agent
uv run pytest tests/test_forge.py::TestForgeOneModule::test_core_guards_task_uses_deterministic_bodies -q
```

Expected assertions:

- The rendered module contains the expected atom signatures.
- `forge.config.create_client.call_count == 0`, proving no LLM client was used.

## Forge Log and Certificate Schema Notes

`forge_log.json` uses a top-level `runs` array. For deterministic stdlib forge tasks, validate the matching run rather than looking for an `entries` key:

```python
runs = [r for r in log["runs"] if r["task_id"] == "vstd-core-guards"]
assert len(runs) == 1
assert runs[0]["status"] == "success"
assert runs[0]["error"] is None
assert runs[0]["outside_decidable_fragment"] is False
```

When checking proof certificates for Z3-proven generated std atoms, assert the solver result and status separately:

- `z3_check_result == "unsat"`
- `z3_result_class == "unsat"`
- `status == "verified"`
- no atom has `z3_check_result` equal to `sat` or `unknown`

Do not expect `z3_result_class == "verified"`; `verified` is the certificate atom `status`.
