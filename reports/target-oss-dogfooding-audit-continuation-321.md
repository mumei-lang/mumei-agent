# Target OSS no-LLM dogfooding audit — continuation 321 (batch 322)

Run: 2026-07-22T19:33:39.887594+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/expand_calls.go` | verified |  |
| go | `src/cmd/link/internal/ld/msync_darwin_libc.go` | verified |  |
| go | `src/debug/dwarf/unit.go` | verified |  |
| go | `src/debug/macho/reloctype_string.go` | verified |  |
| go | `src/internal/poll/splice_linux.go` | verified |  |
| go | `src/internal/runtime/gc/scan/scan_reference.go` | verified |  |
| go | `src/net/http/internal/http2/ascii.go` | verified |  |
| go | `src/runtime/signal_amd64.go` | verified |  |
| go | `src/strings/reader.go` | verified |  |
| go | `src/syscall/zsyscall_netbsd_amd64.go` | verified |  |
| go | `test/fixedbugs/bug152.go` | verified |  |
| go | `test/fixedbugs/bug324.go` | verified |  |
| go | `test/fixedbugs/issue35027.go` | verified |  |
| go | `test/typeparam/issue50481c.dir/main.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/datasourcecheck/uid_validation_step.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/client_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/migrations_test.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam_manifest.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/generator/clientState.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/components/TableCellTooltip.tsx` | verified |  |
| grafana | `pkg/apimachinery/apis/common/v0alpha1/zz_generated.deepcopy.go` | verified |  |
| grafana | `pkg/apis/service/v0alpha1/zz_generated.openapi.go` | verified |  |
| grafana | `pkg/components/dashdiffs/formatter_test.go` | verified |  |
| grafana | `pkg/infra/kvstore/kvstore.go` | verified |  |
| grafana | `pkg/registry/apis/datasource/sub_proxy.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/alerts.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/alertmanager-entities/MuteTimingsSelector.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/grafana/InstanceStatusScene.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/scene/TriageSavedSearchesControl.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/constants.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Footer/QueryEditorFooter.tsx` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/fixtures/mswAPI.ts` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/onprem/resourceDependency.ts` | verified |  |
| grafana | `public/app/features/variables/datasource/adapter.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/logs/completion/suggestionKinds.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/migrations/variableQueryMigrations.ts` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/versions.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/query/QueryEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/gettingstarted/components/DocsCard.tsx` | verified |  |
| grafana | `public/test/setupTests.ts` | verified |  |
| prysm | `beacon-chain/builder/metric.go` | verified |  |
| prysm | `beacon-chain/execution/engine_client.go` | verified |  |
| prysm | `beacon-chain/forkchoice/doubly-linked-tree/errors.go` | verified |  |
| prysm | `beacon-chain/sync/pending_attestations_queue.go` | verified |  |
| prysm | `genesis/errors.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/health.pb.go` | verified |  |
| prysm | `validator/client/beacon-api/submit_signed_contribution_and_proof_test.go` | verified |  |
| prysm | `validator/client/log.go` | verified |  |
| prysm | `validator/db/filesystem/attester_protection_test.go` | verified |  |
| prysm | `validator/keymanager/local/errors.go` | verified |  |
