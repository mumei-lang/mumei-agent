# Target OSS no-LLM dogfooding audit — continuation 309 (batch 310)

Run: 2026-07-22T18:43:40.015444+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/covdata/export_test.go` | verified |  |
| go | `src/cmd/nm/nm_cgo_test.go` | verified |  |
| go | `src/crypto/internal/impl/impl.go` | verified |  |
| go | `src/hash/crc64/crc64.go` | verified |  |
| go | `src/internal/reflectlite/set_test.go` | verified |  |
| go | `src/net/internal/socktest/sys_unix.go` | verified |  |
| go | `src/net/tcpsock_posix.go` | verified |  |
| go | `src/os/root_openat.go` | verified |  |
| go | `src/time/abs_test.go` | verified |  |
| go | `src/time/format_test.go` | verified |  |
| go | `test/fixedbugs/issue32922.go` | verified |  |
| go | `test/typeparam/issue49421.go` | verified |  |
| go | `test/typeparam/issue50485.dir/a.go` | verified |  |
| go | `test/typeparam/issue51250a.dir/main.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/receiver_ext.go` | verified |  |
| grafana | `apps/plugins/pkg/apis/plugins/v0alpha1/meta_client_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/githubconnectionconfig.go` | verified |  |
| grafana | `apps/provisioning/pkg/quotas/quotas.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/github/extra_test.go` | verified |  |
| grafana | `packages/grafana-data/test/helpers/fieldConfig.ts` | verified |  |
| grafana | `packages/grafana-flamegraph/src/FlameGraph/dataTransform.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/ClickOutsideWrapper/ClickOutsideWrapper.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/DateTimePicker/DateTimePicker.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizLegend/VizLegendTableItem.tsx` | verified |  |
| grafana | `pkg/apiserver/endpoints/filters/tracing_log_test.go` | verified |  |
| grafana | `pkg/infra/fs/copy.go` | verified |  |
| grafana | `pkg/registry/apis/secret/contracts/migrator.go` | verified |  |
| grafana | `pkg/registry/apps/playlist/conversions.go` | verified |  |
| grafana | `pkg/services/accesscontrol/noop_globalrole_seeder.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/azuremonitor-resource-handler_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/services/hardcoded_metrics_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/form/fields/DeletedSubform.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/dashboard/DashboardEditableElement.tsx` | verified |  |
| grafana | `public/app/features/gops/configuration-tracker/components/ProgressBar.tsx` | verified |  |
| grafana | `public/app/features/logs/UniqueKeyMaker.ts` | verified |  |
| grafana | `public/app/features/transformers/editors/CalculateFieldTransformerEditor/CalculateFieldTransformerEditor.tsx` | verified |  |
| grafana | `public/app/features/transformers/extractFields/components/JSONPathEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/datasource.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/AnnotationQueryRunner.ts` | verified |  |
| prysm | `beacon-chain/core/gloas/attestation_test.go` | verified |  |
| prysm | `beacon-chain/core/gloas/pending_payment_test.go` | verified |  |
| prysm | `beacon-chain/core/requests/deposits_test.go` | verified |  |
| prysm | `beacon-chain/node/registration/p2p.go` | verified |  |
| prysm | `beacon-chain/state/state-native/getters_exit.go` | verified |  |
| prysm | `crypto/hash/htr/log.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/attestation/aggregation/attestations/export_test.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/blobs.pb.go` | verified |  |
| prysm | `testing/spectest/shared/gloas/operations/payload_attestation.go` | verified |  |
| prysm | `testing/spectest/utils/config.go` | verified |  |
| prysm | `testing/util/block.go` | verified |  |
