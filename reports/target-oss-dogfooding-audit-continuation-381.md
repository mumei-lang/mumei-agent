# Target OSS no-LLM dogfooding audit — continuation 381 (batch 382)

Run: 2026-07-22T23:39:24.391375+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/checkbce.go` | verified |  |
| go | `src/encoding/json/internal/jsonflags/flags.go` | verified |  |
| go | `src/encoding/json/internal/jsontest/testcase.go` | verified |  |
| go | `src/net/mptcpsock_stub.go` | verified |  |
| go | `src/runtime/debuglog_test.go` | verified |  |
| go | `src/runtime/malloc.go` | verified |  |
| go | `src/runtime/signal_solaris_amd64.go` | verified |  |
| go | `src/runtime/vdso_freebsd_riscv64.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/shift_amd64_test.go` | verified |  |
| go | `test/convT2X.go` | verified |  |
| go | `test/fixedbugs/bug040.go` | verified |  |
| go | `test/fixedbugs/bug414.dir/prog.go` | verified |  |
| go | `test/fixedbugs/bug504.go` | verified |  |
| go | `test/fixedbugs/issue44355.go` | verified |  |
| go | `test/fixedbugs/issue47771.go` | verified |  |
| go | `test/fixedbugs/issue51839.go` | verified |  |
| go | `test/reflectmethod8.go` | verified |  |
| go | `test/typeparam/issue47797.go` | verified |  |
| grafana | `apps/annotation/plugin/src/generated/annotation/v0alpha1/annotation_object_gen.ts` | verified |  |
| grafana | `apps/preferences/pkg/apis/preferences/v1alpha1/preferences.go` | verified |  |
| grafana | `apps/secret/inline/v1beta1/inline.pb.go` | verified |  |
| grafana | `apps/shorturl/pkg/apis/shorturl/v1beta1/shorturl_object_gen.go` | verified |  |
| grafana | `e2e-playwright/plugin-e2e/plugin-e2e-api-tests/errors.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/user/index.ts` | verified |  |
| grafana | `packages/grafana-o11y-ds-frontend/src/TemporaryAlert.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/RadioButtonList/RadioButtonList.tsx` | verified |  |
| grafana | `pkg/api/quota_test.go` | verified |  |
| grafana | `pkg/bus/bus_test.go` | verified |  |
| grafana | `pkg/login/social/connectors/github_oauth.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/move/worker_test.go` | verified |  |
| grafana | `pkg/registry/apis/secret/encryption/cipher/provider/errors.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/rules/rulesequence/type.go` | verified |  |
| grafana | `pkg/services/accesscontrol/acimpl/service_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/database/externalservices.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/zanzana.go` | verified |  |
| grafana | `pkg/services/hooks/hooks.go` | verified |  |
| grafana | `pkg/services/rendering/rendering.go` | verified |  |
| grafana | `pkg/storage/unified/search/vector/integration_test.go` | verified |  |
| grafana | `public/app/core/services/backend_srv.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/api/alertingApi.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/enterprise-components/AI/AIGenAlertRuleButton/addAIAlertRuleButton.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/scene/filters/severity.ts` | verified |  |
| grafana | `public/app/features/connections/pages/InsightsFeatureHighlightPage.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Sidebar/DraggableList/useSidebarDragAndDrop.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/new-toolbar/actions/MakeDashboardEditableButton.tsx` | verified |  |
| grafana | `public/app/features/explore/extensions/toolbar/BasicExtensions.tsx` | verified |  |
| grafana | `public/app/features/logs/components/fieldSelector/LogListFieldSelector.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/configuration/parseLokiLabelMappings.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/query/influxql/visual/FormatAsSection.tsx` | verified |  |
| grafana | `scripts/codeowners-manifest/generate.js` | verified |  |
