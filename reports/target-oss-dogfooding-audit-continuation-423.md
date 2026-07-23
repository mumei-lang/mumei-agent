# Target OSS no-LLM dogfooding audit — continuation 423 (batch 424)

Run: 2026-07-23T01:38:17.611345+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/numberlines.go` | verified |  |
| go | `src/cmd/compile/internal/wasm/ssa.go` | verified |  |
| go | `src/cmd/go/internal/modload/help.go` | verified |  |
| go | `src/cmd/gofmt/simplify.go` | verified |  |
| go | `src/cmd/internal/robustio/robustio_other.go` | verified |  |
| go | `src/crypto/internal/fips140/notboring.go` | verified |  |
| go | `src/internal/poll/splice_linux_test.go` | verified |  |
| go | `src/internal/routebsd/binary.go` | verified |  |
| go | `src/internal/routebsd/message_test.go` | verified |  |
| go | `src/internal/runtime/atomic/xchg8.go` | verified |  |
| go | `src/log/slog/internal/buffer/buffer_test.go` | verified |  |
| go | `src/net/tcpsock.go` | verified |  |
| go | `src/path/filepath/example_unix_walk_test.go` | verified |  |
| go | `src/runtime/os_freebsd_amd64.go` | verified |  |
| go | `src/syscall/forkpipe.go` | verified |  |
| go | `src/syscall/zerrors_aix_ppc64.go` | verified |  |
| go | `test/codegen/atomics.go` | verified |  |
| go | `test/dwarf/dwarf.dir/z11.go` | verified |  |
| go | `test/fixedbugs/notinheap.go` | verified |  |
| go | `test/typeparam/issue49432.go` | verified |  |
| go | `test/typeparam/issue49659.dir/a.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2alpha1/dashboard_object_gen.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1alpha1/logsdrilldowndefaults_status_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/quotas/tracker_test.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/matchers/types.ts` | verified |  |
| grafana | `packages/grafana-e2e-selectors/src/selectors/components.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/components/PanelDataErrorView.tsx` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginMeta/types/meta/types.status.gen.ts` | verified |  |
| grafana | `packages/grafana-sql/src/components/QueryEditor.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/utils/adjustDateForReactCalendar.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Segment/types.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/geo/OpenLayersProvider.tsx` | verified |  |
| grafana | `pkg/api/search.go` | verified |  |
| grafana | `pkg/infra/nats/publisher.go` | verified |  |
| grafana | `pkg/infra/usagestats/statscollector/concurrent_users_test.go` | verified |  |
| grafana | `pkg/registry/apis/datasource/sub_access.go` | verified |  |
| grafana | `pkg/registry/apis/secret/encryption/cipher/provider/cipher_aesgcm.go` | verified |  |
| grafana | `pkg/registry/apps/correlations/legacy_storage.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_query.go` | verified |  |
| grafana | `pkg/services/ngalert/api/prometheus/util_test.go` | verified |  |
| grafana | `pkg/services/signingkeys/signingkeysimpl/service_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/scope_migrator.go` | verified |  |
| grafana | `pkg/storage/unified/resource/secure.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/kinds/dataquery/types_dataquery_gen.go` | verified |  |
| grafana | `pkg/tsdb/grafana-testdata-datasource/sims/utils.go` | verified |  |
| grafana | `public/app/core/components/SplashScreenModal/splashContent.ts` | verified |  |
| grafana | `public/app/core/crash/index.ts` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useOrphanedResourceActions.ts` | verified |  |
| grafana | `public/app/plugins/panel/barchart/module.tsx` | verified |  |
| grafana | `public/test/core/redux/reducerTester.ts` | verified |  |
