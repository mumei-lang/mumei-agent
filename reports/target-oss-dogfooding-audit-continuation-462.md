# Target OSS no-LLM dogfooding audit — continuation 462 (batch 463)

Run: 2026-07-23T04:05:54.247361+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/arm64/pair_test.go` | verified |  |
| go | `src/cmd/compile/internal/inline/inlheur/analyze_func_params.go` | verified |  |
| go | `src/cmd/compile/internal/types2/mono.go` | verified |  |
| go | `src/crypto/internal/fips140/edwards25519/doc.go` | verified |  |
| go | `src/crypto/rsa/fips.go` | verified |  |
| go | `src/crypto/x509/verify_test.go` | verified |  |
| go | `src/math/big/bits_test.go` | verified |  |
| go | `src/net/http/header_test.go` | verified |  |
| go | `src/net/tcpconn_keepalive_conf_solaris_test.go` | verified |  |
| go | `src/os/exec/lp_unix_test.go` | verified |  |
| go | `src/os/types_plan9.go` | verified |  |
| go | `src/path/filepath/symlink_plan9.go` | verified |  |
| go | `src/runtime/os_darwin.go` | verified |  |
| go | `src/simd/archsimd/clmul_arm64.go` | verified |  |
| go | `src/sync/atomic/example_test.go` | verified |  |
| go | `test/codegen/issue74485.go` | verified |  |
| go | `test/fixedbugs/issue23504.go` | verified |  |
| go | `test/fixedbugs/issue43384.go` | verified |  |
| go | `test/fixedbugs/issue45503.go` | verified |  |
| go | `test/label.go` | verified |  |
| go | `test/typeparam/mdempsky/4.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/errors.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/git/branch_test.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/components/App/index.tsx` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/contactPoints/components/ContactPointSelector/ContactPointSelector.tsx` | verified |  |
| grafana | `packages/grafana-data/src/themes/createTheme.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Divider/Divider.tsx` | verified |  |
| grafana | `pkg/api/folder.go` | verified |  |
| grafana | `pkg/api/plugin_metrics_test.go` | verified |  |
| grafana | `pkg/infra/log/composite_logger_test.go` | verified |  |
| grafana | `pkg/login/social/socialtest/social_service_fake.go` | verified |  |
| grafana | `pkg/plugins/manager/signature/statickey/static_retriever.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/loki_history_test.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/tracing_header_middleware_test.go` | verified |  |
| grafana | `pkg/services/queryhistory/queryhistory_details_test.go` | verified |  |
| grafana | `pkg/storage/unified/informer/store_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/shorturl_benchmark_test.go` | verified |  |
| grafana | `pkg/tests/api/alerting/api_alertmanager_silence_test.go` | verified |  |
| grafana | `pkg/tests/apis/iam/team/team_redirect_integration_test.go` | verified |  |
| grafana | `public/app/core/components/ForgottenPassword/ChangePassword.tsx` | verified |  |
| grafana | `public/app/core/components/TagFilter/TagOption.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/contact-points/components/GlobalConfig.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/enterprise-components/AI/AIGenImproveAnnotationsButton/addAIImproveAnnotationsButton.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/DataLayerControl.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-rows/RowItemRepeater.tsx` | verified |  |
| grafana | `public/app/features/datasources/state/reducers.ts` | verified |  |
| grafana | `public/app/features/plugins/admin/state/hooks.ts` | verified |  |
| grafana | `public/app/features/provisioning/hooks/usePRBranch.ts` | verified |  |
| grafana | `public/app/features/variables/shared/testing/builders.ts` | verified |  |
