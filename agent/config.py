"""LLM and Mumei CLI configuration."""
import os
from dataclasses import dataclass, field
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse common environment boolean values."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


def _default_core_axiom_path() -> str:
    """Default search path for ``std/core.mm`` (Phase 2-B).

    Honors the ``CORE_AXIOM_PATH`` env var first, then falls back to a
    sibling ``../mumei/std/core.mm`` (the typical layout when the
    mumei-agent and mumei repos are cloned side-by-side).  If neither
    is available, returns the logical path ``std/core.mm`` so callers
    that probe existence will silently skip injection.
    """
    env = os.getenv("CORE_AXIOM_PATH", "").strip()
    if env:
        return env
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except OSError:
        return "std/core.mm"
    # agent/config.py -> <repo_root>/agent/config.py
    repo_root = os.path.abspath(os.path.join(here, os.pardir))
    candidate = os.path.abspath(
        os.path.join(repo_root, os.pardir, "mumei", "std", "core.mm"),
    )
    if os.path.exists(candidate):
        return candidate
    return "std/core.mm"


@dataclass
class AgentConfig:
    """Configuration for the Mumei agent."""
    api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", "")))
    base_url: str | None = field(default_factory=lambda: os.getenv("LLM_BASE_URL", None))
    model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o"))
    mumei_bin: str = field(default_factory=lambda: os.getenv("MUMEI_BIN", "mumei"))
    max_retries: int = 5
    strategy: str = field(default_factory=lambda: os.getenv("AGENT_STRATEGY", "single"))
    visualizer_sync: bool = field(default_factory=lambda: _env_bool("ENABLE_VISUALIZER_SYNC"))

    # Phase 12 — NLAE-inspired features.  Latent debugging remains opt-in;
    # dense property generation is enabled by default and latent protocol is opt-in.
    enable_latent_debug: bool = field(default_factory=lambda: _env_bool("ENABLE_LATENT_DEBUG"))
    enable_dense_properties: bool = field(default_factory=lambda: _env_bool("ENABLE_DENSE_PROPERTIES", True))
    enable_latent_protocol: bool = field(default_factory=lambda: _env_bool("ENABLE_LATENT_PROTOCOL"))
    enable_code_to_spec: bool = field(default_factory=lambda: _env_bool("ENABLE_CODE_TO_SPEC", True))
    enable_generation_health_check: bool = field(
        default_factory=lambda: _env_bool("ENABLE_GENERATION_HEALTH_CHECK", True)
    )
    enable_spec_code_mapping: bool = field(default_factory=lambda: _env_bool("ENABLE_SPEC_CODE_MAPPING", True))
    enable_ambiguity_detection: bool = field(
        default_factory=lambda: _env_bool("ENABLE_AMBIGUITY_DETECTION", True)
    )
    enable_intent_tracking: bool = field(
        default_factory=lambda: _env_bool("ENABLE_INTENT_TRACKING", True)
    )
    intent_drift_threshold: float = field(
        default_factory=lambda: float(os.getenv("INTENT_DRIFT_THRESHOLD", "0.7"))
    )

    # Phase 2-B — std/core.mm core axiom injection for std/ module generation.
    core_axiom_path: str = field(default_factory=_default_core_axiom_path)
    inject_core_axioms: bool = field(
        default_factory=lambda: os.getenv("INJECT_CORE_AXIOMS", "true").lower()
        not in {"false", "0", "no", "off"}
    )

    # Task 2-C — optional path to a ``mumei-lang/mumei-lean`` checkout
    # that ``agent.lean_bridge`` can shell out to when proliferate is
    # invoked with ``--enable-lean-fallback``.  ``None`` (the default)
    # disables the fallback so existing pipelines stay byte-identical.
    mumei_lean_repo: str | None = field(
        default_factory=lambda: os.getenv("MUMEI_LEAN_REPO") or None
    )

    def __post_init__(self):
        # API key validation is deferred to create_client() so that
        # subcommands that never use the LLM (e.g. ``python -m agent
        # health``) can construct AgentConfig without requiring a key.
        pass

    def create_client(self) -> OpenAI:
        """Create an OpenAI-compatible client.

        Raises
        ------
        ValueError
            If ``api_key`` is empty (LLM_API_KEY / OPENAI_API_KEY not set).
        """
        if not self.api_key:
            raise ValueError(
                "LLM_API_KEY (or OPENAI_API_KEY) is not set. "
                "Please check your .env file or environment variables."
            )
        kwargs: dict = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return OpenAI(**kwargs)
