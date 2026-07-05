"""OpenTelemetry helpers with a zero-dependency NoOp fallback (P15 Phase 1).

Observability is opt-in.  Unless ``OTEL_ENABLED`` is truthy *and* the
``opentelemetry`` packages are importable, every helper here returns a NoOp
tracer/meter whose spans and instruments do nothing.  This guarantees that the
agent's existing heal / generate / forge / proliferate flows behave identically
whether or not the ``otel`` extra is installed.

Install the optional dependencies with ``pip install mumei-agent[otel]`` (or
``uv sync --extra otel``) and set ``OTEL_ENABLED=true`` plus
``OTEL_EXPORTER_OTLP_ENDPOINT`` to export traces/metrics to an OTLP backend
(Jaeger, Grafana Tempo, etc.).
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_SERVICE_NAME = "mumei-agent"

# Resolved lazily on first use so that importing this module never touches the
# opentelemetry packages or configures any global provider.
_INITIALISED = False
_TRACER: Any = None
_METER: Any = None
_TOKEN_COUNTER: Any = None


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


def is_enabled() -> bool:
    """Return whether OTel instrumentation is active.

    Requires both ``OTEL_ENABLED`` to be truthy (default ``false``) and the
    ``opentelemetry`` packages to be importable.
    """
    if not _env_bool("OTEL_ENABLED", False):
        return False
    try:
        import opentelemetry.trace  # noqa: F401
    except Exception:  # pragma: no cover - exercised only without the extra
        return False
    return True


# --------------------------------------------------------------------------- #
# NoOp fallbacks
# --------------------------------------------------------------------------- #
class _NoOpSpan:
    """Span stand-in that swallows every OTel span operation."""

    def set_attribute(self, key: str, value: Any) -> None:  # noqa: D401
        return None

    def set_attributes(self, attributes: Any) -> None:
        return None

    def add_event(self, name: str, attributes: Any = None) -> None:
        return None

    def record_exception(self, exception: BaseException, *args: Any, **kwargs: Any) -> None:
        return None

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        return None

    def get_span_context(self) -> None:
        return None

    def end(self, *args: Any, **kwargs: Any) -> None:
        return None


class _NoOpTracer:
    @contextmanager
    def start_as_current_span(self, name: str, **kwargs: Any) -> Iterator[_NoOpSpan]:
        yield _NoOpSpan()


class _NoOpInstrument:
    def add(self, amount: Any, attributes: Any = None) -> None:
        return None

    def record(self, amount: Any, attributes: Any = None) -> None:
        return None


class _NoOpMeter:
    def create_counter(self, *args: Any, **kwargs: Any) -> _NoOpInstrument:
        return _NoOpInstrument()

    def create_histogram(self, *args: Any, **kwargs: Any) -> _NoOpInstrument:
        return _NoOpInstrument()

    def create_up_down_counter(self, *args: Any, **kwargs: Any) -> _NoOpInstrument:
        return _NoOpInstrument()


_NOOP_TRACER = _NoOpTracer()
_NOOP_METER = _NoOpMeter()
_NOOP_INSTRUMENT = _NoOpInstrument()


# --------------------------------------------------------------------------- #
# Exporter selection (gRPC vs HTTP)
# --------------------------------------------------------------------------- #
def _otlp_protocol() -> str:
    """Resolve the OTLP wire protocol from the standard OTel env var.

    Honors ``OTEL_EXPORTER_OTLP_PROTOCOL`` (values ``grpc``, ``http/protobuf``,
    ``http/json``), defaulting to ``grpc``.  Any ``http*`` value selects the
    HTTP/protobuf exporter.
    """
    return (os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc") or "grpc").strip().lower()


def _build_span_exporter() -> Any:
    """Construct an OTLP span exporter, or ``None`` if unavailable."""
    try:
        if _otlp_protocol().startswith("http"):
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
        else:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
        return OTLPSpanExporter()
    except Exception:  # pragma: no cover - exporter optional / offline
        logger.debug("OTLP span exporter unavailable; spans not exported")
        return None


def _build_metric_exporter() -> Any:
    """Construct an OTLP metric exporter, or ``None`` if unavailable."""
    try:
        if _otlp_protocol().startswith("http"):
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter,
            )
        else:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
        return OTLPMetricExporter()
    except Exception:  # pragma: no cover - exporter optional / offline
        logger.debug("OTLP metric exporter unavailable; metrics not exported")
        return None


# --------------------------------------------------------------------------- #
# Lazy provider setup
# --------------------------------------------------------------------------- #
def _initialise() -> None:
    """Configure the global tracer/meter providers once (best effort)."""
    global _INITIALISED, _TRACER, _METER
    if _INITIALISED:
        return
    _INITIALISED = True

    if not is_enabled():
        return

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

        resource = Resource.create({"service.name": _SERVICE_NAME})

        # Only install our own providers if the application has not already
        # configured one (respects an externally-supplied SDK setup).
        if not isinstance(trace.get_tracer_provider(), TracerProvider):
            tracer_provider = TracerProvider(resource=resource)
            span_exporter = _build_span_exporter()
            if span_exporter is not None:
                tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
            trace.set_tracer_provider(tracer_provider)

        # Mirror the tracer guard: only install our MeterProvider when the
        # application has not already configured one.
        if not isinstance(metrics.get_meter_provider(), MeterProvider):
            metric_exporter = _build_metric_exporter()
            if metric_exporter is not None:
                reader = PeriodicExportingMetricReader(metric_exporter)
                meter_provider = MeterProvider(
                    resource=resource, metric_readers=[reader]
                )
                metrics.set_meter_provider(meter_provider)

        _TRACER = trace.get_tracer(_SERVICE_NAME)
        _METER = metrics.get_meter(_SERVICE_NAME)
    except Exception:  # pragma: no cover - defensive; never break the agent
        logger.warning("OpenTelemetry setup failed; falling back to NoOp", exc_info=True)
        _TRACER = None
        _METER = None


def get_tracer(name: str | None = None) -> Any:
    """Return an OTel tracer, or a NoOp tracer when disabled/unavailable."""
    _initialise()
    if _TRACER is None:
        return _NOOP_TRACER
    try:
        from opentelemetry import trace

        return trace.get_tracer(name or _SERVICE_NAME)
    except Exception:  # pragma: no cover - defensive
        return _NOOP_TRACER


def get_meter(name: str | None = None) -> Any:
    """Return an OTel meter, or a NoOp meter when disabled/unavailable."""
    _initialise()
    if _METER is None:
        return _NOOP_METER
    try:
        from opentelemetry import metrics

        return metrics.get_meter(name or _SERVICE_NAME)
    except Exception:  # pragma: no cover - defensive
        return _NOOP_METER


def _token_counter() -> Any:
    global _TOKEN_COUNTER
    if _TOKEN_COUNTER is not None:
        return _TOKEN_COUNTER
    meter = get_meter(__name__)
    _TOKEN_COUNTER = meter.create_counter(
        "gen_ai.usage.total_tokens",
        unit="{token}",
        description="Total LLM tokens consumed (prompt + completion).",
    )
    return _TOKEN_COUNTER


def record_llm_tokens(count: int, *, model: str | None = None) -> None:
    """Record LLM token usage on the ``gen_ai.usage.total_tokens`` counter.

    This is a parallel channel to :meth:`agent.metrics.Metrics.record_tokens`
    and never affects the JSON metrics output.  It is a no-op unless OTel is
    enabled and available.
    """
    if count <= 0 or not is_enabled():
        return
    attributes = {"gen_ai.request.model": model} if model else None
    try:
        _token_counter().add(count, attributes)
    except Exception:  # pragma: no cover - defensive
        logger.debug("record_llm_tokens failed", exc_info=True)


_VERIFY_DURATION_HISTOGRAM: Any = None


def _verify_duration_histogram() -> Any:
    global _VERIFY_DURATION_HISTOGRAM
    if _VERIFY_DURATION_HISTOGRAM is not None:
        return _VERIFY_DURATION_HISTOGRAM
    meter = get_meter(__name__)
    _VERIFY_DURATION_HISTOGRAM = meter.create_histogram(
        "mumei.verify.duration",
        unit="s",
        description="Wall-clock duration of mumei verify subprocess calls.",
    )
    return _VERIFY_DURATION_HISTOGRAM


def record_verify_duration(seconds: float) -> None:
    """Record verify subprocess duration on the ``mumei.verify.duration`` histogram.

    Parallel channel to :attr:`agent.metrics.Metrics.verification_times_seconds`;
    never affects the JSON metrics output.  No-op unless OTel is enabled.
    """
    if seconds <= 0 or not is_enabled():
        return
    try:
        _verify_duration_histogram().record(seconds)
    except Exception:  # pragma: no cover - defensive
        logger.debug("record_verify_duration failed", exc_info=True)


@contextmanager
def start_loop_span(
    loop_type: str,
    *,
    max_retries: int | None = None,
    strategy: str | None = None,
    **extra_attrs: Any,
) -> Iterator[Any]:
    """Context manager that opens a ``mumei.loop.<loop_type>`` root span.

    Yields the span so callers can set finalisation attributes
    (``mumei.loop.final_success``, ``mumei.loop.stop_reason``, etc.)
    at loop exit.  When OTel is disabled the yielded object is a
    :class:`_NoOpSpan` — all attribute / event calls are silently
    swallowed.

    Exceptions are recorded on the span but **not** suppressed.
    """
    tracer = get_tracer(__name__)
    attrs: dict[str, Any] = {"mumei.loop.type": loop_type}
    if max_retries is not None:
        attrs["mumei.loop.max_retries"] = max_retries
    if strategy is not None:
        attrs["mumei.strategy"] = strategy
    attrs.update(extra_attrs)
    try:
        with tracer.start_as_current_span(
            f"mumei.loop.{loop_type}", attributes=attrs,
        ) as span:
            yield span
    except Exception as exc:
        # The real OTel SDK records the exception automatically when
        # ``record_exception=True`` (the default), but we want to be
        # safe in NoOp mode too.
        try:
            span.record_exception(exc)  # type: ignore[possibly-undefined]
        except Exception:
            pass
        raise


def add_thought_event(action: str, attributes: dict[str, Any] | None = None) -> None:
    """Emit an OTel span event on the current span for a ThoughtProcess step.

    Safe to call unconditionally — returns immediately when OTel is disabled
    or unavailable and never raises.
    """
    if not is_enabled():
        return
    try:
        from opentelemetry import trace as _trace

        span = _trace.get_current_span()
        if span is not None and span.is_recording():
            safe_attrs: dict[str, Any] | None = None
            if attributes:
                safe_attrs = {
                    k: v for k, v in attributes.items() if v is not None
                }
            span.add_event(action, attributes=safe_attrs)
    except Exception:  # pragma: no cover - defensive
        logger.debug("add_thought_event failed", exc_info=True)


def inject_trace_context(carrier: dict[str, Any]) -> dict[str, Any]:
    """Inject W3C trace context (``traceparent``/``tracestate``) into *carrier*.

    Returns *carrier* unchanged when OTel is disabled/unavailable so callers can
    always use the result directly.
    """
    if not is_enabled():
        return carrier
    try:
        from opentelemetry.propagate import inject

        inject(carrier)
    except Exception:  # pragma: no cover - defensive
        logger.debug("trace context injection failed", exc_info=True)
    return carrier
