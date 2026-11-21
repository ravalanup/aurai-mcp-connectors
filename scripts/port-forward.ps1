<# Port-forward one connector to http://localhost:8080/mcp for direct testing (docs\local-development.md). #>
param(
  [ValidateSet("tickets", "ops-data", "messaging", "files")][string]$Connector = "tickets",
  [string]$Namespace = "aurai-connectors",
  [int]$Port = 8080
)
$ErrorActionPreference = "Stop"
Write-Host "Connector '$Connector' at http://localhost:$Port/mcp   (Ctrl+C to stop)"
kubectl port-forward -n $Namespace "svc/connector-$Connector" "${Port}:8080"
