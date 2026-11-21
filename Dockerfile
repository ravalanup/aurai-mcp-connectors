# Aurai MCP connectors image. One image runs any connector: `serve <connector>`. It carries the connector manifests and
# security reviews (so `check` runs inside it) and the policy data used by that check; the Rego the OPA sidecar
# evaluates comes from the chart's ConfigMap, not from this image.
FROM python:3.15-slim AS build
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install ".[redis]"

FROM python:3.15-slim
COPY --from=build /install /usr/local
WORKDIR /app
COPY connectors ./connectors
COPY policy ./policy
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin aurai
USER 10001
EXPOSE 8080
ENV PYTHONUNBUFFERED=1 AURAI_CONNECTORS_DIR=/app/connectors AURAI_POLICY_DIR=/app/policy
ENTRYPOINT ["aurai-connectors"]
CMD ["--help"]

LABEL org.opencontainers.image.title="aurai-mcp-connectors" \
      org.opencontainers.image.description="Aurai MCP connectors: governed tool access" \
      org.opencontainers.image.licenses="MIT"
