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
Security settings of the containers of the app; no fixed user ID, as OpenShift
assigns its own. The image's own user otherwise.
*/}}
{{- define "pubgrade.securityContext" -}}
allowPrivilegeEscalation: false
capabilities:
  drop:
    - ALL
runAsNonRoot: true
seccompProfile:
  type: RuntimeDefault
{{- end -}}
