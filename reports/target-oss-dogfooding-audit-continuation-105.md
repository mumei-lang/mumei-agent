# Target OSS no-LLM dogfooding audit — continuation 105 (batch 106)

Run: 2026-07-22T00:20:55.293437+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification.

## Notes

- 2 TSX files reported `errors=1` (`No Mumei atoms were generated from the extracted forge task spec.`) while still returning `verification_status: verified`; they contain React component arrow functions with no extractable function signatures.
- One Go file (`go/src/internal/trace/version/version.go`) was refuted on the first run and fixed by recognizing the ``int(idx) < len(arr)`` upper-bound guard.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| influxdb | `core/influxdb2_client/src/lib.rs` | verified |  |
| prysm | `validator/client/duties.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/pulljob_auth_test.go` | verified |  |
| prysm | `api/server/structs/conversions.go` | verified |  |
| go | `test/fixedbugs/issue30862.dir/main.go` | verified |  |
| go | `src/math/rand/v2/pcg.go` | verified |  |
| grafana | `pkg/setting/setting_grafana_javascript_agent.go` | verified |  |
| prysm | `beacon-chain/db/kv/migration_block_slot_index.go` | verified |  |
| grafana | `pkg/util/md5.go` | verified |  |
| grafana | `public/app/features/plugins/extensions/logs/LogViewer.tsx` | verified |  |
| go | `test/typeparam/recoverimp.dir/a.go` | verified |  |
| grafana | `public/app/plugins/panel/logs/panelcfg.gen.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/handlers/plugins/all-plugin-handlers.ts` | verified |  |
| prysm | `testing/spectest/minimal/deneb__epoch_processing__slashings_test.go` | verified |  |
| prysm | `encoding/ssz/query/analyzer.go` | verified |  |
| influxdb | `core/error_reporting/src/lib.rs` | verified |  |
| prysm | `beacon-chain/cache/depositsnapshot/deposit_fetcher_test.go` | verified |  |
| influxdb | `influxdb3_server/src/grpc.rs` | verified |  |
| go | `src/encoding/json/decode.go` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/SharePublicDashboard/ModalAlerts/UnsupportedTemplateVariablesAlert.tsx` | verified |  |
| grafana | `public/app/plugins/panel/candlestick/CandlestickPanel.tsx` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/StackedEditor/StackedSection.tsx` | verified |  |
| influxdb | `core/catalog_cache/src/api/list/v2.rs` | verified |  |
| go | `src/internal/trace/version/version.go` | verified |  |
| go | `src/runtime/signal_solaris.go` | verified |  |
| grafana | `public/app/plugins/datasource/mysql/webpack.config.ts` | verified |  |
| grafana | `pkg/tests/apis/provisioning/connection/github_branch_protection_test.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/proposer_exits.go` | verified |  |
| influxdb | `core/catalog_cache/src/local/limit.rs` | verified |  |
| go | `test/fixedbugs/bug392.dir/one.go` | verified |  |
| grafana | `pkg/registry/apis/ofrep/register_test.go` | verified |  |
| go | `src/runtime/malloc_generated.go` | verified |  |
| influxdb | `influxdb3_catalog/src/format/record.rs` | verified |  |
| influxdb | `core/arrow_util/src/test_util.rs` | verified |  |
| influxdb | `core/tokio_metrics_bridge/src/bridge.rs` | verified |  |
| go | `src/runtime/race/race_linux_test.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/gloas_builder_api.ssz.go` | verified |  |
| go | `test/checkbce.go` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareButton/share-externally/ShareTypeSelect.tsx` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| influxdb | `influxdb3_load_generator/src/lib.rs` | verified |  |
| prysm | `encoding/ssz/query/query_test.go` | verified |  |
| grafana | `public/app/features/canvas/elements/triangle.tsx` | verified |  |
| go | `src/crypto/internal/fips140/ed25519/cast.go` | verified |  |
| go | `src/internal/goos/zgoos_js.go` | verified |  |
| grafana | `pkg/expr/sql_command.go` | verified |  |
| go | `src/encoding/gob/decgen.go` | verified |  |
| go | `test/fixedbugs/issue4066.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/instrumented_store_test.go` | verified |  |
| influxdb | `influxdb3_py_api/src/lib.rs` | verified |  |
| prysm | `contracts/deposit/helper.go` | verified |  |
