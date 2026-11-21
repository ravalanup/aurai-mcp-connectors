{{- define "aurai-connectors.labels" -}}
app.kubernetes.io/part-of: aurai
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
aurai.io/environment: {{ .Values.global.environment | quote }}
{{- end -}}

{{/* The pod selector of one connector. */}}
{{- define "aurai-connectors.selector" -}}
app.kubernetes.io/name: aurai-connector
app.kubernetes.io/instance: {{ .root.Release.Name }}
aurai.io/connector: {{ .name }}
{{- end -}}

{{- define "aurai-connectors.image" -}}
{{ required "image.repository must be set" .Values.image.repository }}:{{ .Values.image.tag }}
{{- end -}}

{{- define "aurai-connectors.securityContext" -}}
runAsNonRoot: true
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
seccompProfile:
  type: RuntimeDefault
{{- end -}}
