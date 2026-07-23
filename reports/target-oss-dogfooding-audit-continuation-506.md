# Target OSS no-LLM dogfooding audit — continuation 506 (batch 507)

Run: 2026-07-23T07:16:01.099302+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/types2/errsupport.go` | verified |  |
| go | `src/cmd/go/internal/modload/mvs_test.go` | verified |  |
| go | `src/cmd/gofmt/gofmt_unix_test.go` | verified |  |
| go | `src/cmd/internal/obj/x86/asm_test.go` | verified |  |
| go | `src/crypto/mldsa/mldsa_fips140v1.26.go` | verified |  |
| go | `src/crypto/tls/internal/fips140tls/fipstls.go` | verified |  |
| go | `src/encoding/gob/error.go` | verified |  |
| go | `src/encoding/json/v2/arshal.go` | verified |  |
| go | `src/internal/goos/zgoos_ios.go` | verified |  |
| go | `src/runtime/signal_linux_s390x.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/binary_128_test.go` | verified |  |
| go | `src/syscall/zsyscall_freebsd_386.go` | verified |  |
| go | `test/abi/map.go` | verified |  |
| go | `test/fixedbugs/bug364.go` | verified |  |
| go | `test/fixedbugs/issue22164.go` | verified |  |
| go | `test/fixedbugs/issue32922.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue34123.go` | verified |  |
| go | `test/fixedbugs/issue40152.go` | verified |  |
| go | `test/fixedbugs/issue49100b.go` | verified |  |
| go | `test/typeparam/issue45738.go` | verified |  |
| go | `test/typeparam/issue48280.go` | verified |  |
| go | `test/typeparam/issue51250a.dir/b.go` | verified |  |
| go | `test/typeparam/issue55101.go` | verified |  |
| grafana | `apps/playlist/pkg/apis/playlist/v0alpha1/playlist_schema_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/controller/job_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/healthstatus.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/git/sign_test.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/generator/commands.ts` | verified |  |
| grafana | `packages/grafana-data/src/context/plugins/usePluginContext.tsx` | verified |  |
| grafana | `packages/grafana-test-utils/src/unstable.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/TimeZonePicker/TimeZoneGroup.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/PanelChrome/HoverWidget.tsx` | verified |  |
| grafana | `pkg/api/avatar/avatar.go` | verified |  |
| grafana | `pkg/codegen/jenny_eachmajor.go` | verified |  |
| grafana | `pkg/registry/apis/iam/user/mutate.go` | verified |  |
| grafana | `pkg/registry/apis/ofrep/http_routes.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/adminconfig_register_test.go` | verified |  |
| grafana | `pkg/server/wireexts_oss.go` | verified |  |
| grafana | `pkg/services/accesscontrol/errors.go` | verified |  |
| grafana | `pkg/services/correlations/conversions_test.go` | verified |  |
| grafana | `pkg/services/screenshot/screenshot_mock.go` | verified |  |
| grafana | `pkg/services/store/kind/dashboard/dashboard_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/git/webhook/helper_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/Filter/RulesViewModeSelector.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/constants.ts` | verified |  |
| grafana | `public/app/features/correlations/__mocks__/correlations.scenario.ts` | verified |  |
| grafana | `public/app/features/plugins/extensions/registry/types.ts` | verified |  |
| grafana | `public/app/features/transformers/regression/regression.ts` | verified |  |
| grafana | `public/app/features/transformers/spatial/optionsHelper.tsx` | verified |  |
| grafana | `public/app/plugins/panel/logstable/suggestions.ts` | verified |  |
