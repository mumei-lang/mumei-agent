"""Environment variable metadata for the generated reference."""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EnvVar:
    name: str
    category: str
    kind: str
    default: str
    config_field: str | None
    description: str
    sensitive: bool = False


ENV_VARS: tuple[EnvVar, ...] = (
    EnvVar("LLM_API_KEY", "llm", "value", "", "api_key", "API key for the OpenAI-compatible provider; `OPENAI_API_KEY` is used as a fallback.", sensitive=True),
    EnvVar("OPENAI_API_KEY", "llm", "value", "", "api_key", "Fallback API key used when `LLM_API_KEY` is unset.", sensitive=True),
    EnvVar("LLM_BASE_URL", "llm", "value", "", "base_url", "Optional base URL for an OpenAI-compatible API."),
    EnvVar("LLM_MODEL", "llm", "value", "gpt-4o", "model", "Model name; overrides the model selected by `MUMEI_LLM_PROFILE`."),
    EnvVar("LLM_MAX_TOKENS", "llm", "value", "", "llm_max_tokens", "Optional maximum completion tokens; overrides the profile value. Unset or `0` means no explicit limit."),
    EnvVar("LLM_MAX_RETRIES", "llm", "value", "5", "max_retries", "Maximum API retries configured on the OpenAI client."),
    EnvVar("MAX_CONTEXT_TOKENS", "llm", "value", "16000", "max_context_tokens", "Context budget used by the agent."),
    EnvVar("AGENT_STRATEGY", "llm", "value", "single", "strategy", "Default agent strategy name."),
    EnvVar("PROMPT_REPORT_TRUNCATE_CHARS", "llm", "value", "4000", "prompt_report_truncate_chars", "Maximum characters retained in a prompt report."),
    EnvVar("MUMEI_LLM_PROFILE", "llm", "value", "", "llm_profile", "Optional `local-small` or `local-large` preset. Explicit `LLM_MODEL` and `LLM_MAX_TOKENS` values take precedence."),
    EnvVar("MUMEI_AGENT_PRESET", "mumei", "value", "", "agent_preset", "Optional `ci-strict` or `experimental` preset. Explicit environment variables override preset values, which override built-in defaults; unset means no preset."),
    EnvVar("MUMEI_BIN", "mumei", "value", "mumei", "mumei_bin", "Path or command name for the Mumei executable."),
    EnvVar("MUMEI_REPO", "mumei", "value", ".", None, "Mumei checkout path used by commands that need repository assets; defaults to the current directory."),
    EnvVar("MUMEI_MCP_COMMAND", "mcp", "value", "", None, "Optional command used to launch an MCP server; when unset, the built-in default is used."),
    EnvVar("MUMEI_LEAN_REPO", "lean", "value", "", "mumei_lean_repo", "Optional mumei-lean checkout for Lean fallback. The MCP server has a `../mumei-lean` fallback when unset."),
    EnvVar("MUMEI_SPEC_CACHE_DIR", "mumei", "value", "", "spec_cache_dir", "Directory for the opt-in content-addressed spec cache; unset disables the cache."),
    EnvVar("MUMEI_SPEC_SPLIT_CHARS", "mumei", "value", "0", "spec_split_chars", "Character threshold for splitting extracted specs; `0` leaves splitting disabled."),
    EnvVar("MUMEI_DEBUG_JSON_FAIL_DIR", "debug", "value", "", None, "Optional directory where malformed JSON payloads are saved for debugging."),
    EnvVar("MUMEI_DEBUG_JSON_STAMP", "debug", "value", "process ID and current time", None, "Optional filename stamp for debug JSON; otherwise generated from the process ID and current time."),
    EnvVar("CHARTER_LOCK_PATH", "guards", "value", "", "charter_lock_path", "Optional pinned charter file checked by applicable repair and generation flows."),
    EnvVar("CONTROLS_GATE", "guards", "value", "warn", "controls_gate", "Default negative-controls policy for forge and generate. The classic `heal --controls-gate` option defaults to `off` and does not read this variable."),
    EnvVar("CONTRACT_MANIFEST_PATH", "guards", "value", "", "contract_manifest_path", "Optional contract manifest used by validation and generation."),
    EnvVar("ENABLE_CHARTER_GUARD", "guards", "toggle", "true", "enable_charter_guard", "When a lock is configured or discovered, `heal` and `self-correct` reject edits to pinned charter files and abort on malformed lock data; enabled by default."),
    EnvVar("ENABLE_EROSION_GUARD", "guards", "toggle", "true", "enable_erosion_guard", "The `heal` and `self-correct` repair flows reject candidate fixes that remove existing contract clauses; enabled by default."),
    EnvVar("ENABLE_CODE_TO_SPEC", "features", "toggle", "true", "enable_code_to_spec", "The code-to-spec extraction flow returns a disabled result instead of extracting a Mumei spec when this flag is off; enabled by default."),
    EnvVar("ENABLE_GENERATION_HEALTH_CHECK", "features", "toggle", "true", "enable_generation_health_check", "Code-generation flows run `GenerationHealthChecker` against prior examples before accepting generated code; enabled by default."),
    EnvVar("ENABLE_SPEC_CODE_MAPPING", "features", "toggle", "true", "enable_spec_code_mapping", "Generation and repair flows attach or update spec-to-code mapping metadata for generated and fixed code; enabled by default."),
    EnvVar("ENABLE_AMBIGUITY_DETECTION", "features", "toggle", "true", "enable_ambiguity_detection", "`extract-spec` adds LLM-based ambiguity findings to the extraction result when LLM detection is requested; enabled by default."),
    EnvVar("ENABLE_INTENT_TRACKING", "features", "toggle", "true", "enable_intent_tracking", "Spec-refinement attempts compare an accepted refined spec with the original and report intent drift; enabled by default."),
    EnvVar("ENABLE_CONTRACT_ISOLATION", "features", "toggle", "true", "enable_contract_isolation", "Spec refinement loads `CONTRACT_MANIFEST_PATH` and checks each refined spec against that manifest; enabled by default."),
    EnvVar("ENABLE_CEGIS_LOOP", "features", "toggle", "true", "enable_cegis_loop", "The `heal` repair flow attempts CEGIS invariant synthesis for reported `invariant_violated` loops; enabled by default."),
    EnvVar("ENABLE_DENSE_PROPERTIES", "features", "toggle", "false", "enable_dense_properties", "Generation applies the dense-property pass to generated contract clauses before verification; opt-in and off by default."),
    EnvVar("ENABLE_LATENT_DEBUG", "debug", "toggle", "false", "enable_latent_debug", "Repair flows try latent-space decoding before the standard rule-based and LLM fixes; opt-in and off by default."),
    EnvVar("ENABLE_LATENT_PROTOCOL", "features", "toggle", "false", "enable_latent_protocol", "The MCP server exposes latent-message tools when this protocol is enabled; opt-in and off by default."),
    EnvVar("ENABLE_NLAE_MULTI_AGENT", "features", "toggle", "false", "enable_nlae_multi_agent", "The NLAE pipeline runs multi-agent collaboration rounds instead of its single-agent path; opt-in and off by default."),
    EnvVar("ENABLE_SELF_CORRECTION", "features", "toggle", "false", "enable_self_correction", "`heal` switches to structured self-correction and `proliferate` applies it to failed generated code; opt-in and off by default."),
    EnvVar("ENABLE_VISUALIZER_SYNC", "features", "toggle", "false", "visualizer_sync", "The `heal` flow sends verification reports to the visualizer after repair attempts; opt-in and off by default."),
    EnvVar("ENABLE_LEAN_AI_PROOF", "lean", "toggle", "false", "enable_lean_ai_proof", "The `proliferate` flow asks an LLM for Lean proofs of unknown obligations; opt-in and off by default, and disabled without an API key or in `CI_FIXTURE_MODE`."),
    EnvVar("CI_FIXTURE_MODE", "ci", "toggle", "false", "ci_fixture_mode", "Fixture-mode runs suppress the `proliferate` flow's LLM-generated Lean proof attempts; off by default."),
    EnvVar("CEGIS_ESCALATE_TO_LEAN", "lean", "toggle", "true", "cegis_escalate_to_lean", "When the `heal` CEGIS loop cannot find an invariant, it creates a Lean escalation bundle; enabled by default."),
    EnvVar("CEGIS_MAX_ITERATIONS", "features", "value", "10", "cegis_max_iterations", "Iteration budget for invariant synthesis attempted by `heal` on loop-related failures."),
    EnvVar("NLAE_MULTI_AGENT_MAX_ROUNDS", "features", "value", "2", "nlae_multi_agent_max_rounds", "Maximum collaboration rounds for the opt-in NLAE multi-agent pipeline."),
    EnvVar("INTENT_DRIFT_THRESHOLD", "features", "value", "0.7", "intent_drift_threshold", "Intent-preservation scores below this threshold are reported as drift during spec refinement."),
    EnvVar("SELF_CORRECTION_MAX_ATTEMPTS", "features", "value", "10", "self_correction_max_attempts", "Maximum structured repair attempts in `self-correct` and self-correction-enabled `heal` or `proliferate` flows."),
    EnvVar("SELF_CORRECTION_CONVERGENCE_THRESHOLD", "features", "value", "2", "self_correction_convergence_threshold", "Number of consecutive successful repair iterations required before structured self-correction stops as converged."),
    EnvVar("SELF_CORRECTION_MAX_TOKENS", "features", "value", "10000", "self_correction_max_tokens", "Cumulative token-cost ceiling for the structured self-correction loop."),
    EnvVar("PROLIFERATE_FORGE_WORKERS", "features", "value", "4", None, "Maximum parallel forge workers; unset uses up to four workers, capped by the number of specs."),
    EnvVar("CORE_AXIOM_PATH", "mumei", "value", "auto-detected; otherwise `std/core.mm`", "core_axiom_path", "Override the core axiom file path; when unset, a sibling Mumei checkout is searched before `std/core.mm`."),
    EnvVar("INJECT_CORE_AXIOMS", "mumei", "toggle", "true", "inject_core_axioms", "Generation prompts for `std/` modules include the configured core axioms; enabled by default, while `false`, `0`, `no`, and `off` disable injection without whitespace trimming."),
    EnvVar("LEAN_AI_PROOF_MAX_ATTEMPTS", "lean", "value", "3", "lean_ai_proof_max_attempts", "Maximum attempts for AI-generated Lean proofs."),
    EnvVar("LEAN_AI_PROOF_EVIDENCE_DIR", "lean", "value", "", "lean_ai_proof_evidence_dir", "Optional directory for Lean proof evidence."),
    EnvVar("MCP_SAMPLING_MAX_TOKENS", "mcp", "value", "4096", None, "Completion-token limit for LLM requests made through MCP sampling."),
    EnvVar("USE_MCP_CLIENT", "mcp", "toggle", "false", None, "`heal` and `proliferate` route Mumei verification through the MCP client when available and otherwise fall back to the CLI; opt-in and off by default."),
    EnvVar("USE_MCP_SAMPLING", "mcp", "toggle", "false", "use_mcp_sampling", "LLM calls through the MCP server can use request-context sampling instead of the configured provider; opt-in and off by default, though the Devin wrapper enables it when unset."),
    EnvVar("PREFER_MCP_GAPS", "mcp", "toggle", "false", None, "Proliferation delegates gap analysis to the MCP server when available and falls back to the local analyzer otherwise; opt-in and off by default."),
    EnvVar("LATENT_PROTOCOL_KEY", "mcp", "value", "", None, "Optional encryption key for latent-protocol state.", sensitive=True),
    EnvVar("LATENT_PROTOCOL_AUDIT_LOG", "mcp", "value", "", None, "Optional path for the latent-protocol audit log."),
    EnvVar("MUMEI_AGENT_MCP_LOG", "mcp", "value", "$HOME/mumei_agent_mcp.log", None, "Log file for the Devin MCP wrapper script."),
    EnvVar("MUMEI_AGENT_MCP_LOG_MAX_KB", "mcp", "value", "10240", None, "Maximum MCP wrapper log size in KiB before rotation."),
    EnvVar("OTEL_ENABLED", "observability", "toggle", "false", None, "When the optional OpenTelemetry packages are installed, `heal`, `generate`, `forge`, and `proliferate` emit traces and metrics; opt-in and off by default."),
    EnvVar("OTEL_EXPORTER_OTLP_PROTOCOL", "observability", "value", "grpc", None, "OTLP exporter protocol: `grpc`, `http/protobuf`, or `http/json`; values beginning with `http` select the HTTP exporter."),
    EnvVar("OTEL_EXPORTER_OTLP_ENDPOINT", "observability", "value", "SDK default", None, "OTLP endpoint consumed by the OpenTelemetry exporter SDK."),
    EnvVar("GITHUB_TOKEN", "ci", "value", "", None, "GitHub API token used by publish operations; unset outside configured CI or local GitHub workflows.", sensitive=True),
    EnvVar("GITHUB_OWNER", "ci", "value", "", None, "Default GitHub repository owner for publish operations; may be supplied on the command line instead."),
    EnvVar("GITHUB_REPO", "ci", "value", "", None, "Default GitHub repository name for publish operations; may be supplied on the command line instead."),
    EnvVar("GITHUB_BASE_REF", "ci", "value", "", None, "Optional GitHub Actions base branch used for report comparisons."),
    EnvVar("GITHUB_RUN_ID", "ci", "value", "", None, "GitHub Actions run identifier used to label triage metrics."),
    EnvVar("GITHUB_STEP_SUMMARY", "ci", "value", "", None, "GitHub Actions summary-file path; unset outside GitHub Actions."),
    EnvVar("GITHUB_OUTPUT", "ci", "value", "", None, "GitHub Actions output-file path; unset outside GitHub Actions."),
)


_ENV_NAME_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_PYTHON_COMMENT_ENV_PATTERNS = (
    re.compile(r"""os\s*\.\s*getenv\s*\(\s*['"]([A-Z][A-Z0-9_]*)['"]"""),
    re.compile(r"""os\s*\.\s*environ\s*\.\s*(?:get|setdefault|pop)\s*\(\s*['"]([A-Z][A-Z0-9_]*)['"]"""),
    re.compile(r"""os\s*\.\s*environ\s*\[\s*['"]([A-Z][A-Z0-9_]*)['"]\s*\](?!\s*(?:=|\+=|-=|\*=|/=|//=|%=|&=|\|=|\^=|<<=|>>=|\*\*=))"""),
    re.compile(r"""['"]([A-Z][A-Z0-9_]*)['"]\s+in\s+os\s*\.\s*environ"""),
)
_SHELL_ENV_PATTERN = re.compile(r"\$\{([A-Z][A-Z0-9_]*)(?::-?[^}]*)?\}")


def scan_environment_names(repo_root: Path) -> set[str]:
    """Find literal environment reads in agent Python and shell scripts."""
    names: set[str] = set()
    for directory in (repo_root / "agent", repo_root / "scripts"):
        for path in directory.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            names.update(scan_environment_source(source, path.suffix))
    return names


def scan_environment_source(source: str, suffix: str = ".py") -> set[str]:
    if suffix == ".sh":
        return set(_SHELL_ENV_PATTERN.findall(source))
    if suffix != ".py":
        return set()

    names = _comment_environment_names(source)
    try:
        module = ast.parse(source)
    except SyntaxError:
        return names

    constants = _module_environment_constants(module)
    helpers = _module_environment_helpers(module)
    for node in ast.walk(module):
        if isinstance(node, ast.Call):
            argument = _environment_read_argument(node)
            if argument is not None:
                name = _environment_name(argument, constants)
                if name is not None:
                    names.add(name)

            if isinstance(node.func, ast.Name):
                if node.func.id in {"OTLPSpanExporter", "OTLPMetricExporter"}:
                    names.add("OTEL_EXPORTER_OTLP_ENDPOINT")
                for parameter, position in helpers.get(node.func.id, ()):
                    helper_argument = _helper_call_argument(node, parameter, position)
                    if helper_argument is not None:
                        name = _environment_name(helper_argument, constants)
                        if name is not None:
                            names.add(name)
        elif (
            isinstance(node, ast.Subscript)
            and _is_os_environ(node.value)
            and isinstance(node.ctx, ast.Load)
        ):
            name = _environment_name(node.slice, constants)
            if name is not None:
                names.add(name)
        elif isinstance(node, ast.Compare):
            for operator, comparator in zip(node.ops, node.comparators):
                if isinstance(operator, (ast.In, ast.NotIn)) and _is_os_environ(
                    comparator
                ):
                    name = _environment_name(node.left, constants)
                    if name is not None:
                        names.add(name)
    return names


def _is_os_environ(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _is_os_getenv_call(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "getenv"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "os"
    )


def _is_os_environ_method_call(node: ast.Call, methods: set[str]) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr in methods
        and _is_os_environ(node.func.value)
    )


def _environment_read_argument(node: ast.Call) -> ast.AST | None:
    if not node.args:
        return None
    if _is_os_getenv_call(node) or _is_os_environ_method_call(
        node, {"get", "setdefault", "pop"}
    ):
        return node.args[0]
    return None


def _environment_name(node: ast.AST, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if _ENV_NAME_PATTERN.fullmatch(node.value) else None
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _module_environment_constants(module: ast.Module) -> dict[str, str]:
    constants: dict[str, str] = {}
    for statement in module.body:
        if isinstance(statement, ast.Assign):
            targets = statement.targets
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
            value = statement.value
        else:
            continue
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        if not _ENV_NAME_PATTERN.fullmatch(value.value):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = value.value
    return constants


def _is_str_annotation(annotation: ast.expr | None) -> bool:
    return (
        isinstance(annotation, ast.Name)
        and annotation.id == "str"
        or isinstance(annotation, ast.Constant)
        and annotation.value == "str"
    )


def _helper_reads_parameter(function: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        reads_env = _is_os_getenv_call(node) or _is_os_environ_method_call(
            node, {"get"}
        )
        if reads_env and isinstance(node.args[0], ast.Name) and node.args[0].id == name:
            return True
    return False


def _module_environment_helpers(
    module: ast.Module,
) -> dict[str, list[tuple[str, int | None]]]:
    helpers: dict[str, list[tuple[str, int | None]]] = {}
    for statement in module.body:
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        positional = statement.args.posonlyargs + statement.args.args
        for index, argument in enumerate(positional):
            if _is_str_annotation(argument.annotation) and _helper_reads_parameter(
                statement, argument.arg
            ):
                helpers.setdefault(statement.name, []).append((argument.arg, index))
        for argument in statement.args.kwonlyargs:
            if _is_str_annotation(argument.annotation) and _helper_reads_parameter(
                statement, argument.arg
            ):
                helpers.setdefault(statement.name, []).append((argument.arg, None))
    return helpers


def _helper_call_argument(
    call: ast.Call, parameter: str, position: int | None
) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == parameter:
            return keyword.value
    if position is not None and len(call.args) > position:
        return call.args[position]
    return None


def _comment_environment_names(source: str) -> set[str]:
    names: set[str] = set()
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type == tokenize.COMMENT:
                for pattern in _PYTHON_COMMENT_ENV_PATTERNS:
                    names.update(pattern.findall(token.string))
    except (IndentationError, tokenize.TokenError):
        pass
    return names


def referenced_environment_names(repo_root: Path) -> set[str]:
    """Find registry names read in the scanned source tree."""
    names: set[str] = set()
    registry_path = Path(__file__).resolve()
    for directory in (repo_root / "agent", repo_root / "scripts"):
        for path in directory.rglob("*"):
            if (
                path.is_file()
                and path.resolve() != registry_path
                and path.suffix in {".py", ".sh"}
                and "__pycache__" not in path.parts
            ):
                try:
                    source = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                names.update(scan_environment_source(source, path.suffix))
    return names & {entry.name for entry in ENV_VARS}
