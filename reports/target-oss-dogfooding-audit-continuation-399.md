# Target OSS no-LLM dogfooding audit — continuation 399 (batch 400)

Run: 2026-07-23T00:34:32.580207+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/buildid/doc.go` | verified |  |
| go | `src/cmd/internal/obj/x86/evex.go` | verified |  |
| go | `src/crypto/ecdh/x25519.go` | verified |  |
| go | `src/go/types/issues_test.go` | verified |  |
| go | `src/internal/cpu/cpu_arm64_android.go` | verified |  |
| go | `src/log/log.go` | verified |  |
| go | `src/net/http/internal/http2/clientconn_test.go` | verified |  |
| go | `src/net/http/internal/http2/server_push_test.go` | verified |  |
| go | `src/runtime/cgo.go` | verified |  |
| go | `src/runtime/cgo/mmap.go` | verified |  |
| go | `src/runtime/defs_freebsd_arm.go` | verified |  |
| go | `src/syscall/syscall_openbsd_ppc64.go` | verified |  |
| go | `test/fixedbugs/bug115.go` | verified |  |
| go | `test/fixedbugs/issue20780.go` | verified |  |
| go | `test/fixedbugs/issue27143.go` | verified |  |
| go | `test/fixedbugs/issue31060.go` | verified |  |
| go | `test/fixedbugs/issue33739.go` | verified |  |
| go | `test/fixedbugs/issue42568.go` | verified |  |
| go | `test/fixedbugs/issue6428.go` | verified |  |
| go | `test/fixedbugs/issue6703k.go` | verified |  |
| go | `test/typeparam/sliceimp.dir/a.go` | verified |  |
| grafana | `packages/grafana-i18n/src/languages.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/components/DataSourcePicker.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/uPlot/plugins/KeyboardPlugin.tsx` | verified |  |
| grafana | `pkg/cmd/grafana-cli/commands/secretsconsolidation/secretsconsolidation.go` | verified |  |
| grafana | `pkg/registry/apis/iam/globalrole/inmemory/api_installer.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/dualwriter_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/resourcepermissions/service_test.go` | verified |  |
| grafana | `pkg/services/authn/clients/form.go` | verified |  |
| grafana | `pkg/services/grpcserver/interceptors/service_identity_test.go` | verified |  |
| grafana | `pkg/services/licensing/licensingtest/fake.go` | verified |  |
| grafana | `pkg/services/live/pipeline/config.go` | verified |  |
| grafana | `pkg/services/ngalert/api/api_configuration_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/silences.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/jitter_test.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/public_dashboard_middleware_mock.go` | verified |  |
| grafana | `pkg/tests/apis/alerting/notifications/inhibitionrule/imported_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/fixfoldermetadata_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/quota/namespace_quota_test.go` | verified |  |
| grafana | `pkg/util/json_test.go` | verified |  |
| grafana | `pkg/web/router.go` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/grafana/MissedIterationsScene.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-rows/RowItemsEditor.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/VariableStaticOptionsFormAddButton.tsx` | verified |  |
| grafana | `public/app/features/explore/RecentQueries/filterDefaults.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/SpanBar.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/Stepper.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/components/ErrorWithSourceEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/querySplitting.ts` | verified |  |
| grafana | `public/app/plugins/panel/flamegraph/FlameGraphPanel.tsx` | verified |  |
