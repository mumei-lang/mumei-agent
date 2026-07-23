# Target OSS no-LLM dogfooding audit — continuation 496 (batch 497)

Run: 2026-07-23T06:36:26.263378+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/bufio/scan_test.go` | verified |  |
| go | `src/cmd/compile/internal/x86/ggen.go` | verified |  |
| go | `src/cmd/go/internal/cacheprog/cacheprog.go` | verified |  |
| go | `src/crypto/internal/fips140/asan.go` | verified |  |
| go | `src/crypto/md5/example_test.go` | verified |  |
| go | `src/index/suffixarray/suffixarray.go` | verified |  |
| go | `src/internal/bytealg/count_native.go` | verified |  |
| go | `src/internal/bytealg/indexbyte_native.go` | verified |  |
| go | `src/internal/strconv/pow10gen.go` | verified |  |
| go | `src/internal/zstd/xxhash_test.go` | verified |  |
| go | `src/os/timeout_unix_test.go` | verified |  |
| go | `src/runtime/env_plan9.go` | verified |  |
| go | `src/runtime/pprof/label_test.go` | verified |  |
| go | `src/syscall/setuidgid_linux.go` | verified |  |
| go | `test/dwarf/dwarf.dir/z5.go` | verified |  |
| go | `test/escape4.go` | verified |  |
| go | `test/fixedbugs/bug177.go` | verified |  |
| go | `test/fixedbugs/issue20027.go` | verified |  |
| go | `test/fixedbugs/issue54542.go` | verified |  |
| go | `test/fixedbugs/issue6513.go` | verified |  |
| go | `test/reflectmethod6.go` | verified |  |
| go | `test/typeparam/issue51840.go` | verified |  |
| go | `test/typeparam/list2.go` | verified |  |
| go | `test/uintptrescapes.dir/main.go` | verified |  |
| grafana | `apps/correlations/pkg/apis/correlation_manifest.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2alpha1/dashboard_status_gen.go` | verified |  |
| grafana | `apps/playlist/pkg/apis/playlist/v1/constants.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/finalizers.go` | verified |  |
| grafana | `apps/quotas/pkg/apis/quotas/v0alpha1/getusage_response_object_types_gen.go` | verified |  |
| grafana | `apps/shorturl/pkg/apis/shorturl/v1beta1/constants.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Monaco/CodeEditor.tsx` | verified |  |
| grafana | `pkg/apis/iam/v0alpha1/zz_generated.defaults.go` | verified |  |
| grafana | `pkg/apiserver/auditing/policy_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/commit_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/deleteresources/worker_test.go` | verified |  |
| grafana | `pkg/registry/apis/secret/secretkeeper/secretkeeper_test.go` | verified |  |
| grafana | `pkg/registry/apis/wireset.go` | verified |  |
| grafana | `pkg/registry/apps/querycaching/migrator/migrator.go` | verified |  |
| grafana | `pkg/services/authz/rbac/store/permission_store.go` | verified |  |
| grafana | `pkg/services/dashboardimport/api/api.go` | verified |  |
| grafana | `pkg/services/serviceaccounts/serviceaccounts.go` | verified |  |
| grafana | `pkg/services/team/search/search.go` | verified |  |
| grafana | `pkg/util/ring/adaptive_chan.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/RulesTable.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/abilities/alertmanager/useAlertmanagerAdminAbility.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/components/NoRulesFound.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/CriticalPath/testCases/test5.ts` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/types.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/time_grain_converter.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/syntax.ts` | verified |  |
