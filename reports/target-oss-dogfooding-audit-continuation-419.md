# Target OSS no-LLM dogfooding audit — continuation 419 (batch 420)

Run: 2026-07-23T01:27:39.295395+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/syntax/parser.go` | verified |  |
| go | `src/cmd/compile/internal/typecheck/subr.go` | verified |  |
| go | `src/cmd/internal/obj/riscv/asm_test.go` | verified |  |
| go | `src/crypto/internal/fips140/ecdh/ecdh.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/p224_sqrt.go` | verified |  |
| go | `src/crypto/rsa/rsa_wycheproof_test.go` | verified |  |
| go | `src/encoding/json/number_test.go` | verified |  |
| go | `src/encoding/json/v2/errors_test.go` | verified |  |
| go | `src/net/http/internal/http2/flow.go` | verified |  |
| go | `src/net/tcpconn_keepalive_posix_test.go` | verified |  |
| go | `src/runtime/defs_illumos_amd64.go` | verified |  |
| go | `src/syscall/syscall_freebsd_arm64.go` | verified |  |
| go | `src/syscall/syscall_windows_test.go` | verified |  |
| go | `test/dwarf/dwarf.dir/z9.go` | verified |  |
| go | `test/fixedbugs/issue26163.go` | verified |  |
| go | `test/fixedbugs/issue32922.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue43962.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue4734.go` | verified |  |
| go | `test/fixedbugs/issue54912.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue5957.dir/c.go` | verified |  |
| go | `test/interface/embed3.dir/embed1.go` | verified |  |
| go | `test/ken/cplx1.go` | verified |  |
| go | `test/typeparam/issue48049.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/instancechecks/out_of_support_step.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/errors.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/listers/provisioning/v0alpha1/expansion_generated.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/testIds.ts` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/newgauge/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/types/icon.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/DelayRender.tsx` | verified |  |
| grafana | `pkg/apiserver/endpoints/filters/requester.go` | verified |  |
| grafana | `pkg/registry/apis/iam/authorizer/resource_permissions_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/accesscontrol.go` | verified |  |
| grafana | `pkg/services/ngalert/api/tooling/definitions/convert_prometheus_api.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/ticker/metrics.go` | verified |  |
| grafana | `pkg/tests/api/alerting/api_ruler_pause_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/notifications/NotificationsListSceneObject.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/notifications/NotificationsRuntimeDataSource.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-notebook/cells/MarkdownCell.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/SharePublicDashboard/CreatePublicDashboard/CreatePublicDashboard.tsx` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/SeriesVisibilityConfigFactory.ts` | verified |  |
| grafana | `public/app/features/panel/suggestions/consts.ts` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/StepStatusContext.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/Shared/ProvisioningAwareFolderPicker.tsx` | verified |  |
| grafana | `public/app/features/transformers/standardTransformers.tsx` | verified |  |
| grafana | `public/app/features/variables/types.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/MetricsQueryEditor/LegendFormatField.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/querybuilder/components/QueryPatternsModal.tsx` | verified |  |
| grafana | `public/app/plugins/panel/geomap/layers/data/geojsonLayer.ts` | verified |  |
| grafana | `public/app/plugins/panel/test-utils.ts` | verified |  |
