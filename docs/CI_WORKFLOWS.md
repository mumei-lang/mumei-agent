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

結果は job summary に verdict バケット表として出力され、`dogfood-triage` アーティファクトとして
`triage.json` / `triage.md` / `triage.log` がアップロードされる。

### ローカル実行

```bash
MUMEI_BIN=/path/to/mumei uv run python scripts/dogfood_triage_gate.py \
  tests/corpora/oss \
  --json-output /tmp/dogfood/triage.json \
  --markdown-output /tmp/dogfood/triage.md \
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
`tests/test_dogfood_triage_gate.py` が push ごとに回帰テストする。
