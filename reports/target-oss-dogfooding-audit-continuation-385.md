# Target OSS no-LLM dogfooding audit — continuation 385 (batch 386)

Run: 2026-07-22T23:52:22.579381+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/internal/goobj/objfile.go` | verified |  |
| go | `src/cmd/internal/obj/arm64/anames7.go` | verified |  |
| go | `src/crypto/sha1/sha1_test.go` | verified |  |
| go | `src/internal/runtime/atomic/linkname.go` | verified |  |
| go | `src/internal/syscall/unix/sysnum_freebsd.go` | verified |  |
| go | `src/internal/trace/internal/tracev1/parser.go` | verified |  |
| go | `src/math/big/natconv.go` | verified |  |
| go | `src/math/rand/v2/rand.go` | verified |  |
| go | `src/mime/type_windows.go` | verified |  |
| go | `src/net/http/http2.go` | verified |  |
| go | `src/runtime/sigaction.go` | verified |  |
| go | `src/runtime/vdso_freebsd_x86.go` | verified |  |
| go | `src/syscall/net_wasip1.go` | verified |  |
| go | `src/text/scanner/scanner.go` | verified |  |
| go | `test/codegen/smallintiface.go` | verified |  |
| go | `test/fixedbugs/bug460.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue24419.go` | verified |  |
| go | `test/fixedbugs/issue5260.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue6295.dir/p0.go` | verified |  |
| go | `test/fixedbugs/issue79186.go` | verified |  |
| go | `test/typeparam/aliasimp.go` | verified |  |
| go | `test/typeparam/issue51236.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/app/validation/openapi.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/metrics_test.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/folder/v1beta1/folderApiVersionResolver.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/CodeMirror/CodeEditor.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Combobox/types.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/RelativeTimeRangePicker/RelativeTimeRangePicker.tsx` | verified |  |
| grafana | `pkg/plugins/manager/pipeline/initialization/doc.go` | verified |  |
| grafana | `pkg/registry/apis/iam/serviceaccount/validate.go` | verified |  |
| grafana | `pkg/services/live/pipeline/converter_json_frame.go` | verified |  |
| grafana | `pkg/services/ngalert/sender/router.go` | verified |  |
| grafana | `pkg/services/ngalert/state/historian/core.go` | verified |  |
| grafana | `pkg/services/ngalert/store/admin_configuration.go` | verified |  |
| grafana | `pkg/services/notifications/codes.go` | verified |  |
| grafana | `pkg/services/preference/prefapi/k8s_client.go` | verified |  |
| grafana | `pkg/services/preference/preftest/fake.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/tabs/AlertVersionHistory.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/settings/ConfigurationDrawer.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/silences/SilenceGrafanaRuleDrawer.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/DeleteConfirm.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/PanelEditor/OptionsPaneItemDescriptor.tsx` | verified |  |
| grafana | `public/app/features/explore/hooks/useSplitSizeUpdater.ts` | verified |  |
| grafana | `public/app/features/plugins/admin/components/UpdateAllModalBody.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/jaeger/types.ts` | verified |  |
| grafana | `public/app/plugins/panel/bargauge/suggestions.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/editor/CoordinatesMapViewEditor.tsx` | verified |  |
| grafana | `public/app/types/apiKeys.ts` | verified |  |
| grafana | `public/app/types/window.d.ts` | verified |  |
| grafana | `stylelint.config.js` | verified |  |
