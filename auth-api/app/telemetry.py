import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://hermes_jaeger:4317")
SERVICE_NAME  = os.getenv("OTEL_SERVICE_NAME", "hermes-auth-api")


def setup_telemetry(app, engine=None):
    try:
        resource = Resource.create({"service.name": SERVICE_NAME})
        provider = TracerProvider(resource=resource)

        exporter = OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(provider)

        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=provider,
            excluded_urls="health"
        )

        if engine:
            SQLAlchemyInstrumentor().instrument(
                engine=engine,
                tracer_provider=provider
            )

        HTTPXClientInstrumentor().instrument(tracer_provider=provider)

        print(f"✓ OpenTelemetry tracing enabled → {OTEL_ENDPOINT}")

    except Exception as e:
        print(f"⚠ OpenTelemetry setup failed (non-fatal): {e}")
