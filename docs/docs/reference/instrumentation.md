# Instrumentation

## Metrics

Vero exposes Prometheus metrics on the `/metrics` endpoint (e.g., `http://localhost:8000/metrics`).

Vero's GitHub repository contains
[pre-built Grafana dashboards](https://github.com/serenita-org/vero/tree/master/grafana){:target="_blank"}.
These dashboards provide an overview of performed duties, validator status,
errors and connected beacon node scores.

To use these dashboards:

1. Ensure Vero is running with metrics enabled (on by default, configurable via `--metrics-address` and `--metrics-port`)
2. Configure Prometheus to scrape Vero's metrics endpoint
3. Import the dashboard JSON files from the repository into Grafana

<p align="center">
  <img alt="Overview" src="../assets/instrumentation/metrics_overview.png" style="text-align: center">
</p>

<p align="center">
  <img alt="Attestation Consensus" src="../assets/instrumentation/metrics_attestation_consensus.png" style="text-align: center">
</p>

<p align="center">
  <img alt="Duty Submission Time" src="../assets/instrumentation/metrics_duty_submission_time.png" style="text-align: center">
</p>

## Tracing

Vero can export tracing data to any OpenTelemetry-compatible endpoint using the OpenTelemetry SDK.

Set the `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_PROTOCOL` environment variables,
and Vero will automatically push tracing data to the specified endpoint.

You can also set other OpenTelemetry-supported environment variables, such as
`OTEL_TRACES_SAMPLER` or `OTEL_RESOURCE_ATTRIBUTES`. For a full list of
supported variables, refer to the
[OpenTelemetry docs](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/){:target="_blank"}.

!!! note "Block Proposal Trace Example"

    ![Block Proposal](assets/instrumentation/tracing_block_proposal.png)
