# Binary telemetry fixture

`aim_sample.xrk` is copied unchanged from the existing
[TrackTelemetryConverter fixture](https://github.com/BoYanZh/TrackTelemetryConverter/blob/61175ab59f6ed5d4d9ef7b72218e11b17ba29cf8/tests/fixtures/aim_sample.xrk).
It exercises real AiM parsing through the MCP loader in CI, including the optional
`libxrk` dependency. Tests must not depend on a sibling checkout or private logs.
