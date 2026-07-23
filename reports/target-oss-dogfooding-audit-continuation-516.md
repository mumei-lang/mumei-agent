# Target OSS no-LLM dogfooding audit — continuation 516 (batch 517)

Run: 2026-07-23T07:45:03.591494+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue9510.go` | verified |  |
| go | `src/cmd/go/internal/envcmd/env_test.go` | verified |  |
| go | `src/cmd/go/internal/mmap/mmap_test.go` | verified |  |
| go | `src/cmd/go/internal/modinfo/info.go` | verified |  |
| go | `src/cmd/go/internal/work/exec.go` | verified |  |
| go | `src/hash/crc32/crc32_loong64.go` | verified |  |
| go | `src/internal/syscall/unix/fcntl_wasip1.go` | verified |  |
| go | `src/internal/syscall/windows/symlink_windows.go` | verified |  |
| go | `src/reflect/map.go` | verified |  |
| go | `src/regexp/onepass.go` | verified |  |
| go | `src/runtime/mem_windows.go` | verified |  |
| go | `src/runtime/netpoll_aix.go` | verified |  |
| go | `test/const8.go` | verified |  |
| go | `test/fixedbugs/bug027.go` | verified |  |
| go | `test/fixedbugs/bug304.go` | verified |  |
| go | `test/fixedbugs/issue19783.go` | verified |  |
| go | `test/fixedbugs/issue21887.go` | verified |  |
| go | `test/fixedbugs/issue22941.go` | verified |  |
| go | `test/fixedbugs/issue33013.go` | verified |  |
| go | `test/fixedbugs/issue44355.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue45323.go` | verified |  |
| go | `test/fixedbugs/issue5470.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue6703s.go` | verified |  |
| go | `test/fixedbugs/issue72063.go` | verified |  |
| go | `test/fixedbugs/issue9017.go` | verified |  |
| go | `test/return.go` | verified |  |
| go | `test/stress/maps.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/config_object_gen.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/timeinterval_schema_gen.go` | verified |  |
| grafana | `apps/annotation/pkg/apis/annotation/v0alpha1/gettags_response_object_types_gen.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableRT/RowExpander.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/graveyard/GraphNG/GraphNG.tsx` | verified |  |
| grafana | `pkg/api/dtos/index.go` | verified |  |
| grafana | `pkg/ifaces/gcsifaces/gcsifaces.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/fileformat.go` | verified |  |
| grafana | `pkg/services/authn/authnserver/service.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/sandbox/sandbox_test.go` | verified |  |
| grafana | `pkg/services/provisioning/values/values_test.go` | verified |  |
| grafana | `pkg/services/ssosettings/validation/validator.go` | verified |  |
| grafana | `pkg/setting/setting_test.go` | verified |  |
| grafana | `pkg/tsdb/graphite/admission_handler.go` | verified |  |
| grafana | `pkg/web/webtest/middleware.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/mute-timings/MuteTimingForm.tsx` | verified |  |
| grafana | `public/app/features/auth-config/AuthProvidersListPage.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Body/TransformationTypePicker.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/localStorageWithTTL.ts` | verified |  |
| grafana | `public/app/features/profile/UserOrganizations.tsx` | verified |  |
| grafana | `public/app/features/transformers/spatial/spatialTransformer.ts` | verified |  |
| grafana | `public/app/plugins/panel/canvas/components/CanvasTooltip.tsx` | verified |  |
| grafana | `public/app/plugins/panel/logs/useDatasourcesFromTargets.ts` | verified |  |
