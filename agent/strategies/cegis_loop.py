"""CEGIS loop for loop invariant generation."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.config import AgentConfig
from agent.mumei_client import MumeiClient

_logger = logging.getLogger(__name__)


@dataclass
class InvariantCandidate:
    """A candidate loop invariant expression."""

    expression: str
    source: str
    iteration: int
    counterexamples: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CEGISResult:
    """Result of CEGIS loop execution."""

    success: bool
    final_invariant: str | None
    iterations: int
    total_counterexamples: int
    reason: str


class CEGISLoop:
    """Counterexample-guided inductive synthesis for loop invariants."""

    def __init__(
        self,
        config: AgentConfig,
        mumei_client: MumeiClient,
        max_iterations: int = 10,
    ):
        self.config = config
        self.mumei_client = mumei_client
        self.max_iterations = max_iterations
        self.history: list[InvariantCandidate] = []
        self._client = None

    def generate_initial_invariant(self, loop_context: dict[str, Any]) -> str:
        """Generate an initial invariant candidate using an LLM."""
        return self._generate_invariant(
            self._build_initial_invariant_prompt(loop_context),
            fallback=self._template_invariant(loop_context),
        )

    def refine_invariant(
        self,
        current_invariant: str,
        counterexample: dict[str, Any],
        loop_context: dict[str, Any],
    ) -> str:
        """Refine an invariant based on a verifier counterexample."""
        return self._generate_invariant(
            self._build_refinement_prompt(
                current_invariant,
                counterexample,
                loop_context,
            ),
            fallback=current_invariant,
        )

    def verify_invariant(
        self,
        source_file: str,
        invariant: str,
        loop_line: int,
    ) -> dict[str, Any]:
        """Verify whether an invariant is sufficient for the target loop."""
        path = Path(source_file)
        original = path.read_text(encoding="utf-8")
        candidate = apply_invariant(original, invariant, loop_line)
        path.write_text(candidate, encoding="utf-8")
        try:
            result = self.mumei_client.verify(source_file)
        finally:
            path.write_text(original, encoding="utf-8")

        report = result.get("report") or {}
        if result.get("success"):
            return {"success": True, "report": report}
        return {
            "success": False,
            "report": report,
            "counterexample": _extract_counterexample(report),
        }

    def run(
        self,
        source_file: str,
        loop_line: int,
        loop_context: dict[str, Any],
    ) -> CEGISResult:
        """Run the CEGIS loop."""
        current_invariant = self.generate_initial_invariant(loop_context)
        total_counterexamples = 0

        for iteration in range(1, self.max_iterations + 1):
            result = self.verify_invariant(source_file, current_invariant, loop_line)
            if result["success"]:
                return CEGISResult(
                    success=True,
                    final_invariant=current_invariant,
                    iterations=iteration,
                    total_counterexamples=total_counterexamples,
                    reason="converged",
                )

            counterexample = result.get("counterexample") or {}
            total_counterexamples += 1
            self.history.append(
                InvariantCandidate(
                    expression=current_invariant,
                    source="llm",
                    iteration=iteration,
                    counterexamples=[counterexample],
                )
            )
            current_invariant = self.refine_invariant(
                current_invariant,
                counterexample,
                loop_context,
            )

        return CEGISResult(
            success=False,
            final_invariant=None,
            iterations=self.max_iterations,
            total_counterexamples=total_counterexamples,
            reason="escalation_to_lean",
        )

    def _build_initial_invariant_prompt(self, loop_context: dict[str, Any]) -> str:
        return f"""Generate a loop invariant for the following Mumei loop:

Loop variables: {loop_context.get('variables', [])}
Precondition: {loop_context.get('precondition', 'true')}
Postcondition: {loop_context.get('postcondition', 'true')}
Loop condition: {loop_context.get('condition', '')}
Loop body: {loop_context.get('body', '')}

The invariant must:
1. Be true before the loop starts under the precondition
2. Be preserved by each loop iteration
3. Help imply the postcondition when the loop terminates

Return ONLY the invariant expression."""

    def _build_refinement_prompt(
        self,
        current_invariant: str,
        counterexample: dict[str, Any],
        loop_context: dict[str, Any],
    ) -> str:
        counterexample_str = ", ".join(
            f"{key} = {value}" for key, value in sorted(counterexample.items())
        ) or "not available"
        return f"""Your previous loop invariant was rejected.

Current invariant: {current_invariant}
Counterexample: {counterexample_str}

Loop context:
- Variables: {loop_context.get('variables', [])}
- Precondition: {loop_context.get('precondition', 'true')}
- Postcondition: {loop_context.get('postcondition', 'true')}
- Loop condition: {loop_context.get('condition', '')}
- Loop body: {loop_context.get('body', '')}

Generate a refined invariant that excludes the counterexample when it is invalid,
keeps the invariant inductive, and stays as simple as possible.

Return ONLY the refined invariant expression."""

    def _generate_invariant(self, prompt: str, fallback: str) -> str:
        if not self.config.api_key:
            return fallback
        try:
            if self._client is None:
                self._client = self.config.create_client()
            response = self._client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You synthesize concise Mumei loop invariants. "
                            "Return only a boolean expression."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            content = response.choices[0].message.content or ""
            invariant = _clean_invariant(content)
            return invariant or fallback
        except Exception:
            _logger.warning("CEGIS invariant LLM generation failed", exc_info=True)
            return fallback

    def _template_invariant(self, loop_context: dict[str, Any]) -> str:
        variables = [
            str(variable)
            for variable in loop_context.get("variables", [])
            if str(variable).isidentifier()
        ]
        if not variables:
            return "true"
        bounds: list[str] = []
        postcondition = str(loop_context.get("postcondition", ""))
        for variable in variables:
            bounds.append(f"{variable} >= 0")
            if "n" in postcondition and variable != "n":
                bounds.append(f"{variable} <= n")
        return " && ".join(dict.fromkeys(bounds)) or "true"


def apply_invariant(source_code: str, invariant: str, loop_line: int) -> str:
    """Insert an invariant before a loop line."""
    lines = source_code.split("\n")
    if loop_line <= 0:
        return source_code
    for index, line in enumerate(lines):
        if index + 1 == loop_line:
            stripped = line.lstrip()
            if stripped.startswith("invariant:") or f"invariant: {invariant};" in source_code:
                return source_code
            indent = len(line) - len(stripped)
            lines.insert(index, f"{' ' * indent}invariant: {invariant};")
            break
    return "\n".join(lines)


def escalate_to_lean(source_file: str, loop_info: dict[str, Any]) -> Path:
    """Write a Lean escalation bundle for a CEGIS exhaustion."""
    source_path = Path(source_file)
    bundle_path = source_path.with_suffix(".escalation-bundle.json")
    escalation_bundle = {
        "source_file": source_file,
        "loop_line": loop_info.get("line", 0),
        "loop_context": loop_info.get("context", {}),
        "reason": "cegis_max_iterations_reached",
    }
    bundle_path.write_text(
        json.dumps(escalation_bundle, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _logger.info("CEGIS exhausted iterations, escalated to Lean: %s", bundle_path)
    return bundle_path


def _extract_counterexample(report: dict[str, Any]) -> dict[str, Any]:
    for key in ("counterexample", "model"):
        value = report.get(key)
        if isinstance(value, dict):
            return value
    semantic_feedback = report.get("semantic_feedback")
    if isinstance(semantic_feedback, dict):
        value = semantic_feedback.get("counterexample")
        if isinstance(value, dict):
            return value
    return {}


def _clean_invariant(content: str) -> str:
    text = content.strip()
    if "```" in text:
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        text = text.removeprefix("mumei").strip()
    return text.strip().rstrip(";").strip()
