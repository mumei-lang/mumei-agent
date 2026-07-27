"""P12-D: deterministic multi-agent NLAE verification workflow.

The single ``NLAEPipeline`` run (P9-G) drives generate -> verify ->
self-correct -> Lean fidelity as one agent.  This module splits the same
stages across specialised verification agents that hand work to each other
over the existing :class:`~agent.latent_protocol.LatentProtocol` envelopes,
so every handoff carries a semantic hash, a protocol version, an
authentication tag, and a redacted audit entry.

Orchestration is deterministic: roles are fixed, the round order is fixed,
and no new verdict classification is introduced.  Handoff bodies are
inspectable metadata only; verdicts keep coming from the verifier and the
Lean bridge.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any

from agent import telemetry
from agent.latent_protocol import LatentProtocol


GENERATOR_ROLE = "generator"
COUNTEREXAMPLE_ROLE = "counterexample"
LEAN_ESCALATION_ROLE = "lean_escalation"
VERIFICATION_ROLES: tuple[str, ...] = (
    GENERATOR_ROLE,
    COUNTEREXAMPLE_ROLE,
    LEAN_ESCALATION_ROLE,
)

DEFAULT_MAX_ROUNDS = 2


@dataclass(frozen=True)
class AgentHandoff:
    """One inter-agent handoff recorded on a latent protocol envelope."""

    round: int
    from_role: str
    to_role: str
    semantic_hash: str
    protocol_version: str
    transfer_bytes: int
    authenticated: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MultiAgentOutcome:
    """Audit trail for a multi-agent workflow attempt."""

    enabled: bool
    status: str
    roles: list[str] = field(default_factory=lambda: list(VERIFICATION_ROLES))
    rounds: int = 0
    handoffs: list[dict[str, Any]] = field(default_factory=list)
    audit_events: int = 0
    # ``converged`` mirrors ``NLAEResult.verified``, which is true when either
    # backend discharged the obligations; ``converged_by`` names which one
    # ('z3' or 'lean'), reusing the existing verdict vocabulary.
    converged: bool = False
    converged_by: str | None = None
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MultiAgentOrchestrator:
    """Deterministic handoff bus shared by the NLAE verification agents."""

    def __init__(
        self,
        *,
        protocol: LatentProtocol | None = None,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
    ) -> None:
        self.protocol = protocol or LatentProtocol(
            encryption_key=os.environ.get("LATENT_PROTOCOL_KEY") or None,
            audit_log_path=os.environ.get("LATENT_PROTOCOL_AUDIT_LOG") or None,
        )
        self.max_rounds = max(1, int(max_rounds))
        self.handoffs: list[AgentHandoff] = []
        self._previous_message: dict[str, Any] | None = None
        self._previous_context: dict[str, Any] | None = None

    def handoff(
        self,
        *,
        round_index: int,
        from_role: str,
        to_role: str,
        message: dict[str, Any],
        context: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> AgentHandoff:
        """Encode one role-to-role handoff and record its audit metadata."""
        for role in (from_role, to_role):
            if role not in VERIFICATION_ROLES:
                raise ValueError(f"unknown verification role: {role}")

        envelope_context: dict[str, Any] = {
            "from_role": from_role,
            "round": round_index,
            "to_role": to_role,
            "workflow": "mumei.nlae.multi_agent",
        }
        if context:
            envelope_context.update(context)
        if trace_id:
            # ``trace_id`` is a volatile transport field for the protocol's
            # semantic hash, so the same handoff content stays comparable
            # across traces while the envelope still carries trace context.
            envelope_context["trace_id"] = trace_id

        with telemetry.start_span("mumei.nlae.handoff") as span:
            latent_vector = self.protocol.encode_message(
                message,
                envelope_context,
                previous_message=self._previous_message,
                previous_context=self._previous_context,
            )
            decoded = self.protocol.decode_message(latent_vector)
            handoff = AgentHandoff(
                round=round_index,
                from_role=from_role,
                to_role=to_role,
                semantic_hash=str(decoded.get("semantic_hash", "")),
                protocol_version=str(decoded.get("protocol_version", "")),
                transfer_bytes=int(decoded.get("transfer_bytes", 0) or 0),
                authenticated=self.protocol.verify_authentication_tag(latent_vector),
            )
            telemetry.set_span_attributes(
                span,
                {
                    "mumei.nlae.handoff.from_role": from_role,
                    "mumei.nlae.handoff.to_role": to_role,
                    "mumei.nlae.handoff.round": round_index,
                    "mumei.nlae.handoff.semantic_hash": handoff.semantic_hash,
                    "mumei.nlae.handoff.protocol_version": handoff.protocol_version,
                    "mumei.nlae.handoff.authenticated": handoff.authenticated,
                },
            )

        self._previous_message = message
        self._previous_context = envelope_context
        self.handoffs.append(handoff)
        return handoff

    @property
    def audit_events(self) -> int:
        return len(self.protocol.audit_log)

    def outcome(
        self,
        *,
        rounds: int,
        converged: bool,
        converged_by: str | None = None,
    ) -> MultiAgentOutcome:
        return MultiAgentOutcome(
            enabled=True,
            status="ok",
            rounds=rounds,
            handoffs=[handoff.to_dict() for handoff in self.handoffs],
            audit_events=self.audit_events,
            converged=converged,
            converged_by=converged_by,
        )


def fallback_outcome(reason: str) -> MultiAgentOutcome:
    """Outcome recorded when the workflow degrades to the single pipeline."""
    return MultiAgentOutcome(
        enabled=True,
        status="fallback",
        fallback_reason=reason,
    )
