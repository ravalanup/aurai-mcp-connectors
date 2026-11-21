#!/usr/bin/env bash
# Build and install the Aurai MCP connectors on the local kind cluster. Mirrors deploy-local.ps1.
# Requires: docker, kind, kubectl, helm. AURAI_APPROVAL_SIGNING_KEY is generated when not set.
set -euo pipefail
CLUSTER="${CLUSTER:-aurai}"; NS="${NS:-aurai-connectors}"; IMAGE="${IMAGE:-aurai-connectors:0.1.0}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
for t in docker kind kubectl helm; do command -v "$t" >/dev/null || { echo "missing $t" >&2; exit 1; }; done

kubectl config use-context "kind-$CLUSTER" >/dev/null
docker build -t "$IMAGE" "$REPO"
docker run --rm "$IMAGE" check
kind load docker-image "$IMAGE" --name "$CLUSTER"

kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl label namespace "$NS" aurai.io/platform-access=true --overwrite >/dev/null
if [ -z "${AURAI_APPROVAL_SIGNING_KEY:-}" ]; then
  AURAI_APPROVAL_SIGNING_KEY="$(head -c 32 /dev/urandom | base64)"
  echo "Generated an approval signing key. Keep it: the approval service needs the same value."
  echo "  AURAI_APPROVAL_SIGNING_KEY=$AURAI_APPROVAL_SIGNING_KEY"
fi
kubectl apply -f - >/dev/null <<YAML
apiVersion: v1
kind: Secret
metadata: { name: connectors-secrets, namespace: $NS }
type: Opaque
stringData:
  AURAI_APPROVAL_SIGNING_KEY: "$AURAI_APPROVAL_SIGNING_KEY"
YAML

helm upgrade --install aurai-connectors "$REPO/charts/aurai-connectors" -n "$NS" \
  -f "$REPO/charts/aurai-connectors/values-local.yaml" \
  --set image.repository="${IMAGE%%:*}" --set image.tag="${IMAGE##*:}" \
  --set-file policy.rego="$REPO/policy/aurai/tools.rego" \
  --set-file policy.teams="$REPO/policy/teams.yaml" --wait --timeout 3m
kubectl get pods -n "$NS"
echo "Done. Each connector is at http://connector-<name>.$NS.svc.cluster.local:8080/mcp"
