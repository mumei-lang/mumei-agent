# Target OSS no-LLM dogfooding audit — continuation 427 (batch 428)

Run: 2026-07-23T01:51:26.127386+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/asm/internal/arch/mips.go` | verified |  |
| go | `src/cmd/compile/internal/ppc64/opt.go` | verified |  |
| go | `src/cmd/compile/internal/ssagen/arch.go` | verified |  |
| go | `src/cmd/compile/internal/walk/assign.go` | verified |  |
| go | `src/cmd/covdata/merge.go` | verified |  |
| go | `src/cmd/go/internal/auth/auth_test.go` | verified |  |
| go | `src/cmd/go/internal/test/flagdefs.go` | verified |  |
| go | `src/cmd/internal/obj/mips/anames.go` | verified |  |
| go | `src/crypto/internal/fips140/ecdsa/ecdsa.go` | verified |  |
| go | `src/encoding/csv/example_test.go` | verified |  |
| go | `src/internal/abi/switch.go` | verified |  |
| go | `src/internal/cpu/cpu.go` | verified |  |
| go | `src/internal/fuzz/fuzz.go` | verified |  |
| go | `src/math/arith_s390x_test.go` | verified |  |
| go | `src/math/rand/auto_test.go` | verified |  |
| go | `src/net/http/roundtrip_js.go` | verified |  |
| go | `src/net/ipsock_plan9.go` | verified |  |
| go | `src/runtime/preempt.go` | verified |  |
| go | `src/syscall/exec_freebsd.go` | verified |  |
| go | `src/testing/slogtest/run_test.go` | verified |  |
| go | `test/fixedbugs/bug417.go` | verified |  |
| go | `test/fixedbugs/issue8507.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/createsearchexternalgroupmappings_request_body_types_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/teamlbacrule_spec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/auth/token_access_checker.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/clientset/versioned/fake/register.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/verify.go` | verified |  |
| grafana | `packages/grafana-data/src/types/pluginSignature.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Button/Button.tsx` | verified |  |
| grafana | `pkg/apis/appplugin/v0alpha1/zz_generated.openapi.go` | verified |  |
| grafana | `pkg/apiserver/endpoints/filters/path_rewriter.go` | verified |  |
| grafana | `pkg/infra/filestorage/filter_test.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/receiver/authorize.go` | verified |  |
| grafana | `pkg/services/frontend/webassets/webassets_test.go` | verified |  |
| grafana | `pkg/services/ngalert/image/upload_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/v1/compat_test.go` | verified |  |
| grafana | `pkg/services/rendering/capabilities_test.go` | verified |  |
| grafana | `pkg/services/user/userimpl/user_test.go` | verified |  |
| grafana | `public/app/api/clients/folder/v1beta1/test-utils.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/useRoutingTrees.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/TemplatePreview.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/inspect/HelpWizard/utils.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Body/ExpressionTypePicker.tsx` | verified |  |
| grafana | `public/app/features/logs/components/panel/LogLineDetailsLinks.tsx` | verified |  |
| grafana | `public/app/features/scopes/ScopesApiClient.ts` | verified |  |
| grafana | `public/app/features/serviceaccounts/ServiceAccountsListPage.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/alertmanager/types.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/standardStatistics.ts` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/state/context.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/mysql/types.ts` | verified |  |
