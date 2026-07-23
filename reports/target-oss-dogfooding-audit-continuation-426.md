# Target OSS no-LLM dogfooding audit — continuation 426 (batch 427)

Run: 2026-07-23T01:49:38.215303+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `misc/go_android_exec/exitcode_test.go` | verified |  |
| go | `misc/go_android_exec/main.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/rewriteRISCV64.go` | verified |  |
| go | `src/crypto/ecdsa/ecdsa_test.go` | verified |  |
| go | `src/encoding/asn1/common.go` | verified |  |
| go | `src/net/http/httptest/server_test.go` | verified |  |
| go | `src/os/wait6_freebsd64.go` | verified |  |
| go | `src/runtime/env_test.go` | verified |  |
| go | `src/runtime/pprof/elf.go` | verified |  |
| go | `src/syscall/ztypes_freebsd_amd64.go` | verified |  |
| go | `test/ddd1.go` | verified |  |
| go | `test/escape_field.go` | verified |  |
| go | `test/fixedbugs/bug219.go` | verified |  |
| go | `test/fixedbugs/issue10407.go` | verified |  |
| go | `test/fixedbugs/issue10977.go` | verified |  |
| go | `test/fixedbugs/issue13268.go` | verified |  |
| go | `test/fixedbugs/issue22962.go` | verified |  |
| go | `test/fixedbugs/issue30956.go` | verified |  |
| go | `test/fixedbugs/issue4752.go` | verified |  |
| go | `test/import4.dir/import4.go` | verified |  |
| go | `test/typeparam/typeswitch6.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/plugincheck/update_step.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/alerting/v0alpha1/rulesequence_schema_gen.go` | verified |  |
| grafana | `apps/folder/pkg/apis/folder/v1beta1/folder.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1beta1/logsdrilldowndefaultlabels_status_gen.go` | verified |  |
| grafana | `apps/plugins/plugin/src/generated/meta/v0alpha1/types.status.gen.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/migrate-to-cloud/index.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/quotas/v0alpha1/baseAPI.ts` | verified |  |
| grafana | `packages/grafana-data/src/utils/throwIfAngular.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Link/Link.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Slider/HandleTooltip.tsx` | verified |  |
| grafana | `pkg/middleware/dashboard_redirect_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/legacy/team.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/informer/repository.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/progress.go` | verified |  |
| grafana | `pkg/registry/apis/secret/contracts/encryption.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/k8s_adapter_test.go` | verified |  |
| grafana | `pkg/services/apiserver/utils/clientConfig.go` | verified |  |
| grafana | `pkg/services/ngalert/models/alert_rule.go` | verified |  |
| grafana | `pkg/services/quota/quotaimpl/quota_test.go` | verified |  |
| grafana | `pkg/storage/secret/metadata/keeper_model.go` | verified |  |
| grafana | `pkg/storage/unified/resource/gc_gate.go` | verified |  |
| grafana | `public/app/core/navigation/hooks.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/contact-points/ContactPointHeader.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/usePreviewTemplate.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/utils/DraggableManager/EUpdateTypes.tsx` | verified |  |
| grafana | `public/app/features/gops/configuration-tracker/irmHooks.ts` | verified |  |
| grafana | `public/app/features/panel/components/VizTypePicker/VisualizationCardGrid.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/jaeger/components/QueryEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/tracking.ts` | verified |  |
