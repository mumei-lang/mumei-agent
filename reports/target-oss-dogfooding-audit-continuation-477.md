# Target OSS no-LLM dogfooding audit — continuation 477 (batch 478)

Run: 2026-07-23T05:01:38.067340+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/dom.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/value.go` | verified |  |
| go | `src/cmd/link/internal/riscv64/asm.go` | verified |  |
| go | `src/crypto/internal/fips140/rsa/largeexponent.go` | verified |  |
| go | `src/internal/abi/abi.go` | verified |  |
| go | `src/internal/nettest/listener.go` | verified |  |
| go | `src/internal/zstd/literals.go` | verified |  |
| go | `src/io/fs/stat.go` | verified |  |
| go | `src/math/big/ftoa.go` | verified |  |
| go | `src/net/http/alpn_test.go` | verified |  |
| go | `src/os/dirent_solaris.go` | verified |  |
| go | `src/path/filepath/symlink_unix.go` | verified |  |
| go | `src/runtime/pprof/mprof_test.go` | verified |  |
| go | `src/runtime/pprof/proto_windows.go` | verified |  |
| go | `src/sort/example_search_test.go` | verified |  |
| go | `src/syscall/env_unix.go` | verified |  |
| go | `src/syscall/syscall_solaris_amd64.go` | verified |  |
| go | `test/codegen/floats.go` | verified |  |
| go | `test/fixedbugs/issue32454.go` | verified |  |
| go | `test/fixedbugs/issue45344.go` | verified |  |
| go | `test/fixedbugs/issue53309.go` | verified |  |
| go | `test/fixedbugs/issue62498.go` | verified |  |
| go | `test/typeparam/issue48538.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/manifestdata/alerting_manifest.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1beta1/logsdrilldowndefaultlabels_codec_gen.go` | verified |  |
| grafana | `packages/grafana-data/src/field/overrides/processors.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginSettings/logging.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/SecretTextArea/SecretTextArea.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Select/Select.tsx` | verified |  |
| grafana | `pkg/api/plugin_metrics.go` | verified |  |
| grafana | `pkg/apis/iam/v0alpha1/doc.go` | verified |  |
| grafana | `pkg/plugins/instrumentationutils/request_status_test.go` | verified |  |
| grafana | `pkg/services/apiserver/builder/helper_test.go` | verified |  |
| grafana | `pkg/services/dashboardsnapshots/store.go` | verified |  |
| grafana | `pkg/services/live/pipeline/tree/bytesconv.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/routes.go` | verified |  |
| grafana | `pkg/services/ngalert/store/alertmanager.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/installsync/syncer_test.go` | verified |  |
| grafana | `pkg/services/secrets/fakes/fake_store.go` | verified |  |
| grafana | `pkg/services/secrets/kvstore/migrations/migrator.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/dashboard_snapshot_mig.go` | verified |  |
| grafana | `pkg/services/team/sortopts/sortopts.go` | verified |  |
| grafana | `pkg/storage/unified/apistore/permissions.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/git/job_commit_author_test.go` | verified |  |
| grafana | `public/app/core/components/RolePicker/RolePickerMenu.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/components/ListItem.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/SharePublicDashboard/useGetUnsupportedDataSources.ts` | verified |  |
| grafana | `public/app/features/plugins/admin/mocks/mockHelpers.ts` | verified |  |
| grafana | `public/app/features/provisioning/utils/getFormErrors.ts` | verified |  |
| grafana | `public/app/plugins/panel/alertlist/module.tsx` | verified |  |
