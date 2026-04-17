"""LLM and Mumei CLI configuration."""
import os
from dataclasses import dataclass, field
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


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
    visualizer_sync: bool = field(default_factory=lambda: os.getenv("ENABLE_VISUALIZER_SYNC", "false").lower() == "true")

    # Phase 2-B — std/core.mm core axiom injection for std/ module generation.
    core_axiom_path: str = field(default_factory=_default_core_axiom_path)
    inject_core_axioms: bool = field(
        default_factory=lambda: os.getenv("INJECT_CORE_AXIOMS", "true").lower()
        not in {"false", "0", "no", "off"}
    )

    def __post_init__(self):
        if not self.api_key:
            raise ValueError(
                "LLM_API_KEY (or OPENAI_API_KEY) is not set. "
                "Please check your .env file."
            )

    def create_client(self) -> OpenAI:
        """Create an OpenAI-compatible client."""
        kwargs: dict = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return OpenAI(**kwargs)
