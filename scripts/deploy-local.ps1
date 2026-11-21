<#
.SYNOPSIS
  Build and install the Aurai MCP connectors on the local kind cluster.

.DESCRIPTION
  Prerequisites
    - aurai-infra running (Keycloak, OTel collector) and a kind cluster. Docker, kind, kubectl, helm.
    - Callers need Keycloak service-account clients with team_id and use_case_id claims and the aurai-connectors
      audience; this repo does not create them (see docs\identity.md).
  What it does
    1. Builds the image and loads it into kind.
    2. Creates the namespace (labelled for platform access) and the connectors-secrets Secret holding the approval
       signing key. Pass -ApprovalKey to use an existing key; otherwise a random one is generated and printed once.
    3. Runs the same checks CI runs (aurai-connectors check) inside the image, so a connector without a security review
       does not deploy.
    4. Installs the chart with the Rego and team scopes from policy\.
#>
param(
  [string]$ClusterName = "aurai",
  [string]$Namespace = "aurai-connectors",
  [string]$Image = "aurai-connectors:0.1.0",
  [string]$ApprovalKey = $env:AURAI_APPROVAL_SIGNING_KEY
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

foreach ($tool in "docker", "kind", "kubectl", "helm") {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Missing required tool: $tool" }
}

kubectl config use-context "kind-$ClusterName" | Out-Null

Write-Host "Building $Image"
docker build -t $Image $repo
if ($LASTEXITCODE -ne 0) { throw "docker build failed" }

Write-Host "Checking security reviews and policy references"
docker run --rm $Image check
if ($LASTEXITCODE -ne 0) { throw "connector checks failed; fix the reported problems before deploying" }

kind load docker-image $Image --name $ClusterName
if ($LASTEXITCODE -ne 0) { throw "kind load failed" }

kubectl create namespace $Namespace --dry-run=client -o yaml | kubectl apply -f - | Out-Null
kubectl label namespace $Namespace aurai.io/platform-access=true --overwrite | Out-Null

if (-not $ApprovalKey) {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $ApprovalKey = [Convert]::ToBase64String($bytes)
  Write-Host "Generated an approval signing key. Keep it: the approval service needs the same value."
  Write-Host "  AURAI_APPROVAL_SIGNING_KEY=$ApprovalKey"
}

@"
apiVersion: v1
kind: Secret
metadata: { name: connectors-secrets, namespace: $Namespace }
type: Opaque
stringData:
  AURAI_APPROVAL_SIGNING_KEY: "$ApprovalKey"
"@ | kubectl apply -f - | Out-Null

$repository, $tag = $Image.Split(":")
helm upgrade --install aurai-connectors "$repo\charts\aurai-connectors" -n $Namespace `
  -f "$repo\charts\aurai-connectors\values-local.yaml" `
  --set image.repository=$repository --set image.tag=$tag `
  --set-file policy.rego="$repo\policy\aurai\tools.rego" `
  --set-file policy.teams="$repo\policy\teams.yaml" --wait --timeout 3m
if ($LASTEXITCODE -ne 0) { throw "helm install failed" }

kubectl get pods -n $Namespace
Write-Host "Done. Each connector is at http://connector-<name>.$Namespace.svc.cluster.local:8080/mcp"
