"""LLM and Mumei CLI configuration."""
import os
from dataclasses import dataclass, field
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


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
