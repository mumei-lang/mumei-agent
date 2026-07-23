# Target OSS no-LLM dogfooding audit — continuation 521 (batch 522)

Run: 2026-07-23T07:55:18.319344+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/addr2line/main.go` | verified |  |
| go | `src/cmd/go/internal/auth/userauth_test.go` | verified |  |
| go | `src/cmd/go/internal/doc/doc_test.go` | verified |  |
| go | `src/cmd/go/internal/modfetch/zip_sum_test/zip_sum_test.go` | verified |  |
| go | `src/cmd/internal/obj/ppc64/list9.go` | verified |  |
| go | `src/cmd/internal/obj/wasm/a.out.go` | verified |  |
| go | `src/crypto/rand/util.go` | verified |  |
| go | `src/internal/buildcfg/cfg.go` | verified |  |
| go | `src/internal/poll/error_stub_test.go` | verified |  |
| go | `src/internal/syslist/syslist.go` | verified |  |
| go | `src/internal/trace/batchcursor_test.go` | verified |  |
| go | `src/net/error_posix.go` | verified |  |
| go | `src/runtime/secret_noasm.go` | verified |  |
| go | `src/runtime/signal_dragonfly_amd64.go` | verified |  |
| go | `src/runtime/tracestatus.go` | verified |  |
| go | `src/syscall/zsysnum_freebsd_riscv64.go` | verified |  |
| go | `src/unsafe/unsafe.go` | verified |  |
| go | `test/fixedbugs/bug011.go` | verified |  |
| go | `test/fixedbugs/bug122.go` | verified |  |
| go | `test/fixedbugs/issue10219.dir/c.go` | verified |  |
| go | `test/fixedbugs/issue16616.go` | verified |  |
| go | `test/fixedbugs/issue19705.go` | verified |  |
| go | `test/fixedbugs/issue38496.go` | verified |  |
| go | `test/fixedbugs/issue39292.go` | verified |  |
| go | `test/fixedbugs/issue78016.go` | verified |  |
| go | `test/init.go` | verified |  |
| go | `test/typeparam/mdempsky/18.go` | verified |  |
| grafana | `apps/example/pkg/apis/example/v1alpha1/getsomething_response_body_types_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/stageable_repository_mock.go` | verified |  |
| grafana | `packages/grafana-data/src/types/vector.ts` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/bargauge/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `pkg/api/dtos/user_token.go` | verified |  |
| grafana | `pkg/components/simplejson/simplejson_go11.go` | verified |  |
| grafana | `pkg/plugins/manager/process/process_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/user/search.go` | verified |  |
| grafana | `pkg/registry/apis/iam/user/store.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/webhooks/pullrequest/render_test.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/register.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/openfga_server.go` | verified |  |
| grafana | `pkg/services/ngalert/api/tooling/definitions/inhibition_rule.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/httpclient_middleware.go` | verified |  |
| grafana | `pkg/services/screenshot/option.go` | verified |  |
| grafana | `pkg/storage/unified/resource/broadcaster_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/job_warning_result_test.go` | verified |  |
| grafana | `pkg/tsdb/loki/scopes.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/RuleViewer.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-editor/formDefaults.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/conditional-rendering/group/ConditionalRenderingGroupAdd.tsx` | verified |  |
| grafana | `public/app/features/explore/LimitedDataDisclaimer.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Migrate/stats.ts` | verified |  |
