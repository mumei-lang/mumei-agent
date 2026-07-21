# Target OSS no-LLM dogfooding audit — continuation 100 (batch 101)

Run: 2026-07-21T23:56:18.198867+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification after one agent-side heuristic fix.

- Go parameters named ``call`` (a Mumei reserved keyword) are now renamed to ``call_`` in generated atoms, and nil-dereference preconditions/contract text use the safe identifier.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| prysm | `testing/spectest/minimal/bellatrix__epoch_processing__registry_updates_test.go` | verified |  |
| prysm | `beacon-chain/p2p/fork.go` | verified |  |
| grafana | `public/app/core/utils/richHistory.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/types/hooks.ts` | verified |  |
| influxdb | `core/jemalloc_pprof_http/tests/pprof_heap_response.rs` | verified |  |
| go | `src/go/types/util.go` | verified |  |
| prysm | `config/params/testnet_sepolia_config.go` | verified |  |
| grafana | `pkg/infra/usagestats/mock.go` | verified |  |
| grafana | `pkg/services/supportbundles/supportbundlesimpl/collectors.go` | verified |  |
| influxdb | `core/trace_exporters/src/rate_limiter.rs` | verified |  |
| grafana | `public/app/core/components/Theme/ThemePreview.tsx` | verified |  |
| prysm | `beacon-chain/core/electra/transition.go` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useTemplateAutofill.ts` | verified |  |
| grafana | `pkg/server/service.go` | verified |  |
| go | `src/internal/runtime/syscall/linux/defs_linux_arm64.go` | verified |  |
| grafana | `public/app/features/connections/pages/DataSourcesListPage.tsx` | verified |  |
| go | `src/go/token/serialize.go` | verified |  |
| influxdb | `core/trogging/src/lib.rs` | verified |  |
| go | `test/fixedbugs/issue58293.go` | verified |  |
| prysm | `testing/spectest/shared/phase0/operations/proposer_slashing.go` | verified |  |
| prysm | `consensus-types/primitives/committee_index.go` | verified |  |
| influxdb | `core/service_common/src/error.rs` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/repository_resources_factory_mock.go` | verified |  |
| go | `src/internal/coverage/rtcov/rtcov.go` | verified |  |
| go | `src/os/executable_test.go` | verified |  |
| go | `src/cmd/go/internal/toolchain/select.go` | verified |  |
| prysm | `testing/spectest/mainnet/bellatrix__operations__execution_payload_test.go` | verified |  |
| influxdb | `core/backoff/src/lib.rs` | verified |  |
| prysm | `beacon-chain/p2p/doc.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/installsync/installsyncfakes/fakes.go` | verified |  |
| grafana | `public/app/core/trustedTypePolicies.ts` | verified |  |
| go | `src/os/signal/signal_test.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/dataSource/pluginCache.ts` | verified |  |
| grafana | `pkg/services/correlations/database.go` | verified |  |
| influxdb | `influxdb3_catalog/src/object_store/versions/v2.rs` | verified |  |
| go | `src/internal/syscall/unix/at_libc.go` | verified |  |
| prysm | `testing/spectest/mainnet/gloas__operations__voluntary_exit_test.go` | verified |  |
| influxdb | `core/iox_query_influxql/src/plan/util.rs` | verified |  |
| grafana | `pkg/registry/apis/provisioning/test_test.go` | verified |  |
| prysm | `beacon-chain/db/kv/state_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/filter/RulesFilter.v2.tsx` | verified |  |
| grafana | `public/app/features/live/centrifuge/service.ts` | verified |  |
| influxdb | `influxdb3_commands/src/lib.rs` | verified |  |
| go | `src/go/types/typeterm.go` | verified |  |
| influxdb | `core/iox_query/src/physical_optimizer/dedup/dedup_null_columns.rs` | verified |  |
| go | `src/net/writev_unix.go` | verified |  |
| influxdb | `core/data_types/src/partition.rs` | verified |  |
| prysm | `validator/db/kv/genesis.go` | verified |  |
| go | `test/fixedbugs/issue75022.go` | verified |  |
| go | `src/os/file_open_wasip1.go` | verified |  |
