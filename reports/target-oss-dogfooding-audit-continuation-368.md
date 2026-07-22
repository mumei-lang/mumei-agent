# Target OSS no-LLM dogfooding audit — continuation 368 (batch 369)

Run: 2026-07-22T22:15:11.567334+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue43639/a.go` | verified |  |
| go | `src/cmd/compile/internal/types2/importer_test.go` | verified |  |
| go | `src/cmd/compile/internal/types2/under.go` | verified |  |
| go | `src/encoding/json/internal/internal.go` | verified |  |
| go | `src/go/ast/commentmap_test.go` | verified |  |
| go | `src/go/printer/printer.go` | verified |  |
| go | `src/internal/syscall/unix/fcntl_js.go` | verified |  |
| go | `src/internal/testenv/testenv_test.go` | verified |  |
| go | `src/log/slog/example_discard_test.go` | verified |  |
| go | `src/net/http/cookiejar/punycode.go` | verified |  |
| go | `src/net/sock_cloexec.go` | verified |  |
| go | `src/os/dirent_netbsd.go` | verified |  |
| go | `src/os/exec/lp_windows.go` | verified |  |
| go | `src/runtime/signal_freebsd_arm.go` | verified |  |
| go | `src/simd/archsimd/ops_emulated_amd64.go` | verified |  |
| go | `test/fixedbugs/issue15548.go` | verified |  |
| go | `test/fixedbugs/issue49282.go` | verified |  |
| go | `test/fixedbugs/issue7310.go` | verified |  |
| go | `test/known_bits.go` | verified |  |
| go | `test/syntax/semi3.go` | verified |  |
| go | `test/typeparam/dictionaryCapture-noinline.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/app/validation/openapi_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/v1beta1_to_v2.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v6_test.go` | verified |  |
| grafana | `packages/grafana-alerting/src/internal.ts` | verified |  |
| grafana | `packages/grafana-data/src/panel/PanelPlugin.ts` | verified |  |
| grafana | `packages/grafana-data/src/utils/deprecationWarning.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/TimeSyncButton.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Sparkline/utils.ts` | verified |  |
| grafana | `pkg/api/apierrors/folder_test.go` | verified |  |
| grafana | `pkg/registry/apis/preferences/utils/names_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/extra.go` | verified |  |
| grafana | `pkg/registry/apis/secret/inline/service.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/postgres_tags.go` | verified |  |
| grafana | `pkg/registry/apps/shorturl/migrator/migrator.go` | verified |  |
| grafana | `pkg/services/authn/authnimpl/sync/user_sync_test.go` | verified |  |
| grafana | `pkg/services/live/pipeline/frame_processor_keep_field.go` | verified |  |
| grafana | `pkg/services/oauthtoken/oauthtokentest/service_mock.go` | verified |  |
| grafana | `pkg/storage/unified/resource/lease/metrics.go` | verified |  |
| grafana | `pkg/tsdb/loki/api.go` | verified |  |
| grafana | `pkg/util/debouncer/queue_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/contact-points/useContactPoints.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/PermissionsEditView.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/version-history/DiffGroup.tsx` | verified |  |
| grafana | `public/app/features/plugins/extensions/useLoadAppPlugins.tsx` | verified |  |
| grafana | `public/app/features/plugins/loader/pluginInfoCache.ts` | verified |  |
| grafana | `public/app/features/provisioning/components/Dashboards/OrphanedDashboardBanner.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/components/TagEditor.tsx` | verified |  |
| grafana | `public/app/types/intl.d.ts` | verified |  |
| grafana | `public/test/mocks/style.ts` | verified |  |
