<#
.SYNOPSIS
  Run one connector on this machine over stdio, for use from an MCP client (Claude Desktop, an inspector) without a cluster.

.DESCRIPTION
  stdio has no HTTP headers, so the caller is the development identity: AURAI_DEV_CALLER=<team>:<use_case>, honoured only
  when AURAI_ALLOW_DEV_IDENTITY=1. Policy is still evaluated, by the opa binary on PATH against policy\. Approvals still
  apply: mint a token with `aurai-connectors approve` and pass it as the X-Aurai-Approval header from an HTTP client; a
  stdio client cannot send headers, so writes that need approval are exercised over HTTP (docs\local-development.md).
#>
param(
  [ValidateSet("tickets", "ops-data", "messaging", "files")][string]$Connector = "ops-data",
  [string]$Team = "ops-insights",
  [string]$UseCase = "local-dev"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
if (-not (Get-Command opa -ErrorAction SilentlyContinue)) { throw "opa is not on PATH (https://www.openpolicyagent.org/docs/#running-opa)" }
$env:AURAI_ALLOW_DEV_IDENTITY = "1"
$env:AURAI_DEV_CALLER = "${Team}:${UseCase}"
$env:AURAI_CONNECTORS_DIR = "$repo\connectors"
$env:AURAI_POLICY_DIR = "$repo\policy"
aurai-connectors serve $Connector --transport stdio
