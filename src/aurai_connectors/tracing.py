"""Spans follow the Aurai conventions in aurai-eval-governance: `aurai.tool.call` carries the tool name and
`aurai.approval` records whether an approval was required and its outcome. Arguments and results are never attached."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SPAN_TOOL_CALL = "aurai.tool.call"
SPAN_APPROVAL = "aurai.approval"
ATTR_USE_CASE = "aurai.use_case.id"
ATTR_TEAM = "aurai.team.id"
ATTR_TIER = "aurai.risk_tier"
ATTR_TOOL = "aurai.tool.name"
ATTR_CONNECTOR = "aurai.tool.connector"
ATTR_DECISION = "aurai.tool.decision"
ATTR_APPROVAL_REQUIRED = "aurai.approval.required"
ATTR_APPROVAL_OUTCOME = "aurai.approval.outcome"  # pending | approved | rejected


def setup_tracing(otlp_endpoint: str, service_name: str) -> trace.Tracer:
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint.rstrip("/") + "/v1/traces"))
        )
    return provider.get_tracer("aurai.connectors")
