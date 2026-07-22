# Target OSS no-LLM dogfooding audit — continuation 273 (batch 274)

Run: 2026-07-22T16:19:37.145316+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification after treating *Block receivers as non-nil.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/archive/tar/common.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/block.go` | verified |  |
| go | `src/cmd/go/internal/toolchain/path_unix.go` | verified |  |
| go | `src/crypto/md5/md5block_decl.go` | verified |  |
| go | `src/html/template/css.go` | verified |  |
| go | `src/internal/goarch/goarch_loong64.go` | verified |  |
| go | `src/internal/msan/doc.go` | verified |  |
| go | `src/net/http/httptrace/example_test.go` | verified |  |
| go | `src/net/udpsock_test.go` | verified |  |
| go | `test/fixedbugs/bug096.go` | verified |  |
| go | `test/fixedbugs/bug155.go` | verified |  |
| go | `test/fixedbugs/bug430.go` | verified |  |
| go | `test/fixedbugs/gcc61244.go` | verified |  |
| go | `test/fixedbugs/issue49122.go` | verified |  |
| go | `test/fixedbugs/issue50439.go` | verified |  |
| go | `test/fixedbugs/issue8947.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/routingtree_codec_gen.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/routingtree_schema_gen.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/alerting/v0alpha1/createsearchrules_response_object_types_gen.go` | verified |  |
| grafana | `apps/collections/pkg/apis/collections/v1alpha1/register.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2alpha1/zz_generated.openapi.go` | verified |  |
| grafana | `apps/preferences/pkg/apis/preferences/v1/preferences_schema_gen.go` | verified |  |
| grafana | `pkg/cmd/grafana-cli/utils/args_mock.go` | verified |  |
| grafana | `pkg/infra/usagestats/statscollector/prometheus_flavor_test.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/k8s_adapter.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/receiver_svc_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/tls_mysql.go` | verified |  |
| grafana | `pkg/storage/unified/migrations/testcases/folders_dashboards.go` | verified |  |
| grafana | `pkg/storage/unified/resource/notifier_nats.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/time/time-grain_test.go` | verified |  |
| grafana | `public/app/features/browse-dashboards/permissions.ts` | verified |  |
| grafana | `public/app/features/logs/components/infiniteScrollUtils.ts` | verified |  |
| grafana | `public/app/features/provisioning/utils/sourceLink.ts` | verified |  |
| grafana | `public/app/features/query/components/QueryGroupOptions.tsx` | verified |  |
| grafana | `public/app/features/search/types.ts` | verified |  |
| grafana | `public/app/features/teams/hooks.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/migrations/metricQueryMigrations.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/config/InfluxFluxConfig.tsx` | verified |  |
| grafana | `public/app/plugins/panel/gettingstarted/components/TutorialCard.tsx` | verified |  |
| prysm | `beacon-chain/core/feed/event.go` | verified |  |
| prysm | `cmd/prysmctl/p2p/p2p.go` | verified |  |
| prysm | `contracts/deposit/deposit_contract.sol` | verified |  |
| prysm | `proto/engine/v1/engine.minimal.ssz.go` | verified |  |
| prysm | `runtime/interop/generate_genesis_state_bellatrix.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__epoch_processing__registry_updates_test.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__operations__withdrawals_test.go` | verified |  |
| prysm | `testing/spectest/minimal/phase0__epoch_processing__effective_balance_updates_test.go` | verified |  |
| prysm | `testing/spectest/shared/bellatrix/sanity/slot_processing.go` | verified |  |
| prysm | `testing/spectest/shared/fulu/sanity/block_processing.go` | verified |  |
| prysm | `validator/db/kv/migration_source_target_epochs_bucket_test.go` | verified |  |
