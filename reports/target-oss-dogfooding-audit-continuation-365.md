# Target OSS no-LLM dogfooding audit — continuation 365 (batch 366)

Run: 2026-07-22T22:02:05.631455+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/gc/util.go` | verified |  |
| go | `src/cmd/compile/internal/ir/html.go` | verified |  |
| go | `src/cmd/compile/internal/types2/builtins.go` | verified |  |
| go | `src/cmd/compile/internal/types2/cycles.go` | verified |  |
| go | `src/cmd/covdata/tool_test.go` | verified |  |
| go | `src/cmd/distpack/archive_test.go` | verified |  |
| go | `src/cmd/go/internal/modcmd/tidy.go` | verified |  |
| go | `src/crypto/internal/fips140/edwards25519/field/_asm/fe_amd64_asm.go` | verified |  |
| go | `src/crypto/md5/_asm/md5block_amd64_asm.go` | verified |  |
| go | `src/encoding/pem/pem.go` | verified |  |
| go | `src/go/types/util_test.go` | verified |  |
| go | `src/internal/fuzz/counters_unsupported.go` | verified |  |
| go | `src/internal/goos/nonunix.go` | verified |  |
| go | `src/internal/types/errors/codes_test.go` | verified |  |
| go | `src/math/cmplx/conj.go` | verified |  |
| go | `src/math/const.go` | verified |  |
| go | `src/runtime/preempt_loong64.go` | verified |  |
| go | `src/runtime/signal_windows_386.go` | verified |  |
| go | `test/fixedbugs/issue44823.go` | verified |  |
| go | `test/fixedbugs/issue48834.go` | verified |  |
| go | `test/gc2.go` | verified |  |
| go | `test/stringrange.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/shorturl/v1beta1/baseAPI.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/navigation/useHelpNavItem.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/BigValue/BigValueTypes.ts` | verified |  |
| grafana | `pkg/api/datasource/connections_test.go` | verified |  |
| grafana | `pkg/apis/iam/v0alpha1/types_team.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/export/worker.go` | verified |  |
| grafana | `pkg/services/auth/authimpl/token_cleanup_test.go` | verified |  |
| grafana | `pkg/services/auth/authtest/auth_token_service_mock.go` | verified |  |
| grafana | `pkg/services/grpcserver/health.go` | verified |  |
| grafana | `pkg/services/loginattempt/loginattempttest/fake.go` | verified |  |
| grafana | `pkg/services/ngalert/api/compat/compat_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/images.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/nats/relist/helpers_test.go` | verified |  |
| grafana | `pkg/tsdb/loki/flatten_tabular.go` | verified |  |
| grafana | `public/app/features/alerting/unified/navigation/useNotificationConfigNav.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/instance-details/QueryVisualization.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/conditional-rendering/conditions/serializers.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/conditional-rendering/hooks/useConditionalRenderingEditor.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/VariableEditorList.tsx` | verified |  |
| grafana | `public/app/features/explore/LiveTailButton.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/components/Loader.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/components/PluginList.tsx` | verified |  |
| grafana | `public/app/features/plugins/extensions/registry/Registry.ts` | verified |  |
| grafana | `public/app/features/query/state/QueryRunner.ts` | verified |  |
| grafana | `public/app/features/transformers/editors/ReduceTransformerEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/CheatSheet/tokenizer.ts` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/module.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/jaeger/components/SearchForm.tsx` | verified |  |
