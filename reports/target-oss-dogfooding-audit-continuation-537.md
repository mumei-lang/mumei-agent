# Target OSS no-LLM dogfooding audit — continuation 537 (batch 538)

Run: 2026-07-23T09:16:48.503293+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/internal/telemetrystats/version_other.go` | verified |  |
| go | `src/crypto/internal/fips140/aes/const.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/p521.go` | verified |  |
| go | `src/encoding/json/decode_test.go` | verified |  |
| go | `src/encoding/json/jsontext/options.go` | verified |  |
| go | `src/go/types/builtins.go` | verified |  |
| go | `src/go/types/under.go` | verified |  |
| go | `src/internal/strconv/import_test.go` | verified |  |
| go | `src/log/slog/internal/buffer/buffer.go` | verified |  |
| go | `src/math/big/internal/asmgen/loong64.go` | verified |  |
| go | `src/net/http/internal/http2/server_test.go` | verified |  |
| go | `src/os/exec/internal/fdtest/exists_windows.go` | verified |  |
| go | `src/runtime/vdso_linux_amd64.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/helpers_test.go` | verified |  |
| go | `src/syscall/ztypes_netbsd_386.go` | verified |  |
| go | `src/text/template/template.go` | verified |  |
| go | `test/abi/result_regalloc.go` | verified |  |
| go | `test/dwarf/dwarf.dir/z8.go` | verified |  |
| go | `test/fixedbugs/bug445.go` | verified |  |
| go | `test/fixedbugs/bug468.dir/p1.go` | verified |  |
| go | `test/fixedbugs/issue19632.go` | verified |  |
| go | `test/fixedbugs/issue20530.go` | verified |  |
| go | `test/fixedbugs/issue23781.go` | verified |  |
| go | `test/fixedbugs/issue29610.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue53137.go` | verified |  |
| go | `test/fixedbugs/issue55889.go` | verified |  |
| go | `test/typeparam/importtest.go` | verified |  |
| go | `test/typeparam/mdempsky/3.dir/a.go` | verified |  |
| go | `test/typeparam/valimp.dir/main.go` | verified |  |
| go | `test/typeparam/valimp.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/local/validator.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/CodeMirror/useLanguageExtension.ts` | verified |  |
| grafana | `pkg/api/datasource/connections.go` | verified |  |
| grafana | `pkg/registry/apis/iam/datasourcek8s/k8s.go` | verified |  |
| grafana | `pkg/registry/apis/iam/resourcepermission/sql_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/conditions.go` | verified |  |
| grafana | `pkg/services/accesscontrol/resolvers_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/roles_test.go` | verified |  |
| grafana | `pkg/services/libraryelements/libraryelements_k8s_folder_test.go` | verified |  |
| grafana | `pkg/services/validations/service.go` | verified |  |
| grafana | `pkg/storage/unified/testing/kv_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/contact-points/useNotificationTemplates.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/central-state-history/__fixtures__/alert-state-history.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useExternalAmSelector.ts` | verified |  |
| grafana | `public/app/features/provisioning/GettingStarted/types.ts` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/AuthTypeStep.tsx` | verified |  |
| grafana | `public/app/features/transformers/fieldToConfigMapping/fieldToConfigMapping.ts` | verified |  |
| grafana | `public/app/features/variables/shared/testing/intervalVariableBuilder.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/cloudwatch-logs-test-data/commentOnlyQuery.ts` | verified |  |
| grafana | `public/app/plugins/panel/nodeGraph/useContextMenu.tsx` | verified |  |
