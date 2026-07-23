# Target OSS no-LLM dogfooding audit — continuation 478 (batch 479)

Run: 2026-07-23T05:17:54.227372+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue26430.go` | verified |  |
| go | `src/cmd/compile/internal/syntax/source.go` | verified |  |
| go | `src/cmd/internal/osinfo/os_solaris.go` | verified |  |
| go | `src/cmd/link/internal/arm/l.go` | verified |  |
| go | `src/cmd/trace/main_test.go` | verified |  |
| go | `src/cmd/trace/procgen.go` | verified |  |
| go | `src/crypto/internal/sysrand/rand_aix.go` | verified |  |
| go | `src/crypto/sha1/_asm/sha1block_amd64_shani.go` | verified |  |
| go | `src/crypto/x509/root_unix.go` | verified |  |
| go | `src/encoding/ascii85/ascii85_test.go` | verified |  |
| go | `src/go/version/version.go` | verified |  |
| go | `src/image/jpeg/dct.go` | verified |  |
| go | `src/internal/fuzz/mutator_test.go` | verified |  |
| go | `src/net/http/httputil/persist.go` | verified |  |
| go | `src/os/sys.go` | verified |  |
| go | `src/os/sys_bsd.go` | verified |  |
| go | `src/runtime/os2_aix.go` | verified |  |
| go | `src/runtime/signal_mipsx.go` | verified |  |
| go | `src/runtime/trace.go` | verified |  |
| go | `src/sync/rwmutex_test.go` | verified |  |
| go | `src/syscall/ztypes_solaris_amd64.go` | verified |  |
| go | `test/fixedbugs/bug051.go` | verified |  |
| go | `test/fixedbugs/bug440_32.go` | verified |  |
| go | `test/fixedbugs/issue33739.dir/b.go` | verified |  |
| grafana | `apps/advisor/pkg/apis/advisor/v0alpha1/check_client_gen.go` | verified |  |
| grafana | `e2e-playwright/dashboard-new-layouts/page-objects/sidebar/PanelOptions.ts` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/components/App/App.tsx` | verified |  |
| grafana | `packages/grafana-o11y-ds-frontend/src/IntervalInput/validation.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/Form.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/geo/index.ts` | verified |  |
| grafana | `pkg/api/dashboard_permission_test.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/legacy/sql_dashboards_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/metrics_mock.go` | verified |  |
| grafana | `pkg/services/accesscontrol/database/database.go` | verified |  |
| grafana | `pkg/services/accesscontrol/filter.go` | verified |  |
| grafana | `pkg/services/apiserver/builder/request_handler.go` | verified |  |
| grafana | `pkg/services/live/managedstream/cache_memory_test.go` | verified |  |
| grafana | `pkg/services/live/pipeline/frame_output_multiple.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/redis_peer.go` | verified |  |
| grafana | `pkg/services/secrets/kvstore/test_helpers.go` | verified |  |
| grafana | `playwright.config.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/export/FileExportPreview.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/annotations/AnnotationSettingsList.tsx` | verified |  |
| grafana | `public/app/features/logs/components/panel/LogListSearchContext.tsx` | verified |  |
| grafana | `public/app/features/variables/ensureStringValues.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/ResourcePicker/Search.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/fsql/fields.ts` | verified |  |
| grafana | `public/app/plugins/panel/canvas/globalStyles.ts` | verified |  |
| grafana | `public/app/plugins/panel/nodeGraph/EdgeLabel.tsx` | verified |  |
| grafana | `scripts/webpack/webpack.dev.ts` | verified |  |
