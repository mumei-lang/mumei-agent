# Target OSS no-LLM dogfooding audit — continuation 346 (batch 347)

Run: 2026-07-22T20:56:53.155588+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue8694.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/_gen/S390XOps.go` | verified |  |
| go | `src/encoding/json/v2/errors.go` | verified |  |
| go | `src/flag/example_textvar_test.go` | verified |  |
| go | `src/net/http/internal/ascii/print_test.go` | verified |  |
| go | `src/reflect/example_test.go` | verified |  |
| go | `src/sort/example_keys_test.go` | verified |  |
| go | `src/syscall/exec_linux_test.go` | verified |  |
| go | `test/chan/select8.go` | verified |  |
| go | `test/fixedbugs/bug016.go` | verified |  |
| go | `test/fixedbugs/bug322.dir/lib.go` | verified |  |
| go | `test/fixedbugs/issue15514.dir/a.go` | verified |  |
| go | `test/typeparam/dedup.go` | verified |  |
| go | `test/typeparam/issue45547.go` | verified |  |
| go | `test/typeparam/issue47684.go` | verified |  |
| go | `test/typeparam/issue47775.dir/b.go` | verified |  |
| go | `test/typeparam/issue49246.go` | verified |  |
| go | `test/typeparam/recoverimp.dir/main.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/github/connectionconfig_mock.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/plugins/grafana-extensionexample2-app/components/App/App.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/RadialGauge/effects.tsx` | verified |  |
| grafana | `pkg/plugins/backendplugin/grpcplugin/log_wrapper_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/connection_status_patcher_mock.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/shutdown_test.go` | verified |  |
| grafana | `pkg/registry/apps/logsdrilldown/register.go` | verified |  |
| grafana | `pkg/registry/apps/plugins/accesscontrol.go` | verified |  |
| grafana | `pkg/services/accesscontrol/mock/mock.go` | verified |  |
| grafana | `pkg/services/ngalert/api/util_test.go` | verified |  |
| grafana | `pkg/services/user/userimpl/verifier.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/migratejob_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/stats_test.go` | verified |  |
| grafana | `pkg/util/testutil/testutil.go` | verified |  |
| grafana | `public/app/features/admin/ldap/LdapTestDrawer.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/abilities/types.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/TransformationsEditor/TransformationFilter.tsx` | verified |  |
| grafana | `public/app/features/logs/components/getLogRowStyles.ts` | verified |  |
| grafana | `public/app/features/logs/components/panel/__mocks__/LogListContext.tsx` | verified |  |
| grafana | `public/app/features/transformers/extractFields/extractFields.ts` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-postgresql-datasource/configuration/useAutoDetectFeatures.ts` | verified |  |
| grafana | `public/app/plugins/panel/nodeGraph/layeredLayout.js` | verified |  |
| prysm | `api/client/event/utils_test.go` | verified |  |
| prysm | `beacon-chain/cache/subnet_ids_test.go` | verified |  |
| prysm | `beacon-chain/rpc/core/duties_test.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/proposer_execution_payload.go` | verified |  |
| prysm | `config/params/minimal_config.go` | verified |  |
| prysm | `testing/spectest/shared/capella/sanity/block_processing.yaml.go` | verified |  |
| prysm | `testing/spectest/shared/common/light_client/single_merkle_proof.go` | verified |  |
| prysm | `time/utils.go` | verified |  |
| prysm | `validator/client/beacon-api/beacon_api_helpers_test.go` | verified |  |
| prysm | `validator/web/log.go` | verified |  |
