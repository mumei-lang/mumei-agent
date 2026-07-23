# Target OSS no-LLM dogfooding audit — continuation 472 (batch 473)

Run: 2026-07-23T04:47:10.963413+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/loong64/galign.go` | verified |  |
| go | `src/cmd/compile/internal/mips64/galign.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/regalloc_test.go` | verified |  |
| go | `src/cmd/go/internal/cmdflag/flag.go` | verified |  |
| go | `src/cmd/go/internal/toolchain/umask_unix.go` | verified |  |
| go | `src/internal/poll/writev_test.go` | verified |  |
| go | `src/internal/runtime/maps/table.go` | verified |  |
| go | `src/math/big/calibrate_graph.go` | verified |  |
| go | `src/math/big/floatexample_test.go` | verified |  |
| go | `src/net/http/internal/sniff.go` | verified |  |
| go | `src/os/timeout_test.go` | verified |  |
| go | `src/runtime/defs_solaris.go` | verified |  |
| go | `src/runtime/os_openbsd_arm.go` | verified |  |
| go | `src/runtime/signal_openbsd.go` | verified |  |
| go | `src/syscall/syscall_openbsd_386.go` | verified |  |
| go | `test/const3.go` | verified |  |
| go | `test/fixedbugs/bug120.go` | verified |  |
| go | `test/fixedbugs/bug128.go` | verified |  |
| go | `test/fixedbugs/bug201.go` | verified |  |
| go | `test/fixedbugs/issue15961.go` | verified |  |
| go | `test/fixedbugs/issue18392.go` | verified |  |
| go | `test/fixedbugs/issue22662.go` | verified |  |
| go | `test/fixedbugs/issue71680.go` | verified |  |
| go | `test/linkname.dir/linkname3.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/routingtree_ext.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v1/dashboard_codec_gen.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/cache/cache.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/local/watch.go` | verified |  |
| grafana | `packages/grafana-data/src/utils/uuid.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Actions/ActionButton.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Button/FullWidthButtonContainer.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Combobox/MessageRows.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/utils/useTimeSync.tsx` | verified |  |
| grafana | `pkg/api/basic_auth.go` | verified |  |
| grafana | `pkg/components/satokengen/tokengen_test.go` | verified |  |
| grafana | `pkg/registry/apis/appplugin/metrics.go` | verified |  |
| grafana | `pkg/registry/apis/collections/legacy/sql.go` | verified |  |
| grafana | `pkg/registry/apis/folders/parents.go` | verified |  |
| grafana | `pkg/services/secrets/fakes/mock_service.go` | verified |  |
| grafana | `pkg/services/ssosettings/ssosettingstests/service_mock.go` | verified |  |
| grafana | `pkg/services/star/model.go` | verified |  |
| grafana | `pkg/storage/unified/search/remote_index_store.go` | verified |  |
| grafana | `pkg/storage/unified/sql/backend_gc_test.go` | verified |  |
| grafana | `public/app/features/dimensions/direction.ts` | verified |  |
| grafana | `public/app/features/playlist/PlaylistTable.tsx` | verified |  |
| grafana | `public/app/features/plugins/extensions/ExtensionRegistriesContext.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Repository/RepositoryStatusPage.tsx` | verified |  |
| grafana | `public/app/features/visualization/data-hover/DataHoverRow.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/test/helpers/selectOptionInTest.ts` | verified |  |
| grafana | `public/app/types/templates.ts` | verified |  |
