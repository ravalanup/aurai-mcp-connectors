# Writing a connector

A new connector needs four things, and CI fails without any of them.

1. **`connectors/<name>/connector.yaml`**: the connector name (equal to its folder) and every tool with `action`,
   `classification` (`public`, `internal`, `confidential`, `restricted` or `dynamic`), `approval` (`none`, `policy`,
   `always`; a write cannot be `none`) and a `description` the model will read. Write descriptions that say what the
   tool does and its limits, not how to use the system.
2. **`src/aurai_connectors/connectors/<name>.py`** with `NAME` and `build(governor, backend)`. Register each tool with
   `@governor.tool(server, "<tool>")`, validate arguments with `require(...)`, and finish with
   `governor.assert_complete()`. Add the module to `MODULES` in `wiring.py`.
3. **`connectors/<name>/review.yaml`**: the security review (owner, a different reviewer, date, `approved`, the tools
   reviewed, findings). It must list exactly the tools in the manifest.
4. **Policy**: add the connector to the teams that should have it in `policy/teams.yaml`, with a Rego or data test if
   the rules change.

## Rules for tool code

- **Return less.** Return the fields a task needs, not whole records. Everything returned goes to the model.
- **Dynamic classification**: when a tool's sensitivity depends on its arguments (a file's label), give the manifest
  `classification: dynamic` and pass `classify=` a function from arguments to a label. If it raises or returns an unknown
  label the call is judged `restricted`. Never classify from something the caller supplies unless you take the more
  sensitive of that and what is stored (see `files_write`).
- **Many-item tools** should filter by `current().decision.ceiling`, as `files_list` does.
- **Validate in the tool too.** Policy decides whether the caller may call the tool; the tool decides whether the
  arguments are sane (the messaging connector enforces its recipient domain even though policy already approved).
- **Raise `require(False, "...")`** for refusals the caller should see; any other exception becomes a generic error with
  nothing from the exception in it.
- **Do not log arguments or results.** The framework audits the call; tests assert no argument text reaches the log or
  a span.
- **No write tool without an approval path.** If a write is low-risk enough to skip approval at low tiers, use
  `approval: policy`: tiers T0 and T1 then run it directly and T2 and above need approval.

## Replacing a synthetic backend

The classes in `backends.py` stand in for real systems. A real connector swaps one of them for a client (a
work-management API, a warehouse, a mail service, a document store) behind the same methods, using credentials scoped to
what the connector's tools need and nothing more. The tool functions, manifest and policy do not change.
