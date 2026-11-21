# Contributing

## Set up

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Install the `opa` binary to run the policy tests locally.

## Before you open a pull request

```powershell
ruff check .
ruff format --check .
opa test policy
aurai-connectors check
pytest -q
```

CI runs the same, plus `helm lint`, `helm template` with kubeconform, a container build and secret scanning.

## Rules that protect the governed path

- **Register tools only through `Governor.tool`.** Do not call `server.tool` or `add_tool` directly; a tool registered that way skips identity, policy, approval and audit.
- **The manifest is the contract.** A tool's action, classification and approval rule are declared in `connectors/<name>/connector.yaml`, never in code. A write tool cannot have `approval: none`.
- **Identity comes from the verified token.** Never read a team, tier, user or approver from a header, argument or body.
- **A new or changed tool needs a new security review** (`review.yaml`) from someone other than the owner, covering exactly the tools in the manifest. `aurai-connectors check` enforces it.
- **Changes to `policy/teams.yaml` or the Rego** need a test and a reviewer from the data owner of whatever they open up. Never loosen a rule to make a test pass.
- **Do not log or trace arguments or results.** Tests assert this.
- **Fail closed.** Anything unexpected in identity, policy or approval is a refusal.
- Keep backends and sample data synthetic. No real names, customer data or internal documents.

## Commit messages

Imperative mood, a short summary line, and a body that says why when it is not obvious.
