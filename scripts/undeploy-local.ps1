<# Remove the connectors, their secret and the namespace. #>
param([string]$Namespace = "aurai-connectors")
helm uninstall aurai-connectors -n $Namespace
kubectl delete secret connectors-secrets -n $Namespace --ignore-not-found
kubectl delete namespace $Namespace --ignore-not-found
