# Target OSS no-LLM dogfooding audit — continuation 271 (batch 272)

Run: 2026-07-22T16:08:53.032629+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification after fixing Go index and divisor guards.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ir/symtab.go` | verified |  |
| go | `src/cmd/compile/internal/test/ssa_test.go` | verified |  |
| go | `src/cmd/link/internal/arm64/asm.go` | verified |  |
| go | `src/cmd/link/internal/ld/macho.go` | verified |  |
| go | `src/crypto/internal/fips140/subtle/xor_loong64.go` | verified |  |
| go | `src/image/names.go` | verified |  |
| go | `src/internal/poll/read_test.go` | verified |  |
| go | `src/internal/runtime/atomic/atomic_riscv64.go` | verified |  |
| go | `src/internal/syscall/unix/at_sysnum_fstatat_linux.go` | verified |  |
| go | `src/net/dnsclient.go` | verified |  |
| go | `src/os/wait_unimp.go` | verified |  |
| go | `test/fixedbugs/issue20333.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/configchecks/security_config_step_test.go` | verified |  |
| grafana | `apps/dashboard/tshack/v0alpha1_spec_gen.ts` | verified |  |
| grafana | `apps/logsdrilldown/plugin/src/generated/logsdrilldown/v1alpha1/types.metadata.gen.ts` | verified |  |
| grafana | `packages/grafana-data/rollup.config.ts` | verified |  |
| grafana | `packages/grafana-data/typings/jest/index.d.ts` | verified |  |
| grafana | `packages/grafana-flamegraph/.storybook/preview.ts` | verified |  |
| grafana | `packages/grafana-flamegraph/src/TopTable/FlameGraphTopTableContainer.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Portal/Portal.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Select/SelectMenu.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/themes/GlobalStyles/uPlot.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/uniqueId.ts` | verified |  |
| grafana | `pkg/api/frontendlogging/grafana_javascript_agent_sourcemaps.go` | verified |  |
| grafana | `pkg/expr/mathexp/exp_memory_limit_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/repository_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/resourcepermissions/api_test.go` | verified |  |
| grafana | `pkg/services/ngalert/ngalert_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/v1/templates.go` | verified |  |
| grafana | `pkg/services/sqlstore/database_config.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/ualert/migration_service_migration.go` | verified |  |
| grafana | `pkg/tests/apis/alerting/notifications/timeinterval/imported_test.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/fsql/query_model.go` | verified |  |
| grafana | `pkg/util/xorm/session_context.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/state-history/common.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/state-history/numberFormatter.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/silences/SilenceViewPage.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/abilities/rules/ruleAbilities.utils.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/TransformationsEditor/SqlExpressions/SqlExpressionsBanner.tsx` | verified |  |
| grafana | `public/app/plugins/panel/geomap/editor/VariableNameEditor.tsx` | verified |  |
| prysm | `beacon-chain/p2p/testing/p2p.go` | verified |  |
| prysm | `beacon-chain/sync/backfill/service_test.go` | verified |  |
| prysm | `beacon-chain/sync/decode_pubsub_test.go` | verified |  |
| prysm | `beacon-chain/sync/rpc_light_client_test.go` | verified |  |
| prysm | `runtime/debug/cgo_symbolizer.go` | verified |  |
| prysm | `testing/spectest/mainnet/capella__operations__voluntary_exit_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/phase0__epoch_processing__slashings_test.go` | verified |  |
| prysm | `testing/spectest/shared/fulu/epoch_processing/registry_updates.go` | verified |  |
| prysm | `validator/client/beacon-api/log.go` | verified |  |
| prysm | `validator/web/doc.go` | verified |  |
