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

## 外部コード dogfooding 集計層（Planned / 未着手）

> **ステータス: Planned（未着手）** — 実ワークフローファイルはまだ追加していない。詳細な受け入れ条件は
> [`docs/ROADMAP.md`](./ROADMAP.md) の「外部コード dogfooding 堅牢性拡張（Planned / 未着手）」項目2を参照。

次段階として、ディレクトリ / コーパス dogfood の出力を既存 verdict（`verified` / `refuted` / `unverifiable`）で
バケット分けする集計 / ゲート層を、`.github/workflows/proliferate.yml` と同型のスケジュール実行ワークフロー
（cron + `ollama-local` で外部依存ゼロ）として恒久運用に組み込む構想がある。`refuted`（実バグ候補）のみを
human review に浮かせ、`unverifiable` を原因サブカテゴリ（`skipped_rate_limited` / `timeout` /
`no_function_declarations` / `encoding_gap`）へ畳み込む。集計は 7 固定キー契約（`AUDIT_SCHEMA_KEYS`）と
既存 verdict の上に載せ、新規分類や別名 alias は導入しない。実ワークフロー追加時に本ファイルへ運用手順を追記する。
