"""aurai-connectors serve <connector> | check | approve."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .approvals import issue_approval_token
from .reviews import check_policy_references, check_reviews
from .settings import Settings
from .wiring import MODULES, build_server, http_app


def _serve(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    server = build_server(args.connector, settings)
    if args.transport == "stdio":
        server.run(transport="stdio")
        return 0
    import uvicorn

    uvicorn.run(http_app(server, settings), host=args.host, port=args.port, log_level="info")
    return 0


def _check(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    problems = check_reviews(settings.connectors_dir)
    problems += check_policy_references(settings.connectors_dir, settings.policy_dir / "teams.yaml")
    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    if not problems:
        print("connector reviews and policy references are consistent")
    return 1 if problems else 0


def _approve(args: argparse.Namespace) -> int:
    """Development stand-in for the approval service: mint a token for one exact call."""
    secret = os.environ.get("AURAI_APPROVAL_SIGNING_KEY", "")
    if len(secret) < 32:
        print("set AURAI_APPROVAL_SIGNING_KEY (32+ characters)", file=sys.stderr)
        return 2
    token = issue_approval_token(
        secret,
        tool=args.tool,
        arguments=json.loads(args.arguments),
        team=args.team,
        use_case=args.use_case,
        approvers=args.approver,
    )
    print(token)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aurai-connectors")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run one connector as an MCP server")
    serve.add_argument("connector", choices=sorted(MODULES))
    serve.add_argument("--transport", choices=["http", "stdio"], default="http")
    serve.add_argument("--host", default="0.0.0.0")  # noqa: S104 - the pod network is the boundary
    serve.add_argument("--port", type=int, default=8080)
    serve.set_defaults(func=_serve)

    check = sub.add_parser("check", help="verify security reviews and policy references (run in CI)")
    check.set_defaults(func=_check)

    approve = sub.add_parser("approve", help="development: mint an approval token for one exact call")
    approve.add_argument("--tool", required=True)
    approve.add_argument("--arguments", required=True, help="the tool arguments as JSON")
    approve.add_argument("--team", required=True)
    approve.add_argument("--use-case", required=True)
    approve.add_argument("--approver", action="append", required=True)
    approve.set_defaults(func=_approve)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
