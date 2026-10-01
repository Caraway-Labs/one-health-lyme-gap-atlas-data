"""Bounded, fail-open export of a short-lived literature invocation's spans."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from contextlib import suppress
from threading import Event, RLock, Thread, Timer

from lyme_gap_atlas_shared.observability import parse_otlp_headers
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanLimits, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

LITERATURE_COMMANDS = frozenset(
    {
        "pipeline.pmc-extract",
        "pipeline.literature-preflight",
        "pipeline.pubmed-discover",
        "pipeline.build-retrieval-corpus",
        "pipeline.literature-status",
    }
)
_LOGGER = logging.getLogger(__name__)


def trace_fields() -> dict[str, str]:
    """Use an actual OTel identity, never manufacture one when tracing is disabled."""
    try:
        context = trace.get_current_span().get_span_context()
        return {"trace_id": format(context.trace_id, "032x")} if context.is_valid else {}
    except Exception:
        with suppress(Exception):
            _LOGGER.warning("atlas-data.trace_context_unavailable")
        return {}


class InvocationSpanProcessor(SpanProcessor):
    """Defer ended child spans until the CLI root ends, then release the root first.

    A span/time limit, explicit early flush, or shutdown switches to the standard
    delegate. Limits never terminate ingestion or promise retention after fallback.
    """

    def __init__(
        self,
        delegate: SpanProcessor,
        *,
        max_spans: int = 128,
        max_duration_seconds: float = 300,
        flush_timeout_millis: int = 5000,
    ) -> None:
        if max_spans < 1 or max_duration_seconds <= 0 or flush_timeout_millis <= 0:
            raise ValueError("invocation tracing limits must be positive")
        self._delegate = delegate
        self._max_spans = max_spans
        self._max_duration = max_duration_seconds
        self._flush_timeout = flush_timeout_millis
        self._lock = RLock()
        self._buffer: list[ReadableSpan] = []
        self._trace_id: int | None = None
        self._root_id: int | None = None
        self._timer: Timer | None = None
        self._streaming = False
        self._closed = False

    def _warn(self, reason: str) -> None:
        with suppress(Exception):
            _LOGGER.warning(
                "atlas-data.trace_buffer %s",
                json.dumps(
                    {
                        "reason": reason,
                        "trace_id": format(self._trace_id, "032x") if self._trace_id else None,
                        "max_spans": self._max_spans,
                        "max_duration_seconds": self._max_duration,
                    },
                    sort_keys=True,
                ),
            )

    def _forward(self, span: ReadableSpan) -> None:
        try:
            self._delegate.on_end(span)
        except Exception:
            self._warn("processor_unavailable")

    def _release(self, reason: str) -> None:
        """Caller holds the lock; the production delegate only queues spans."""
        self._streaming = True
        if self._timer is not None:
            self._timer.cancel()
        buffered, self._buffer = self._buffer, []
        self._warn(reason)
        for span in buffered:
            self._forward(span)

    def _expire(self) -> None:
        with self._lock:
            if not self._closed and not self._streaming:
                self._release("duration_limit")

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        with self._lock:
            if self._closed:
                return
            if span.name == "atlas-data.cli" and self._root_id is None:
                context = span.get_span_context()
                self._trace_id, self._root_id = context.trace_id, context.span_id
                try:
                    self._timer = Timer(self._max_duration, self._expire)
                    self._timer.daemon = True
                    self._timer.start()
                except Exception:
                    self._streaming = True
                    self._warn("timer_unavailable")
            try:
                self._delegate.on_start(span, parent_context)
            except Exception:
                self._warn("processor_unavailable")

    def on_end(self, span: ReadableSpan) -> None:
        with self._lock:
            if self._closed:
                return
            context = span.context
            if context is None or context.trace_id != self._trace_id or self._streaming:
                self._forward(span)
            elif context.span_id == self._root_id:
                # An exporter can wake between queue writes: release ERROR/root
                # before children so it is present at the first sampling decision.
                self._streaming = True
                if self._timer is not None:
                    self._timer.cancel()
                self._forward(span)
                buffered, self._buffer = self._buffer, []
                for child in buffered:
                    self._forward(child)
            elif len(self._buffer) < self._max_spans:
                self._buffer.append(span)
            else:
                self._release("span_limit")
                self._forward(span)

    def _bounded_call(self, callback: Callable[[], object], timeout_millis: int) -> bool:
        """Some SDK versions ignore flush timeouts; don't block a worker on them."""
        completed = Event()
        succeeded = [False]

        def run() -> None:
            try:
                succeeded[0] = callback() is not False
            except Exception:
                self._warn("exporter_unavailable")
            finally:
                completed.set()

        try:
            thread = Thread(target=run, name="atlas-literature-telemetry", daemon=True)
            thread.start()
        except Exception:
            self._warn("flush_unavailable")
            return False
        if not completed.wait(max(0, timeout_millis) / 1000):
            self._warn("flush_timeout")
            return False
        if not succeeded[0]:
            self._warn("flush_incomplete")
        return succeeded[0]

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        with self._lock:
            if self._closed:
                return False
            if self._buffer:
                self._release("flush_before_root")
        budget = min(timeout_millis, self._flush_timeout)
        return self._bounded_call(lambda: self._delegate.force_flush(budget), budget)

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._timer is not None:
                self._timer.cancel()
            if self._buffer:
                self._release("shutdown_before_root")
        self._bounded_call(self._delegate.shutdown, self._flush_timeout)


def configure_literature_tracing(service_name: str) -> None:
    """Keep existing OTLP destination/auth; bound buffers and export waits locally."""
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    headers = parse_otlp_headers(os.getenv("OTEL_EXPORTER_OTLP_HEADERS"))
    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name}),
        span_limits=SpanLimits(
            max_attributes=64, max_attribute_length=1024, max_events=0, max_links=0
        ),
    )
    exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers, timeout=3)
    batch = BatchSpanProcessor(
        exporter,
        max_queue_size=256,
        max_export_batch_size=256,
        export_timeout_millis=3000,
    )
    provider.add_span_processor(InvocationSpanProcessor(batch))
    trace.set_tracer_provider(provider)
