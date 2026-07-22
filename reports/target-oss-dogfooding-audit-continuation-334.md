# Target OSS no-LLM dogfooding audit — continuation 334 (batch 335)

Run: 2026-07-22T20:20:17.271471+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue52611.go` | verified |  |
| go | `src/compress/flate/deflate.go` | verified |  |
| go | `src/encoding/json/v2_decode.go` | verified |  |
| go | `src/internal/cpu/cpu_riscv64.go` | verified |  |
| go | `src/net/tcpsock_solaris.go` | verified |  |
| go | `src/runtime/mgcmark.go` | verified |  |
| go | `src/runtime/retry.go` | verified |  |
| go | `test/fixedbugs/issue13539.go` | verified |  |
| go | `test/fixedbugs/issue29362b.go` | verified |  |
| go | `test/fixedbugs/issue44335.go` | verified |  |
| go | `test/fixedbugs/issue79274a.go` | verified |  |
| go | `test/fixedbugs/issue79812.go` | verified |  |
| go | `test/recover1.go` | verified |  |
| grafana | `apps/correlations/pkg/apis/correlation/v0alpha1/correlation_codec_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2/validation.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/getsearchusers_request_params_types_gen.go` | verified |  |
| grafana | `apps/live/pkg/apis/live/v1alpha1/getsomething_response_body_types_gen.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/api/notifications/v0alpha1/types.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/joinDataFrames.ts` | verified |  |
| grafana | `pkg/apiserver/endpoints/filters/jaeger_tracing.go` | verified |  |
| grafana | `pkg/infra/metrics/graphitebridge/graphite.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/snapshot/conversions_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/retry_client.go` | verified |  |
| grafana | `pkg/registry/apis/query/errors.go` | verified |  |
| grafana | `pkg/registry/apis/secret/decrypt/grpc_client.go` | verified |  |
| grafana | `pkg/registry/apis/secret/decrypt/service.go` | verified |  |
| grafana | `pkg/services/cloudmigration/api/api_test.go` | verified |  |
| grafana | `pkg/services/dashboards/dashboard_provisioning_mock.go` | verified |  |
| grafana | `pkg/services/featuremgmt/openfeature_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pipeline/steps_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginconfig/azure_settings_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/db/migrations/migrator.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/mute-timings/useExportMuteTimingsDrawer.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/abilities/alertmanager/useSilenceAbility.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/configure/admin_config.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/handlers/alertNotifiers.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/inspect/PanelInspectDrawer.tsx` | verified |  |
| grafana | `public/app/features/query/state/PanelQueryRunner.ts` | verified |  |
| grafana | `public/app/features/scopes/selector/useScopesApi.ts` | verified |  |
| grafana | `scripts/cli/themeTemplates/generatedFileBanner.ts` | verified |  |
| prysm | `beacon-chain/cache/attestation_data.go` | verified |  |
| prysm | `beacon-chain/core/helpers/shuffle_test.go` | verified |  |
| prysm | `beacon-chain/db/pruner/pruner_test.go` | verified |  |
| prysm | `beacon-chain/forkchoice/types/types.go` | verified |  |
| prysm | `beacon-chain/sync/rate_limiter.go` | verified |  |
| prysm | `config/params/fork_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/electra__operations__execution_payload_test.go` | verified |  |
| prysm | `testing/util/sync_committee.go` | verified |  |
| prysm | `tools/analyzers/modernize/reflecttypefor/analyzer.go` | verified |  |
| prysm | `validator/client/beacon-api/get_beacon_block_test.go` | verified |  |
