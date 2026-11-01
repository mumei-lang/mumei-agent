"""Environment variable metadata for the generated reference."""

from __future__ import annotations

import re
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


ENV_VARS: tuple[EnvVar, ...] = (
    EnvVar("LLM_API_KEY", "llm", "value", "", "api_key", "API key for the OpenAI-compatible provider; `OPENAI_API_KEY` is used as a fallback."),
    EnvVar("OPENAI_API_KEY", "llm", "value", "", "api_key", "Fallback API key used when `LLM_API_KEY` is unset."),
    EnvVar("LLM_BASE_URL", "llm", "value", "", "base_url", "Optional base URL for an OpenAI-compatible API."),
    EnvVar("LLM_MODEL", "llm", "value", "gpt-4o", "model", "Model name; overrides the model selected by `MUMEI_LLM_PROFILE`."),
    EnvVar("LLM_MAX_TOKENS", "llm", "value", "", "llm_max_tokens", "Optional maximum completion tokens; overrides the profile value. Unset or `0` means no explicit limit."),
    EnvVar("LLM_MAX_RETRIES", "llm", "value", "5", "max_retries", "Maximum API retries configured on the OpenAI client."),
    EnvVar("MAX_CONTEXT_TOKENS", "llm", "value", "16000", "max_context_tokens", "Context budget used by the agent."),
    EnvVar("AGENT_STRATEGY", "llm", "value", "single", "strategy", "Default agent strategy name."),
    EnvVar("PROMPT_REPORT_TRUNCATE_CHARS", "llm", "value", "4000", "prompt_report_truncate_chars", "Maximum characters retained in a prompt report."),
    EnvVar("MUMEI_LLM_PROFILE", "llm", "value", "", "llm_profile", "Optional `local-small` or `local-large` preset. Explicit `LLM_MODEL` and `LLM_MAX_TOKENS` values take precedence."),
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
    EnvVar("ENABLE_CHARTER_GUARD", "guards", "toggle", "true", "enable_charter_guard", "Enable the charter guard by default."),
    EnvVar("ENABLE_EROSION_GUARD", "guards", "toggle", "true", "enable_erosion_guard", "Enable the contract-erosion guard by default."),
    EnvVar("ENABLE_CODE_TO_SPEC", "features", "toggle", "true", "enable_code_to_spec", "Enable code-to-spec support by default."),
    EnvVar("ENABLE_GENERATION_HEALTH_CHECK", "features", "toggle", "true", "enable_generation_health_check", "Enable the generation health check by default."),
    EnvVar("ENABLE_SPEC_CODE_MAPPING", "features", "toggle", "true", "enable_spec_code_mapping", "Enable spec-to-code mapping by default."),
    EnvVar("ENABLE_AMBIGUITY_DETECTION", "features", "toggle", "true", "enable_ambiguity_detection", "Enable ambiguity detection by default."),
    EnvVar("ENABLE_INTENT_TRACKING", "features", "toggle", "true", "enable_intent_tracking", "Enable intent tracking by default."),
    EnvVar("ENABLE_CONTRACT_ISOLATION", "features", "toggle", "true", "enable_contract_isolation", "Enable contract isolation by default."),
    EnvVar("ENABLE_CEGIS_LOOP", "features", "toggle", "true", "enable_cegis_loop", "Enable the CEGIS loop by default."),
    EnvVar("ENABLE_DENSE_PROPERTIES", "features", "toggle", "false", "enable_dense_properties", "Opt in to dense property generation."),
    EnvVar("ENABLE_LATENT_DEBUG", "debug", "toggle", "false", "enable_latent_debug", "Opt in to latent-state debugging."),
    EnvVar("ENABLE_LATENT_PROTOCOL", "features", "toggle", "false", "enable_latent_protocol", "Opt in to the latent protocol."),
    EnvVar("ENABLE_NLAE_MULTI_AGENT", "features", "toggle", "false", "enable_nlae_multi_agent", "Opt in to NLAE multi-agent orchestration."),
    EnvVar("ENABLE_SELF_CORRECTION", "features", "toggle", "false", "enable_self_correction", "Opt in to the self-correction loop."),
    EnvVar("ENABLE_VISUALIZER_SYNC", "features", "toggle", "false", "visualizer_sync", "Opt in to visualizer synchronization."),
    EnvVar("ENABLE_LEAN_AI_PROOF", "lean", "toggle", "false", "enable_lean_ai_proof", "Opt in to LLM-generated Lean proofs. It is effectively forced off without an API key or when `CI_FIXTURE_MODE` is enabled."),
    EnvVar("CI_FIXTURE_MODE", "ci", "toggle", "false", "ci_fixture_mode", "Use deterministic fixture behavior; also disables AI Lean proof generation."),
    EnvVar("CEGIS_ESCALATE_TO_LEAN", "lean", "toggle", "true", "cegis_escalate_to_lean", "Enable escalation of unresolved CEGIS cases to Lean by default."),
    EnvVar("CEGIS_MAX_ITERATIONS", "features", "value", "10", "cegis_max_iterations", "Maximum CEGIS iterations."),
    EnvVar("NLAE_MULTI_AGENT_MAX_ROUNDS", "features", "value", "2", "nlae_multi_agent_max_rounds", "Maximum NLAE multi-agent rounds."),
    EnvVar("INTENT_DRIFT_THRESHOLD", "features", "value", "0.7", "intent_drift_threshold", "Intent-drift threshold used by the intent-tracking feature."),
    EnvVar("SELF_CORRECTION_MAX_ATTEMPTS", "features", "value", "10", "self_correction_max_attempts", "Maximum self-correction attempts."),
    EnvVar("SELF_CORRECTION_CONVERGENCE_THRESHOLD", "features", "value", "2", "self_correction_convergence_threshold", "Convergence threshold for self-correction."),
    EnvVar("SELF_CORRECTION_MAX_TOKENS", "features", "value", "10000", "self_correction_max_tokens", "Token budget for self-correction requests."),
    EnvVar("PROLIFERATE_FORGE_WORKERS", "features", "value", "4", None, "Maximum parallel forge workers; unset uses up to four workers, capped by the number of specs."),
    EnvVar("CORE_AXIOM_PATH", "mumei", "value", "auto-detected; otherwise `std/core.mm`", "core_axiom_path", "Override the core axiom file path; when unset, a sibling Mumei checkout is searched before `std/core.mm`."),
    EnvVar("INJECT_CORE_AXIOMS", "mumei", "toggle", "true", "inject_core_axioms", "Inject core axioms by default. The values `false`, `0`, `no`, and `off` disable injection; other values enable it without trimming whitespace."),
    EnvVar("LEAN_AI_PROOF_MAX_ATTEMPTS", "lean", "value", "3", "lean_ai_proof_max_attempts", "Maximum attempts for AI-generated Lean proofs."),
    EnvVar("LEAN_AI_PROOF_EVIDENCE_DIR", "lean", "value", "", "lean_ai_proof_evidence_dir", "Optional directory for Lean proof evidence."),
    EnvVar("MCP_SAMPLING_MAX_TOKENS", "mcp", "value", "4096", None, "Completion-token limit for LLM requests made through MCP sampling."),
    EnvVar("USE_MCP_CLIENT", "mcp", "toggle", "false", None, "Opt in to using the configured MCP client."),
    EnvVar("USE_MCP_SAMPLING", "mcp", "toggle", "false", "use_mcp_sampling", "Opt in to LLM requests through MCP sampling. The Devin wrapper script enables it by default when unset."),
    EnvVar("PREFER_MCP_GAPS", "mcp", "toggle", "false", None, "Prefer gap data from MCP when the MCP path is available."),
    EnvVar("LATENT_PROTOCOL_KEY", "mcp", "value", "", None, "Optional encryption key for latent-protocol state."),
    EnvVar("LATENT_PROTOCOL_AUDIT_LOG", "mcp", "value", "", None, "Optional path for the latent-protocol audit log."),
    EnvVar("MUMEI_AGENT_MCP_LOG", "mcp", "value", "$HOME/mumei_agent_mcp.log", None, "Log file for the Devin MCP wrapper script."),
    EnvVar("MUMEI_AGENT_MCP_LOG_MAX_KB", "mcp", "value", "10240", None, "Maximum MCP wrapper log size in KiB before rotation."),
    EnvVar("OTEL_ENABLED", "observability", "toggle", "false", None, "Enable OpenTelemetry instrumentation when the optional dependencies are installed."),
    EnvVar("OTEL_EXPORTER_OTLP_PROTOCOL", "observability", "value", "grpc", None, "OTLP exporter protocol: `grpc`, `http/protobuf`, or `http/json`; values beginning with `http` select the HTTP exporter."),
    EnvVar("OTEL_EXPORTER_OTLP_ENDPOINT", "observability", "value", "SDK default", None, "OTLP endpoint consumed by the OpenTelemetry exporter SDK."),
    EnvVar("GITHUB_TOKEN", "ci", "value", "", None, "GitHub API token used by publish operations; unset outside configured CI or local GitHub workflows."),
    EnvVar("GITHUB_OWNER", "ci", "value", "", None, "Default GitHub repository owner for publish operations; may be supplied on the command line instead."),
    EnvVar("GITHUB_REPO", "ci", "value", "", None, "Default GitHub repository name for publish operations; may be supplied on the command line instead."),
    EnvVar("GITHUB_BASE_REF", "ci", "value", "", None, "Optional GitHub Actions base branch used for report comparisons."),
    EnvVar("GITHUB_RUN_ID", "ci", "value", "", None, "GitHub Actions run identifier used to label triage metrics."),
    EnvVar("GITHUB_STEP_SUMMARY", "ci", "value", "", None, "GitHub Actions summary-file path; unset outside GitHub Actions."),
    EnvVar("GITHUB_OUTPUT", "ci", "value", "", None, "GitHub Actions output-file path; unset outside GitHub Actions."),
)


_PYTHON_ENV_PATTERNS = (
    re.compile(r"""os\s*\.\s*getenv\s*\(\s*['"]([A-Z][A-Z0-9_]*)['"]"""),
    re.compile(r"""os\s*\.\s*environ\s*\.\s*(?:get|setdefault|pop)\s*\(\s*['"]([A-Z][A-Z0-9_]*)['"]"""),
    re.compile(r"""os\s*\.\s*environ\s*\[\s*['"]([A-Z][A-Z0-9_]*)['"]\s*\]"""),
    re.compile(r"""['"]([A-Z][A-Z0-9_]*)['"]\s+in\s+os\s*\.\s*environ"""),
    re.compile(r"""_env_bool\s*\(\s*['"]([A-Z][A-Z0-9_]*)['"]"""),
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
    names: set[str] = set()
    if suffix == ".py":
        for pattern in _PYTHON_ENV_PATTERNS:
            names.update(pattern.findall(source))
    elif suffix == ".sh":
        names.update(_SHELL_ENV_PATTERN.findall(source))
    return names


def referenced_environment_names(repo_root: Path) -> set[str]:
    """Find registry names mentioned in the scanned source tree."""
    parts = []
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
                    parts.append(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError):
                    continue
    source = "\n".join(parts)
    return {entry.name for entry in ENV_VARS if entry.name in source}
