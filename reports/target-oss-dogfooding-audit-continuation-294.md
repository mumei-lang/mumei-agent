# Target OSS no-LLM dogfooding audit — continuation 294 (batch 295)

Run: 2026-07-22T17:37:57.107420+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/reflectdata/alg_test.go` | verified |  |
| go | `src/cmd/internal/pkgpath/pkgpath_test.go` | verified |  |
| go | `src/crypto/internal/fips140/sha512/sha512block_noasm.go` | verified |  |
| go | `src/crypto/rsa/equal_test.go` | verified |  |
| go | `src/debug/dwarf/line_test.go` | verified |  |
| go | `src/go/ast/directive_test.go` | verified |  |
| go | `src/net/http/cgi/host_test.go` | verified |  |
| go | `src/runtime/msan0.go` | verified |  |
| go | `test/closure5.dir/main.go` | verified |  |
| go | `test/fixedbugs/bug212.go` | verified |  |
| go | `test/fixedbugs/issue4326.dir/q2.go` | verified |  |
| go | `test/fixedbugs/issue4618.go` | verified |  |
| go | `test/fixedbugs/issue46907.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/alerting/v0alpha1/recordingrule_client_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2alpha1/zz_generated.defaults.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/v2beta1_to_v2alpha1.go` | verified |  |
| grafana | `pkg/apis/appplugin/v0alpha1/zz_generated.deepcopy.go` | verified |  |
| grafana | `pkg/infra/features/types.go` | verified |  |
| grafana | `pkg/plugins/apiserver.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/variable_fields.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/informer/historicjob_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/tree_mock.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/config/type.go` | verified |  |
| grafana | `pkg/services/ngalert/api/api_testing.go` | verified |  |
| grafana | `pkg/services/ngalert/api/authorization_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/external_am_syncer.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginstore/store_test.go` | verified |  |
| grafana | `pkg/services/preference/pref.go` | verified |  |
| grafana | `pkg/setting/setting_grpc.go` | verified |  |
| grafana | `pkg/storage/legacysql/dualwrite/dualwriter_continue_token_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/resourcekinds/sync_test.go` | verified |  |
| grafana | `pkg/tsdb/grafana-postgresql-datasource/sqleng/sql_engine_test.go` | verified |  |
| grafana | `pkg/util/scheduler/queue_test.go` | verified |  |
| grafana | `public/app/api/clients/annotation/v0alpha1/types.ts` | verified |  |
| grafana | `public/app/core/components/OptionsUI/number.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/CardEditorRenderer.tsx` | verified |  |
| grafana | `public/app/features/home/useHomeGreeting.ts` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/hooks/useWizardCancellation.ts` | verified |  |
| grafana | `public/app/plugins/panel/piechart/PieChart.tsx` | verified |  |
| grafana | `public/test/helpers/initTemplateSrv.ts` | verified |  |
| prysm | `beacon-chain/rpc/prysm/beacon/validator_count_test.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/proposer_bellatrix_test.go` | verified |  |
| prysm | `beacon-chain/startup/testing.go` | verified |  |
| prysm | `monitoring/prometheus/logrus_collector_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/gloas__operations__voluntary_exit_churn_test.go` | verified |  |
| prysm | `testing/spectest/minimal/bellatrix__operations__voluntary_exit_test.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__fork__upgrade_to_fulu_test.go` | verified |  |
| prysm | `testing/spectest/shared/capella/operations/proposer_slashing.go` | verified |  |
| prysm | `testing/spectest/shared/deneb/operations/bls_to_execution_changes.go` | verified |  |
| prysm | `validator/client/conn_tracker_test.go` | verified |  |
