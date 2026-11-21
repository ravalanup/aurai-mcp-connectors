# Approvals

A write that policy says needs human approval runs only with a **signed, single-use token naming exactly that call**.

## The token

HS256 JWT, signed with `AURAI_APPROVAL_SIGNING_KEY` (32+ characters), carried in the `X-Aurai-Approval` request header.
It is a header, not a tool argument, so the model cannot write one into its own call.

| Claim | Meaning |
| --- | --- |
| `tool` | the tool it was granted for |
| `args_hash` | SHA-256 of the canonical JSON of the arguments (sorted keys, no whitespace) |
| `team`, `use_case` | the caller it was granted to |
| `approvers` | the distinct people who approved |
| `iat`, `exp` | issue and expiry; never more than 15 minutes apart |
| `jti` | single-use id |

## What the connector checks, in order

Signature, expiry and lifetime cap; same tool; same team and use case; same arguments; approvers are well formed and
**do not include the caller** (an agent cannot approve its own action); enough distinct approvers (T2 write: 1, T3
write: 2, `always` tools: at least 1); then, last, the `jti` is claimed. A token that fails any earlier check is not
consumed, so a typo does not burn a real approval. A used token is refused (`approval token was already used`).

## What the caller sees

Without a token, a call that needs approval returns an error result:

```json
{"error": "approval_required", "approvals_required": 1, "args_hash": "…", "tool": "messages_send", "message": "…"}
```

An approval service (in the platform, the agent runtime) shows the proposed call to the approvers, and after they
approve it, mints a token for that `tool` and `args_hash` and the agent retries with the header. A token for a
different draft, different arguments or a different team is refused.

## Single use across replicas

`MemoryUsedTokens` is correct for one replica. With more than one, set `config.redisUrl`; `RedisUsedTokens` claims the
id with `SET NX EX`, so a token works once across all pods. The AWS values enable it.

## Development

`aurai-connectors approve --tool messages_send --arguments '{"draft_id":"DRF-1"}' --team ops-insights --use-case x
--approver alice` prints a token. It stands in for the approval service and needs the same key.

## What is not here

The approval service itself (UI, notification, who may approve what), key rotation, and asymmetric signing (so
connectors hold only a public key) are production work. See the README.
