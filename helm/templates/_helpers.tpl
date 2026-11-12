{{/*
Labels selecting one component's pods; each Service selects only its own.
Call with the component's name.
*/}}
{{- define "pubgrade.selectorLabels" -}}
app.kubernetes.io/name: pubgrade
app.kubernetes.io/component: {{ . }}
{{- end -}}

{{/*
Whether an OpenShift Route is created ("true") or not (empty); as in the chart
foca-common.
*/}}
{{- define "pubgrade.routeEnabled" -}}
{{- if and .Values.pubgrade.route.enabled (not .Values.pubgrade.ingress.enabled) (.Capabilities.APIVersions.Has "route.openshift.io/v1") -}}
true
{{- end -}}
{{- end -}}

{{/*
A security context (of a pod or a container) from the values, as YAML; nothing
if it is empty. An empty `seccompProfile` (`{}`) is left out, like one removed
with `null`, so that the cluster's own profile applies (e.g., on OpenShift).
Call with the context's values.
*/}}
{{- define "pubgrade.securityContext" -}}
{{- $context := . | default dict -}}
{{- if not $context.seccompProfile -}}
{{- $context = omit $context "seccompProfile" -}}
{{- end -}}
{{- with $context -}}
{{- toYaml . -}}
{{- end -}}
{{- end -}}
