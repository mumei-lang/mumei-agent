# Target OSS no-LLM dogfooding audit — continuation 430 (batch 431)

Run: 2026-07-23T01:57:34.559133+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/types2/decl.go` | verified |  |
| go | `src/cmd/internal/objabi/autotype.go` | verified |  |
| go | `src/crypto/internal/fips140/edwards25519/edwards25519.go` | verified |  |
| go | `src/internal/runtime/gc/scan/filter_amd64_test.go` | verified |  |
| go | `src/internal/syscall/unix/at_sysnum_openbsd.go` | verified |  |
| go | `src/os/exec_plan9.go` | verified |  |
| go | `src/runtime/symtabinl.go` | verified |  |
| go | `src/runtime/syscall_unix_test.go` | verified |  |
| go | `src/sort/example_wrapper_test.go` | verified |  |
| go | `src/syscall/bpf_bsd.go` | verified |  |
| go | `src/syscall/syscall_test.go` | verified |  |
| go | `src/syscall/zsyscall_netbsd_386.go` | verified |  |
| go | `test/fixedbugs/bug241.go` | verified |  |
| go | `test/fixedbugs/bug265.go` | verified |  |
| go | `test/fixedbugs/bug300.go` | verified |  |
| go | `test/fixedbugs/issue26094.go` | verified |  |
| go | `test/fixedbugs/issue45503.dir/a.go` | verified |  |
| go | `test/typeparam/issue48276a.go` | verified |  |
| go | `test/typeparam/issue50317.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/getintegrationtypeschemas_response_types_gen.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/inhibitionrule_client_gen.go` | verified |  |
| grafana | `apps/plugins/pkg/app/meta/catalog.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/ScopesContext.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/MatchersUI/utils.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Splitter/useSplitter.ts` | verified |  |
| grafana | `pkg/apimachinery/identity/error.go` | verified |  |
| grafana | `pkg/apiserver/endpoints/filters/upstream_trace_link_test.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/storepb/v1/store_grpc.pb.go` | verified |  |
| grafana | `pkg/services/apiserver/builder/runner/admission.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_mutate_rolebindings_test.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_mutate_roles_test.go` | verified |  |
| grafana | `pkg/services/live/remotewrite/remotewrite.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/v1/errors.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/registry_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/usealertingheaders_middleware_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/test/alerting_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/annotation_mig.go` | verified |  |
| grafana | `pkg/tsdb/loki/api_mock.go` | verified |  |
| grafana | `pkg/tsdb/loki/scopes_test.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/MegaMenu/MegaMenuSkeleton.tsx` | verified |  |
| grafana | `public/app/features/admin/Users/UsersTable.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/navigation/extensions.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/editors/AdHocFiltersVariableEditor.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareButton/share-externally/PublicShare/PublicSharing.tsx` | verified |  |
| grafana | `public/app/features/dimensions/scalar.ts` | verified |  |
| grafana | `public/app/features/provisioning/guards.ts` | verified |  |
| grafana | `public/app/features/stars/utils.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/config-v2/InfluxInfluxQLDBConnection.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/config-v2/tracking.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/components/MeasureOverlay.tsx` | verified |  |
