"""Optional OpenTelemetry tracing (F2).

Disabled by default. Set ``OTEL_ENABLED=true`` to turn it on; everything else is
configured through the standard OTel environment variables
(``OTEL_EXPORTER_OTLP_ENDPOINT``, ``OTEL_SERVICE_NAME``, ...).

Heavy ``opentelemetry`` imports are deferred into ``init_otel`` so that the
default (disabled) path adds no import cost and no hard dependency. If the OTel
packages are not installed, ``init_otel`` logs a warning and returns ``False``.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_initialized = False


def otel_enabled() -> bool:
    return os.environ.get("OTEL_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def init_otel(service_name: str = "coderunner-agent-host") -> bool:
    """Initialise OTel tracing if enabled. Returns True when set up.

    Idempotent and safe to call from a service's startup hook. A no-op (returns
    False) unless ``OTEL_ENABLED`` is truthy.
    """
    global _initialized
    if _initialized:
        return True
    if not otel_enabled():
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        logger.warning(
            "OTEL_ENABLED is set but opentelemetry packages are missing (%s); "
            "tracing disabled. Install opentelemetry-sdk + "
            "opentelemetry-exporter-otlp to enable.",
            exc,
        )
        return False

    resource = Resource.create(
        {SERVICE_NAME: os.environ.get("OTEL_SERVICE_NAME", service_name)}
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    _initialized = True
    logger.info("OpenTelemetry tracing initialised (service=%s)", service_name)
    return True
