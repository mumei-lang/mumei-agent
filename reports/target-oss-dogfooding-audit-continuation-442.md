# Target OSS no-LLM dogfooding audit — continuation 442 (batch 443)

Run: 2026-07-23T02:33:47.259322+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/out.go` | verified |  |
| go | `src/cmd/go/internal/web/url_test.go` | verified |  |
| go | `src/cmd/internal/par/queue_test.go` | verified |  |
| go | `src/cmd/link/internal/ld/elf_test.go` | verified |  |
| go | `src/crypto/x509/x509_test.go` | verified |  |
| go | `src/encoding/json/v2/intern_test.go` | verified |  |
| go | `src/go/printer/nodes.go` | verified |  |
| go | `src/image/jpeg/writer.go` | verified |  |
| go | `src/internal/runtime/gc/scan/mem_nounix_test.go` | verified |  |
| go | `src/net/http/cookiejar/jar_test.go` | verified |  |
| go | `src/runtime/sigtab_linux_generic.go` | verified |  |
| go | `src/simd/endianness_test.go` | verified |  |
| go | `test/fixedbugs/bug222.go` | verified |  |
| go | `test/fixedbugs/issue32595.go` | verified |  |
| go | `test/fixedbugs/issue33866.go` | verified |  |
| go | `test/fixedbugs/issue44732.dir/foo/foo.go` | verified |  |
| go | `test/fixedbugs/issue52856.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue6004.go` | verified |  |
| go | `test/mainsig.go` | verified |  |
| go | `test/typeparam/dedup.dir/c.go` | verified |  |
| go | `test/typeparam/issue50437.dir/b.go` | verified |  |
| go | `test/typeparam/mdempsky/21.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/git/sign.go` | verified |  |
| grafana | `e2e-playwright/dashboard-new-layouts/page-objects/Panel.ts` | verified |  |
| grafana | `packages/grafana-flamegraph/src/FlameGraph/colors.ts` | verified |  |
| grafana | `packages/grafana-ui/src/options/builder/text.tsx` | verified |  |
| grafana | `pkg/api/ds_query_diagnostics.go` | verified |  |
| grafana | `pkg/api/dtos/models_test.go` | verified |  |
| grafana | `pkg/api/login.go` | verified |  |
| grafana | `pkg/apis/datasource/v0alpha1/doc.go` | verified |  |
| grafana | `pkg/registry/apis/iam/team/legacy_search.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/metrics_test.go` | verified |  |
| grafana | `pkg/registry/apis/secret/testutils/fake_clock.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/timeinterval/storage.go` | verified |  |
| grafana | `pkg/server/module_server.go` | verified |  |
| grafana | `pkg/services/auth/authimpl/auth_token.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/temp_user.go` | verified |  |
| grafana | `pkg/services/sqlstore/sqlstore_testinfra.go` | verified |  |
| grafana | `pkg/services/supportbundles/bundleregistry/service.go` | verified |  |
| grafana | `pkg/storage/unified/resource/continue.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/settings_stats_auth_test.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/AppChromeService.tsx` | verified |  |
| grafana | `public/app/core/services/journey/JourneyRegistryImpl.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/entities/alertmanagers.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/timeRange.ts` | verified |  |
| grafana | `public/app/features/correlations/useCorrelations.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/SaveDashboard/types.ts` | verified |  |
| grafana | `public/app/features/provisioning/Migrate/FolderEntry.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/utils/getProvisionedMeta.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/constants.ts` | verified |  |
