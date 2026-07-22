# Target OSS no-LLM dogfooding audit — continuation 349 (batch 350)

Run: 2026-07-22T21:02:27.803497+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/syntax/pos.go` | verified |  |
| go | `src/cmd/go/internal/vcs/discovery_test.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/benchmark_test.go` | verified |  |
| go | `src/crypto/internal/fips140/tls13/cast.go` | verified |  |
| go | `src/crypto/internal/fips140only/fips140only_test.go` | verified |  |
| go | `src/crypto/x509/root_aix.go` | verified |  |
| go | `src/math/floor_noasm.go` | verified |  |
| go | `src/net/http/cookie.go` | verified |  |
| go | `src/runtime/rwmutex_test.go` | verified |  |
| go | `src/simd/archsimd/unsafe_helpers.go` | verified |  |
| go | `src/syscall/sockcmsg_unix.go` | verified |  |
| go | `test/char_lit.go` | verified |  |
| go | `test/fixedbugs/bug186.go` | verified |  |
| go | `test/fixedbugs/bug392.dir/pkg3.go` | verified |  |
| go | `test/fixedbugs/issue18331.go` | verified |  |
| go | `test/fixedbugs/issue30898.go` | verified |  |
| go | `test/fixedbugs/issue6295.dir/p1.go` | verified |  |
| go | `test/ken/robfunc.go` | verified |  |
| go | `test/ken/simpbool.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/validator.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizRepeater/VizRepeater.tsx` | verified |  |
| grafana | `pkg/registry/apis/dashboard/legacy/queries_test.go` | verified |  |
| grafana | `pkg/registry/apis/folders/conversions.go` | verified |  |
| grafana | `pkg/registry/apis/iam/team/retryable.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/commit.go` | verified |  |
| grafana | `pkg/services/ngalert/provisioning/compat.go` | verified |  |
| grafana | `pkg/services/ngalert/state/state_bench_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginstore/plugins.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/CloudRulesSourcePicker.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/RuleConfigStatus.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/silences/SilenceStateTag.tsx` | verified |  |
| grafana | `public/app/features/browse-dashboards/state/actions.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/version-history/LazyDiffViewer.tsx` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useCreateOrUpdateRepositoryFile.ts` | verified |  |
| grafana | `public/app/features/variables/guard.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryEditor/TimeManagement.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/jaeger/configuration/TraceIdTimeParams.tsx` | verified |  |
| grafana | `public/app/plugins/panel/bargauge/module.tsx` | verified |  |
| grafana | `public/app/plugins/panel/xychart/config.ts` | verified |  |
| grafana | `public/app/types/ldap.ts` | verified |  |
| prysm | `api/server/structs/conversions_gloas.go` | verified |  |
| prysm | `beacon-chain/blockchain/receive_block.go` | verified |  |
| prysm | `beacon-chain/db/filesystem/data_column_cache.go` | verified |  |
| prysm | `beacon-chain/db/filesystem/iteration_test.go` | verified |  |
| prysm | `beacon-chain/p2p/discovery_test.go` | verified |  |
| prysm | `crypto/bls/blst/bls_benchmark_test.go` | verified |  |
| prysm | `testing/spectest/shared/phase0/operations/block_header.go` | verified |  |
| prysm | `tools/analyzers/modernize/bloop/analyzer.go` | verified |  |
| prysm | `validator/accounts/accounts_delete_test.go` | verified |  |
| prysm | `validator/client/wait_helpers_test.go` | verified |  |
