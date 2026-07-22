# Target OSS no-LLM dogfooding audit — continuation 286 (batch 287)

Run: 2026-07-22T17:08:55.711391+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/internal/objabi/head.go` | verified |  |
| go | `src/crypto/hpke/aead_fips140v1.0.go` | verified |  |
| go | `src/go/types/package.go` | verified |  |
| go | `src/internal/abi/compiletype.go` | verified |  |
| go | `src/internal/abi/funcpc_gccgo.go` | verified |  |
| go | `src/internal/goos/zgoos_darwin.go` | verified |  |
| go | `src/maps/iter.go` | verified |  |
| go | `src/path/filepath/path_test.go` | verified |  |
| go | `src/unique/clone_test.go` | verified |  |
| go | `test/dwarf/dwarf.dir/z16.go` | verified |  |
| go | `test/fixedbugs/bug363.go` | verified |  |
| go | `test/fixedbugs/issue25055.go` | verified |  |
| go | `test/fixedbugs/issue35073b.go` | verified |  |
| grafana | `apps/alerting/rules/plugin/src/generated/rulesequence/v0alpha1/types.metadata.gen.ts` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1beta1/logsdrilldowndefaultlabels_object_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/pullrequestjoboptions.go` | verified |  |
| grafana | `apps/scope/pkg/apis/scope/v0alpha1/zz_generated.deepcopy.go` | verified |  |
| grafana | `kinds/gen.go` | verified |  |
| grafana | `pkg/api/org_users.go` | verified |  |
| grafana | `pkg/api/swagger_responses.go` | verified |  |
| grafana | `pkg/expr/errors_test.go` | verified |  |
| grafana | `pkg/plugins/codegen/pfs/plugin.go` | verified |  |
| grafana | `pkg/registry/apis/ofrep/static.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/mocks/StatusPatcher.go` | verified |  |
| grafana | `pkg/registry/apps/logsdrilldown/authorizer.go` | verified |  |
| grafana | `pkg/services/authn/clients/ext_jwt.go` | verified |  |
| grafana | `pkg/services/authz/rbac/resolver.go` | verified |  |
| grafana | `pkg/services/extsvcauth/models.go` | verified |  |
| grafana | `pkg/services/ngalert/remote/client/alertmanager.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/tracing_header_middleware.go` | verified |  |
| grafana | `pkg/storage/unified/search/lock_objstore.go` | verified |  |
| grafana | `pkg/storage/unified/search/remote_index_store_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/sqltemplate/sqltemplate.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/resources/dimension_keys_request.go` | verified |  |
| grafana | `pkg/tsdb/loki/sql.go` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/filter/useApplyDefaultSearch.ts` | verified |  |
| grafana | `public/app/features/variables/pickers/OptionsPicker/reducer.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/cloudwatch-sql/completion/tokenUtils.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/monaco-query-field/monaco-completion-provider/situation.ts` | verified |  |
| prysm | `beacon-chain/db/filesystem/blob_test.go` | verified |  |
| prysm | `beacon-chain/db/kv/backup_test.go` | verified |  |
| prysm | `beacon-chain/db/slasherkv/log.go` | verified |  |
| prysm | `beacon-chain/db/slasherkv/schema.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/debug/p2p.go` | verified |  |
| prysm | `beacon-chain/state/stategen/hot_state_cache_test.go` | verified |  |
| prysm | `beacon-chain/sync/validate_attester_slashing_test.go` | verified |  |
| prysm | `consensus-types/blocks/getters_test.go` | verified |  |
| prysm | `consensus-types/blocks/proto.go` | verified |  |
| prysm | `testing/spectest/mainnet/deneb__operations__deposit_test.go` | verified |  |
| prysm | `testing/spectest/shared/fulu/operations/withdrawals.go` | verified |  |
