# CI Workflows

## SI-5 Autonomous Proliferation

`.github/workflows/proliferate.yml` runs the scheduled autonomous stdlib
proliferation loop and can also be launched with `workflow_dispatch`.

Lean fallback is enabled by default in the `python -m agent proliferate` CLI and
therefore in CI. The workflow:

1. checks out `mumei-agent`, `mumei`, and best-effort `mumei-lean`;
2. installs Python and the mumei compiler dependencies;
3. installs Lean/Lake with `elan`;
4. verifies `lean --version` and `lake --version` for diagnostics;
5. runs proliferation with `--output-json /tmp/proliferate/summary.json`;
6. reports `lean_fallback_attempted`, `lean_fallback_proved`,
   `lean_fallback_failed`, and `lean_fallback_success_rate` to the job summary;
7. fails the workflow when Lean fallback attempted Z3 `unknown` atoms but proved
   fewer than 70% of them.

When Lean is unavailable, the agent does not abort the forge run. Instead,
`summary.json` records a per-result `lean_fallback.error_code` such as
`lean_unavailable` or `lake_missing`, and the atom-level failures contribute to
the fallback metrics.

See [Lean Fallback Troubleshooting](./LEAN_FALLBACK_TROUBLESHOOTING.md) for
diagnostic codes and remediation steps.

## Agent README CI Verification Gate

## CI Verification Gate

mumei-agent includes a CI verification pipeline that automatically verifies `.mm` files in pull requests.

### Usage in your project

Add to your `.github/workflows/verify.yml`:

```yaml
name: Mumei Verify
on: [pull_request]
jobs:
  verify:
    uses: mumei-lang/mumei-agent/.github/workflows/mumei-verify.yml@develop
    with:
      proof-cert: true
```

Or use the standalone script:

```bash
python scripts/ci_verify.py src/*.mm --proof-cert
```

## Existing-code audit composite action

`.github/actions/mumei-audit` is the adoption-oriented composite action for repositories that do not yet use `.mm`. It installs the mumei binary, sets up Python/uv with a dependency cache keyed by this repository's `uv.lock`, runs `python -m agent audit`, writes SARIF and JSON evidence, uploads SARIF to code scanning when present, and appends a concise audit summary plus timing to `GITHUB_STEP_SUMMARY`. The uploaded evidence artifact keeps audit evidence at the top level (`audit.json`, `audit.sarif`, audit logs, timing files, and `generated-baseline.json` when `--write-baseline` is used). Opt-in migration execution evidence is role-separated under `migration-execution/`: the upstream `migration_execution.json`, a machine-readable `status.json`, and copied generated artifacts. Generated `.mm` proof artifacts are not relabeled as audit proof certificates or host semantic-equivalence evidence.

Minimal caller workflow:

For a copyable payment/ledger starting point, use the validated repo-root starter in [`mumei-demo/templates/payment-ledger-starter`](https://github.com/mumei-lang/mumei-demo/tree/main/templates/payment-ledger-starter). It includes the canonical payment fixture, an empty audit baseline, a two-job audit/download-verification workflow, reviewer checklist, and migration evidence boundaries. Its offline verification job is fixture-smoke-only; real repositories with zero migration candidates are outside the current artifact verifier contract.

The minimal example below uses `@develop` only as a bootstrap illustration. Before production use, review the action and replace that mutable ref with a full immutable commit SHA or immutable release ref, as the starter does. Do not treat a moving branch pin as reproducible supply-chain policy.

```yaml
name: Mumei audit
on: [pull_request]

permissions:
  contents: read
  security-events: write  # required only for SARIF code-scanning upload

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: mumei-lang/mumei-agent/.github/actions/mumei-audit@develop
        with:
          code-file: src/
          language: python
          audit-args: --baseline audit-baseline.json --write-baseline .mumei-audit/generated-baseline.json --fail-on high-confidence
          # Optional: collect upstream generated-.mm migration execution evidence.
          migration-execution-output: .mumei-audit/migration_execution.json
```

The `audit-args` example uses the merged baseline contract directly: `audit-baseline.json` is a copyable `mumei.audit-baseline/v1` file such as `{"version":"mumei.audit-baseline/v1","fingerprints":[]}`, `--write-baseline` refreshes the fingerprint set for review, and `--fail-on high-confidence` keeps informational/model-limitation evidence visible without failing the job on lower-confidence findings. Keep `audit-args` on one line because the composite action treats it as a space-separated argument list.

Relevant inputs:

| Input | Default | Meaning |
|---|---:|---|
| `code-file` | required | Source file or directory to audit |
| `language` | auto-detect | Optional audit language override |
| `mumei-version` | `latest` | Version passed to the mumei installer |
| `audit-args` | empty | Extra space-separated `mumei-agent audit` arguments |
| `audit-output` | `.mumei-audit/audit.json` | Stable audit JSON artifact |
| `sarif-output` | `.mumei-audit/audit.sarif` | SARIF artifact for code scanning |
| `migration-execution-output` | empty (disabled) | Workspace-contained migration execution JSON path; enables collection |
| `upload-sarif` | `true` | Upload SARIF when produced |

The action emits GitHub Actions `notice` annotations for active findings (`baseline` other than `suppressed`); baseline-suppressed findings are never annotated, and annotations are a review signal only — they are not a proof or verification verdict, never use `warning`/`error` severity, and do not affect the audit exit classification or `--fail-on` policy. File annotations are attached only when `source_file` resolves to a workspace-relative path, so runner absolute paths never appear. The action preserves the audit CLI exit classification as the `audit_exit_code` output (`0` no failing code findings, `1` code evidence, `2` operational/extraction error) and fails the step for nonzero classifications after artifacts and the summary are written. LLM keys are never required: without `LLM_API_KEY`/`OPENAI_API_KEY`, audit uses the deterministic extraction path and records that limitation in the existing audit keys. If a caller opts into LLM-backed extraction, configure secrets at the job or environment level; do not pass secret values through action inputs.

When `migration-execution-output` is set, the action resolves the path inside the caller workspace, rejects traversal, symlinked output directories, and pre-existing output paths rather than deleting caller-controlled files, adds `--auto-migrate` automatically when the caller did not supply it, and passes `--migration-execution-output` only after probing the bundled audit CLI. Missing, malformed, schema-inconsistent, escaping, or unsupported migration output is an operational error rather than silently absent evidence. The action copies the upstream JSON plus non-symlink files from its generated-artifact directory into `migration-execution/` and exposes `migration_execution_status`, `migration_execution_ready_count`, and `migration_execution_operational_error_count`. Because the caller explicitly requested this evidence, candidate-level `operational_error` states also fail the action after artifacts are copied; `blocked` and `ready_for_human_review` remain human-review evidence and do not fail the action. The step summary reports `ready_for_human_review` / `blocked` / `operational_error` counts, `review_required`, and that consumer policy. This evidence means only that generated `.mm` artifacts were accepted or blocked as written; it is not proof that the host-language implementation is semantically equivalent, and it does not change audit exit-code, baseline, fail-on, or formal verdict semantics.

Timing outputs are `setup_seconds`, `audit_seconds`, and `total_seconds`. The repository self-test workflow `.github/workflows/mumei-audit-selftest.yml` runs the action against `examples/ci-small-repo` and publishes those values in each job summary. Initial local measurement for that small fixture on the validation VM was `0.01s` dependency setup with a warm uv cache, `1.23s` audit execution, and `1.24s` dependency-setup-plus-audit total; the composite action's own `setup_seconds` additionally includes Python setup and mumei installation on GitHub-hosted runners.

## 外部コード dogfooding 集計層

> **ステータス: ✅ Implemented** — 実装は `scripts/dogfood_triage_gate.py` と
> `.github/workflows/dogfood-triage.yml`。受け入れ条件は
> [`docs/ROADMAP.md`](./ROADMAP.md) の「外部コード dogfooding 堅牢性拡張」項目2を参照。

ディレクトリ / コーパス dogfood の出力を既存 verdict（`verified` / `refuted` / `unverifiable`）で
バケット分けする集計 / ゲート層。`refuted`（実バグ候補）のみを既存の human review 入口
（`next_steps` と `verification_violations`）に浮かせ、`unverifiable` は原因サブカテゴリ
（`skipped_rate_limited` / `timeout` / `no_function_declarations` / `encoding_gap` / `other`）へ
畳み込む。集計は 8 固定キー契約（`AUDIT_SCHEMA_KEYS`）と既存 verdict の上に載せ、新規分類や
別名 alias は導入しない。

### スケジュール実行ワークフロー

`.github/workflows/dogfood-triage.yml` は `proliferate.yml` と同型の構成
（mumei-agent / mumei の checkout → mumei compiler build → `uv sync` → LLM provisioning）で、
毎週水曜 02:00 UTC の cron と `workflow_dispatch` で起動する。既定プロファイルは `ollama-local`
（ローカル Ollama サーバ）で外部依存・シークレットはゼロ。`llm_profile: remote` を選んだ場合のみ
`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` を参照する。

`workflow_dispatch` 入力:

| 入力 | 既定値 | 用途 |
|------|--------|------|
| `corpus_paths` | `tests/corpora/oss` | 監査対象ディレクトリ（空白区切りで複数指定可） |
| `llm_profile` | `ollama-local` | LLM バックエンド（`ollama-local` / `remote`） |
| `llm_model` | `qwen3.5:4b` | モデルタグ |
| `fail_on_refuted` | `false` | `refuted` が 1 件でもあればジョブを失敗させる |
| `per_file_timeout` | `300` | 1 ファイルの監査上限秒数。超過したファイルは `unverifiable` / `timeout` として打ち切る |

結果は job summary に verdict バケット表として出力され、`dogfood-triage` アーティファクトとして
`triage.json` / `triage.md` / `triage.log` / `verdict_history.json` がアップロードされる。

### per-file timeout 監視

`--per-file-timeout` を指定すると、ディレクトリ監査はファイル単位の子プロセス（`agent/dogfood_timeout.py`）で
実行され、予算を超えたファイルのみを強制終了して残りのコーパスを守る。打ち切ったファイルは
既存語彙のまま `unverifiable` の `timeout` サブカテゴリに入り、新規分類は作らない。job summary には
遅いファイルの秒数と構造的 risk marker（`large_function` / `inline_assembly` / `complex_generics`）が
出力されるので、コーパス拡大時にどの形が高いのかを再実行なしで判定できる。

### verdict バケットの時系列

`--history-file` で指定した JSON に各 run の verdict 件数が追記され（ワークフローでは `actions/cache` で
保持）、job summary に時系列表とアラートが出力される。検知は 2 種で、いずれも `::warning::` 注釈と
なりジョブの成否には影響しない:

- **`refuted` 急増** — 直前複数 run の平均に対して `--refuted-spike-min-delta`（既定 2 件）以上かつ
  50% 以上増えたとき。
- **`unverifiable` サブカテゴリの偏り** — 1 つの原因が `--unverifiable-skew-share`（既定 60%）以上を
  占め、かつベースライン比で 20 ポイント以上増えたとき。

履歴ファイルは助言情報なので、欠損・壊れていてもゲートは失敗せず、その run の時系列が短くなるだけである。

### ローカル実行

```bash
MUMEI_BIN=/path/to/mumei uv run python scripts/dogfood_triage_gate.py \
  tests/corpora/oss \
  --json-output /tmp/dogfood/triage.json \
  --markdown-output /tmp/dogfood/triage.md \
  --per-file-timeout 300 \
  --slow-file-threshold 30 \
  --history-file /tmp/dogfood/verdict_history.json \
  --fail-on-refuted
```

`--fail-on-refuted` を省略すると `refuted` があっても終了コードは 0 のままで、`::warning::`
注釈のみを出力する（観測モード）。`GITHUB_STEP_SUMMARY` が設定されている場合は Markdown が
自動で追記される。

### トリアージ結果の読み方

- `refuted` の増加 → 決定的抽出のリグレッション、または実際のバグ検出。`next_steps` に従い
  `migrate-suggest` → `heal` を回す。
- `unverifiable` の偏り → 環境要因（`timeout` は Z3 予算、`skipped_rate_limited` は LLM レート制限、
  `no_function_declarations` は抽出対象なし、`encoding_gap` は lowering 未対応）。
- `verified` は集計値のみを追う（個別ファイルは列挙しない）。

コーパス自体の妥当性（`requires` / `ensures` が既存 oracle を満たすこと）は
`tests/test_foreign_code_oss_corpus.py`、集計 / ゲート層の挙動は
`tests/test_dogfood_triage_gate.py`、per-file timeout 監視は `tests/test_dogfood_timeout.py`、
時系列と急増 / 偏り検知は `tests/test_dogfood_trend.py` が push ごとに回帰テストする。
