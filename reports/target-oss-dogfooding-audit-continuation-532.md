# Target OSS no-LLM dogfooding audit — continuation 532 (batch 533)

Run: 2026-07-23T08:59:05.983290+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/_gen/MIPSOps.go` | verified |  |
| go | `src/cmd/compile/internal/test/race.go` | verified |  |
| go | `src/cmd/internal/obj/s390x/asmz.go` | verified |  |
| go | `src/crypto/internal/cryptotest/x509limbo/_schema/schema_gen.go` | verified |  |
| go | `src/crypto/internal/fips140/sha512/sha512block_asm.go` | verified |  |
| go | `src/crypto/internal/fips140/subtle/constant_time_test.go` | verified |  |
| go | `src/crypto/internal/fips140only/random_fips140v1.28.go` | verified |  |
| go | `src/encoding/json/v2_decode_test.go` | verified |  |
| go | `src/flag/export_test.go` | verified |  |
| go | `src/go/parser/error_test.go` | verified |  |
| go | `src/internal/gover/gover.go` | verified |  |
| go | `src/internal/platform/supported.go` | verified |  |
| go | `src/math/bits/make_tables.go` | verified |  |
| go | `src/net/http/responsewrite_test.go` | verified |  |
| go | `src/net/interface_linux_test.go` | verified |  |
| go | `src/runtime/trace/batch.go` | verified |  |
| go | `src/syscall/syscall_windows.go` | verified |  |
| go | `src/weak/doc.go` | verified |  |
| go | `test/chanlinear.go` | verified |  |
| go | `test/codegen/issue31618.go` | verified |  |
| go | `test/codegen/logic.go` | verified |  |
| go | `test/fixedbugs/bug049.go` | verified |  |
| go | `test/fixedbugs/bug511.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue21048.go` | verified |  |
| go | `test/fixedbugs/issue28053.go` | verified |  |
| go | `test/fixedbugs/issue33903.go` | verified |  |
| go | `test/fixedbugs/issue38690.go` | verified |  |
| go | `test/fixedbugs/issue6247.go` | verified |  |
| grafana | `apps/example/pkg/apis/example/v0alpha1/example_object_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/serviceaccount_listserviceaccounttokens_request_params_types_gen.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1beta1/logsdrilldowndefaultcolumns_status_gen.go` | verified |  |
| grafana | `packages/grafana-data/src/types/pluginExtensions.ts` | verified |  |
| grafana | `packages/grafana-sql/src/components/configuration/TLSSecretsConfig.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/List/AbstractList.tsx` | verified |  |
| grafana | `pkg/plugins/repo/service_test.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/store/migration/migrator.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/config.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/keyretriever/dynamic/dynamic_retriever_test.go` | verified |  |
| grafana | `pkg/services/preference/themes_generated.go` | verified |  |
| grafana | `pkg/services/quota/context.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/user_auth_mig.go` | verified |  |
| grafana | `pkg/tests/api/correlations/correlations_delete_test.go` | verified |  |
| grafana | `pkg/util/encoding.go` | verified |  |
| grafana | `public/app/core/components/TimelineChart/utils.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/yamlToRulerConverter.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/notificaton-preview/PolicyTreeSelector.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/types/alerting.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/SaveDashboard/SaveDashboardDiff.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/QueryEditor/LogsQueryEditor/code-editors/PPLQueryEditor.tsx` | verified |  |
| grafana | `scripts/cli/themeTemplates/_variables.light.scss.tmpl.ts` | verified |  |
