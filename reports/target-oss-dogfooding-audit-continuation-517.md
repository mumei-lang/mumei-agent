# Target OSS no-LLM dogfooding audit — continuation 517 (batch 518)

Run: 2026-07-23T07:47:02.591402+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue24161arg/use.go` | verified |  |
| go | `src/cmd/compile/internal/midway/rewrite.go` | verified |  |
| go | `src/cmd/internal/obj/loong64/doc.go` | verified |  |
| go | `src/crypto/internal/fips140/hkdf/cast.go` | verified |  |
| go | `src/encoding/json/v2/intern.go` | verified |  |
| go | `src/go/internal/gccgoimporter/ar.go` | verified |  |
| go | `src/html/template/doc.go` | verified |  |
| go | `src/internal/bytealg/index_ppc64x.go` | verified |  |
| go | `src/internal/cpu/cpu_arm64_darwin.go` | verified |  |
| go | `src/internal/goos/zgoos_aix.go` | verified |  |
| go | `src/math/ldexp.go` | verified |  |
| go | `src/net/http/main_test.go` | verified |  |
| go | `src/net/sendfile_test.go` | verified |  |
| go | `src/net/tcpsockopt_openbsd.go` | verified |  |
| go | `src/regexp/onepass_test.go` | verified |  |
| go | `src/syscall/ztypes_darwin_amd64.go` | verified |  |
| go | `src/syscall/ztypes_openbsd_ppc64.go` | verified |  |
| go | `src/time/internal_test.go` | verified |  |
| go | `test/abi/many_int_input.go` | verified |  |
| go | `test/args.go` | verified |  |
| go | `test/fixedbugs/bug510.go` | verified |  |
| go | `test/fixedbugs/issue21576.go` | verified |  |
| go | `test/fixedbugs/issue30430.go` | verified |  |
| go | `test/fixedbugs/issue36437.go` | verified |  |
| go | `test/fixedbugs/issue6703z.go` | verified |  |
| go | `test/fixedbugs/issue71857.go` | verified |  |
| grafana | `apps/advisor/pkg/app/utils.go` | verified |  |
| grafana | `apps/preferences/pkg/apis/preferences/v1/register.go` | verified |  |
| grafana | `apps/shorturl/pkg/apis/shorturl/v1beta1/shorturl_spec_gen.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/pages/ExposedComponents.tsx` | verified |  |
| grafana | `packages/grafana-schema/src/schema/dashboard/v2beta1/types.metadata.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Text/Text.tsx` | verified |  |
| grafana | `pkg/apiserver/rest/dualwriter_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/webhooks/webhook_replay_test.go` | verified |  |
| grafana | `pkg/services/annotations/accesscontrol/accesscontrol.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/common/info.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/file_store.go` | verified |  |
| grafana | `pkg/storage/unified/migrations/testcases/preferences.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/movejob_auth_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/errors.go` | verified |  |
| grafana | `public/app/core/components/Branding/OrangeBadge.tsx` | verified |  |
| grafana | `public/app/core/components/PageLoader/PageLoader.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/expressions/ExpressionStatusIndicator.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/tabs/Instances.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/navigation/useAlertRulesNav.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/WorkbenchContext.tsx` | verified |  |
| grafana | `public/app/features/canvas/elements/cloud.tsx` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/cloud/MigrationTokenPane/MigrationTokenPane.tsx` | verified |  |
| grafana | `public/app/features/provisioning/utils/quota.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/datasource.ts` | verified |  |
