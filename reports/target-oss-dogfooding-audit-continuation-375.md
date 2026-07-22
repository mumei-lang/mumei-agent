# Target OSS no-LLM dogfooding audit — continuation 375 (batch 376)

Run: 2026-07-22T22:32:03.727424+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/asm/internal/arch/s390x.go` | verified |  |
| go | `src/cmd/compile/internal/liveness/plive.go` | verified |  |
| go | `src/cmd/go/internal/modfetch/codehost/shell.go` | verified |  |
| go | `src/cmd/internal/obj/riscv/anames.go` | verified |  |
| go | `src/compress/lzw/writer_test.go` | verified |  |
| go | `src/crypto/internal/rand/random_fips140v1.28.go` | verified |  |
| go | `src/image/color/ycbcr_test.go` | verified |  |
| go | `src/image/jpeg/reader_test.go` | verified |  |
| go | `src/internal/fuzz/sys_posix.go` | verified |  |
| go | `src/math/bits/make_examples.go` | verified |  |
| go | `src/reflect/nih_test.go` | verified |  |
| go | `src/runtime/vdso_linux_386.go` | verified |  |
| go | `src/simd/archsimd/_gen/simdgen/gen_simdrules.go` | verified |  |
| go | `src/simd/archsimd/clmul_emulated.go` | verified |  |
| go | `src/simd/tofrom_amd64.go` | verified |  |
| go | `test/fixedbugs/bug062.go` | verified |  |
| go | `test/fixedbugs/issue11771.go` | verified |  |
| go | `test/fixedbugs/issue14331.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue15303.go` | verified |  |
| go | `test/fixedbugs/issue46556.go` | verified |  |
| go | `test/fixedbugs/issue47087.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue60945.go` | verified |  |
| go | `test/fixedbugs/issue7740.go` | verified |  |
| go | `test/typeparam/issue47892b.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/auth/author.go` | verified |  |
| grafana | `packages/grafana-data/src/utils/location.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Modal/ModalBase.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/PageLoader/PageLoader.tsx` | verified |  |
| grafana | `pkg/apis/service/v0alpha1/register.go` | verified |  |
| grafana | `pkg/infra/remotecache/redis_storage_integration_test.go` | verified |  |
| grafana | `pkg/server/server.go` | verified |  |
| grafana | `pkg/services/annotations/annotationsimpl/store.go` | verified |  |
| grafana | `pkg/services/dashboardimport/api/api_test.go` | verified |  |
| grafana | `pkg/services/dashboards/accesscontrol_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/licensing/licensing.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginsources/pluginsources_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/ualert/alert_rule_namespace_collation.go` | verified |  |
| grafana | `pkg/services/temp_user/model.go` | verified |  |
| grafana | `pkg/storage/secret/metadata/decrypt_store_test.go` | verified |  |
| grafana | `pkg/storage/unified/search/open_index_list.go` | verified |  |
| grafana | `pkg/storage/unified/sql/service.go` | verified |  |
| grafana | `pkg/storage/unified/testing/sqlkv_search_sections_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/folderownerrefs_test.go` | verified |  |
| grafana | `pkg/tsdb/loki/streaming_test.go` | verified |  |
| grafana | `pkg/util/contextutil_test.go` | verified |  |
| grafana | `public/app/core/utils/query.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/removeVariable.ts` | verified |  |
| grafana | `public/app/features/provisioning/components/Dashboards/DeleteProvisionedDashboardDrawer.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/cloudwatch-logs-test-data/empty.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/query/influxql/visual/AddButton.tsx` | verified |  |
