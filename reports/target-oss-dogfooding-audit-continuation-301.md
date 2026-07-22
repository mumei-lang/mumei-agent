# Target OSS no-LLM dogfooding audit — continuation 301 (batch 302)

Run: 2026-07-22T18:17:39.687356+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/bytes/iter.go` | verified |  |
| go | `src/crypto/internal/boring/sig/sig.go` | verified |  |
| go | `src/crypto/internal/fips140test/xaes_test.go` | verified |  |
| go | `src/crypto/subtle/xor.go` | verified |  |
| go | `src/fmt/gostringer_example_test.go` | verified |  |
| go | `src/fmt/print.go` | verified |  |
| go | `src/internal/runtime/gc/sizeclasses.go` | verified |  |
| go | `src/internal/runtime/syscall/linux/defs_linux_mips64x.go` | verified |  |
| go | `src/math/asin.go` | verified |  |
| go | `src/runtime/signal_freebsd_amd64.go` | verified |  |
| go | `src/syscall/time_fake.go` | verified |  |
| go | `test/chan/powser2.go` | verified |  |
| go | `test/internal/runtime/sys/inlinegcpc.go` | verified |  |
| go | `test/ken/interbasic.go` | verified |  |
| grafana | `packages/grafana-data/src/dataframe/CircularDataFrame.ts` | verified |  |
| grafana | `packages/grafana-data/src/field/fieldOverrides.ts` | verified |  |
| grafana | `pkg/apimachinery/errutil/doc.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/connection_health_test.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/historian/register.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/search_handler_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/dualwrite/resource_reconciler_orphan_test.go` | verified |  |
| grafana | `pkg/services/dashboardsnapshots/database/database_test.go` | verified |  |
| grafana | `pkg/services/encryption/provider/decipher_aes_test.go` | verified |  |
| grafana | `pkg/services/ngalert/store/admin_configuration_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/coreplugin/coreplugins.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/migrations.go` | verified |  |
| grafana | `pkg/services/sqlstore/user_test.go` | verified |  |
| grafana | `pkg/storage/secret/encryption/encrypted_value_store.go` | verified |  |
| grafana | `pkg/storage/unified/apistore/util.go` | verified |  |
| grafana | `pkg/storage/unified/client_retry.go` | verified |  |
| grafana | `public/app/core/navigation/mocks/routeProps.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useFilteredRules.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/conditional-rendering/group/ConditionalRenderingGroupVisibility.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/editors/CustomVariableEditor/PaneItem.tsx` | verified |  |
| grafana | `public/app/features/explore/CustomContainer.tsx` | verified |  |
| grafana | `public/app/features/explore/Logs/LogsTableActionButtons.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/utils/service-name.ts` | verified |  |
| grafana | `public/app/features/explore/spec/helper/mocks.ts` | verified |  |
| grafana | `public/app/plugins/panel/alertlist/UnifiedAlertList.tsx` | verified |  |
| grafana | `public/app/plugins/panel/heatmap/palettes.ts` | verified |  |
| prysm | `beacon-chain/cache/committee.go` | verified |  |
| prysm | `beacon-chain/db/kv/p2p.go` | verified |  |
| prysm | `beacon-chain/db/kv/p2p_test.go` | verified |  |
| prysm | `beacon-chain/sync/pending_blocks_queue.go` | verified |  |
| prysm | `cmd/prysmctl/checkpointsync/cmd.go` | verified |  |
| prysm | `cmd/prysmctl/validator/log.go` | verified |  |
| prysm | `proto/eth/v1/node.pb.go` | verified |  |
| prysm | `testing/endtoend/helpers/epochTimer.go` | verified |  |
| prysm | `tools/analyzers/cryptorand/analyzer.go` | verified |  |
| prysm | `validator/keymanager/local/backup_test.go` | verified |  |
