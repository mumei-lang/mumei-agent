# Target OSS no-LLM dogfooding audit — continuation 458 (batch 459)

Run: 2026-07-23T03:58:35.743445+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/archive/zip/zip_test.go` | verified |  |
| go | `src/cmd/compile/internal/ppc64/galign.go` | verified |  |
| go | `src/cmd/compile/internal/types2/package.go` | verified |  |
| go | `src/cmd/go/internal/modfetch/codehost/git.go` | verified |  |
| go | `src/cmd/link/internal/loader/symbolbuilder.go` | verified |  |
| go | `src/crypto/internal/fips140deps/time/time_windows.go` | verified |  |
| go | `src/debug/macho/reloctype.go` | verified |  |
| go | `src/image/gif/fuzz_test.go` | verified |  |
| go | `src/internal/strconv/atoi.go` | verified |  |
| go | `src/internal/syscall/unix/sysnum_linux_mips64x.go` | verified |  |
| go | `src/net/sockopt_windows.go` | verified |  |
| go | `src/os/dirent_linux.go` | verified |  |
| go | `src/runtime/defs_linux_s390x.go` | verified |  |
| go | `src/runtime/panic32.go` | verified |  |
| go | `src/runtime/signal_openbsd_riscv64.go` | verified |  |
| go | `src/runtime/tracecpu.go` | verified |  |
| go | `src/strings/clone_test.go` | verified |  |
| go | `test/abi/struct_3_string_input.go` | verified |  |
| go | `test/fixedbugs/bug088.dir/bug0.go` | verified |  |
| go | `test/fixedbugs/issue31053.go` | verified |  |
| go | `test/typeparam/issue47676.go` | verified |  |
| go | `test/typeparam/issue48609.go` | verified |  |
| grafana | `apps/collections/pkg/apis/collections/v1alpha1/stars.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/v2alpha1_to_v2beta1.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/clientset/versioned/typed/provisioning/v0alpha1/historicjob.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginMeta/datasources.ts` | verified |  |
| grafana | `pkg/api/http_server_test.go` | verified |  |
| grafana | `pkg/apis/datasource/v0alpha1/query.go` | verified |  |
| grafana | `pkg/registry/apis/folders/hooks.go` | verified |  |
| grafana | `pkg/services/apiserver/appinstaller/strategy.go` | verified |  |
| grafana | `pkg/services/folder/service.go` | verified |  |
| grafana | `pkg/services/ngalert/api/api_convert_prometheus.go` | verified |  |
| grafana | `pkg/services/stats/statsimpl/stats_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/doc.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/log_sync_query_test.go` | verified |  |
| grafana | `pkg/tsdb/jaeger/grpc_client.go` | verified |  |
| grafana | `pkg/util/testutil/pgtest/pgtest.go` | verified |  |
| grafana | `public/app/core/components/GraphNG/GraphNG.tsx` | verified |  |
| grafana | `public/app/core/components/RolePicker/TeamRolePicker.tsx` | verified |  |
| grafana | `public/app/features/admin/api.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/export/GrafanaRuleFolderExporter.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/mute-timings/mocks.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/HelpWizard/utils.ts` | verified |  |
| grafana | `public/app/features/datasources/components/DataSourceMissingRightsMessage.tsx` | verified |  |
| grafana | `public/app/features/explore/QueryLibrary/QueryLibraryContext.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/SpanDetail/DetailState.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/utils/DraggableManager/types.tsx` | verified |  |
| grafana | `public/app/features/invites/state/selectors.ts` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useImportProvisionedSave.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/mocks/datasource.ts` | verified |  |
