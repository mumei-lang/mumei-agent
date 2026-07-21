# Target OSS no-LLM dogfooding audit — continuation 101 (batch 102)

Run: 2026-07-21T23:59:57.122122+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification after one agent-side heuristic fix.

- Rust trait method signatures without bodies (e.g. ``fn id(&self);``) are no longer treated as missing implementations, avoiding ``No function signatures were extracted`` false positives.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| grafana | `apps/provisioning/pkg/repository/github/mutator_test.go` | verified |  |
| go | `src/go/printer/math.go` | verified |  |
| influxdb | `influxdb3_processing_engine/src/manager.rs` | verified |  |
| go | `src/cmd/go/internal/modfetch/coderepo_test.go` | verified |  |
| go | `src/crypto/internal/fips140deps/fipsdeps_test.go` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/config/InfluxInfluxQLConfig.tsx` | verified |  |
| go | `test/fixedbugs/issue77604.go` | verified |  |
| prysm | `cmd/validator/log.go` | verified |  |
| prysm | `testing/spectest/minimal/bellatrix__ssz_static__ssz_static_test.go` | verified |  |
| prysm | `beacon-chain/core/deneb/upgrade_test.go` | verified |  |
| grafana | `public/app/features/explore/CorrelationEditorModeBar.tsx` | verified |  |
| prysm | `beacon-chain/p2p/partialdatacolumnbroadcaster/publish_blocking_test.go` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelDataPane/PanelDataQueriesTab.tsx` | verified |  |
| grafana | `pkg/services/dashboardversion/dashvertest/fake.go` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/ResourcePicker/utils.ts` | verified |  |
| grafana | `pkg/registry/apis/provisioning/webhooks/pullrequest/render.go` | verified |  |
| grafana | `public/app/features/connections/pages/AddNewConnectionPage.tsx` | verified |  |
| prysm | `beacon-chain/core/helpers/metrics.go` | verified |  |
| go | `test/fixedbugs/issue15920.go` | verified |  |
| prysm | `api/apiutil/header.go` | verified |  |
| influxdb | `core/influxdb2_client/src/models/file.rs` | verified |  |
| grafana | `public/app/plugins/panel/piechart/PieChartPanel.tsx` | verified |  |
| grafana | `pkg/services/ngalert/api/generated_base_api_provisioning.go` | verified |  |
| go | `test/abi/result_live.go` | verified |  |
| grafana | `scripts/codeowners-manifest/index.js` | verified |  |
| influxdb | `core/arrow_util/benches/iter_set_positions.rs` | verified |  |
| grafana | `pkg/services/sqlstore/sqlutil/sqlutil.go` | verified |  |
| go | `src/internal/syscall/unix/at_sysnum_freebsd.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v40.go` | verified |  |
| prysm | `validator/keymanager/local/refresh.go` | verified |  |
| influxdb | `core/influxdb2_client/src/models/ast/mod.rs` | verified |  |
| influxdb | `core/iox_http/src/write/multi_tenant.rs` | verified |  |
| go | `test/fixedbugs/issue48357.go` | verified |  |
| go | `test/fixedbugs/issue5809.go` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/Theme.tsx` | verified |  |
| go | `test/typeparam/issue49536.dir/b.go` | verified |  |
| go | `src/cmd/go/internal/web/bootstrap.go` | verified |  |
| prysm | `time/slots/testing/mock_test.go` | verified |  |
| prysm | `validator/accounts/wallet/wallet_test.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/debug/handlers_test.go` | verified |  |
| prysm | `beacon-chain/state/stategen/history.go` | verified |  |
| go | `src/crypto/internal/fips140/aes/cbc.go` | verified |  |
| grafana | `pkg/services/ngalert/accesscontrol/alertmanager_imports.go` | verified |  |
| influxdb | `core/object_store_mem_cache/src/cache_system/hook/level_trigger.rs` | verified |  |
| influxdb | `influxdb3_startup/src/env_compat.rs` | verified |  |
| influxdb | `influxdb3_catalog/src/resource.rs` | verified |  |
| grafana | `public/app/plugins/panel/histogram/config.ts` | verified |  |
| prysm | `testing/spectest/mainnet/deneb__epoch_processing__historical_summaries_update_test.go` | verified |  |
| influxdb | `core/iox_query/src/chunk_statistics.rs` | verified |  |
| influxdb | `core/trace_exporters/src/thrift/jaeger.rs` | verified |  |
