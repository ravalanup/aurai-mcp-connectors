# Local development

## Everything without a cluster

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
ruff check .; pytest -q; aurai-connectors check
```

The tests that evaluate policy need the `opa` binary on `PATH` (https://www.openpolicyagent.org/docs/#running-opa). They
are skipped, and the test run says so, if it is missing; CI installs it. `opa test policy` runs the Rego tests on their
own.

## Try a connector from an MCP client (stdio)

```powershell
scripts\run-local.ps1 -Connector ops-data -Team ops-insights
```

Point the client at that command. The caller is the development identity; policy still runs against `policy\`. Change
`-Team` to `sandbox` and the same call is denied, which is the quickest way to see the scopes. Writes that need approval
cannot be completed over stdio (no headers); use HTTP.

## Try HTTP with an approval

Serve a connector over HTTP with a signing key and a test JWKS, or deploy to kind. The tests show the exact requests:
`tests/conftest.py` builds a service token, posts JSON-RPC to `/mcp`, and passes `X-Aurai-Approval`. Mint an approval
with `aurai-connectors approve`.

## On the kind cluster

```powershell
scripts\deploy-local.ps1        # builds, runs `check` inside the image, creates the Secret, installs the chart
scripts\port-forward.ps1 -Connector tickets
```

Needs the aurai-infra stack for Keycloak and the OTel collector. A caller needs a service client with the
`aurai-connectors` audience and `team_id`/`use_case_id` claims (docs/identity.md). The deploy script prints the
generated approval signing key once; keep it.
