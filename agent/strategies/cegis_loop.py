"""CEGIS loop for loop invariant generation."""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from agent import telemetry
from agent.config import AgentConfig
from agent.mumei_client import MumeiClient

_logger = logging.getLogger(__name__)


from agent.strategies.cegis_loop_helpers import (
    CEGISResult,
    InvariantCandidate,
    _clean_invariant,
    _extract_counterexample,
    _is_loop_line,
    _loop_has_invariant,
    apply_invariant,
    escalate_to_lean,
    find_loop_line,
    normalize_loop_line,
)


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
        with tempfile.NamedTemporaryFile(
            "w",
            suffix=path.suffix,
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(candidate)
            tmp_path = Path(tmp.name)
        try:
            result = self.mumei_client.verify(str(tmp_path))
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

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
            tracer = telemetry.get_tracer(__name__)
            with tracer.start_as_current_span("llm.cegis_synthesize_invariant") as span:
                span.set_attribute("gen_ai.system", "openai-compatible")
                span.set_attribute("gen_ai.request.model", self.config.model)
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
