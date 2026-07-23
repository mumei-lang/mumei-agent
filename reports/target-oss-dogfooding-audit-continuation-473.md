# Target OSS no-LLM dogfooding audit — continuation 473 (batch 474)

Run: 2026-07-23T04:49:06.215350+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/check.go` | verified |  |
| go | `src/cmd/internal/obj/ppc64/anames9.go` | verified |  |
| go | `src/crypto/internal/fips140/sha512/sha512block_ppc64x.go` | verified |  |
| go | `src/encoding/encoding.go` | verified |  |
| go | `src/encoding/json/v2/fuzz_test.go` | verified |  |
| go | `src/internal/cpu/cpu_arm64_hwcap.go` | verified |  |
| go | `src/internal/fuzz/mutator.go` | verified |  |
| go | `src/net/rawconn_test.go` | verified |  |
| go | `src/runtime/abi_test.go` | verified |  |
| go | `src/syscall/zsyscall_openbsd_ppc64.go` | verified |  |
| go | `test/fixedbugs/bug437.dir/x.go` | verified |  |
| go | `test/fixedbugs/issue22660.go` | verified |  |
| go | `test/fixedbugs/issue23868.go` | verified |  |
| go | `test/fixedbugs/issue42284.go` | verified |  |
| go | `test/fixedbugs/issue45743.go` | verified |  |
| go | `test/fixedbugs/issue54722.go` | verified |  |
| go | `test/func7.go` | verified |  |
| go | `test/typeparam/issue48962.dir/b.go` | verified |  |
| go | `test/typeparam/issue49611.go` | verified |  |
| go | `test/typeparam/pragma.go` | verified |  |
| grafana | `apps/alerting/rules/plugin/src/generated/rulesequence/v0alpha1/types.status.gen.ts` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v0alpha1/snapshot_object_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/serviceaccount_spec_gen.go` | verified |  |
| grafana | `packages/grafana-data/src/utils/valueMappings.ts` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/nodegraph/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/FormField/FormField.tsx` | verified |  |
| grafana | `pkg/expr/transform.go` | verified |  |
| grafana | `pkg/registry/apis/folders/sub_count.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_check_teamfolder_test.go` | verified |  |
| grafana | `pkg/services/featuremgmt/static_provider_test.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/service/annotations.go` | verified |  |
| grafana | `pkg/services/team/team.go` | verified |  |
| grafana | `pkg/services/user/usertest/fake.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/types/types.go` | verified |  |
| grafana | `pkg/tsdb/grafana-postgresql-datasource/macros.go` | verified |  |
| grafana | `pkg/tsdb/loki/sql_test.go` | verified |  |
| grafana | `public/app/api/clients/folder/v1beta1/index.ts` | verified |  |
| grafana | `public/app/core/app_events.ts` | verified |  |
| grafana | `public/app/core/components/AppChrome/FullscreenWorkspace/AssistantToolbarButtons.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/integration/AlertRulesToolbarButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/links/ProvisionedLinksSection.tsx` | verified |  |
| grafana | `public/app/features/dashboard/api/v2.ts` | verified |  |
| grafana | `public/app/features/dashboard/types/revisionModels.ts` | verified |  |
| grafana | `public/app/features/logs/components/panel/LogListControlsOption.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Shared/CodeBlock.tsx` | verified |  |
| grafana | `public/app/features/runtime/init.ts` | verified |  |
| grafana | `public/app/features/serviceaccounts/components/ServiceAccountProfile.tsx` | verified |  |
| grafana | `public/app/features/variables/adhoc/picker/AdHocFilter.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/cloudwatch-logs-test-data/diffModifierQuery.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/query_part.ts` | verified |  |
