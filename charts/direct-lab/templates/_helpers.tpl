{{- define "direct-lab.fullname" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "direct-lab.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "direct-lab.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Mongo connection string for the app, built from values so no code change is
needed if the Bitnami subchart's naming/auth model changes — only this
helper and values.yaml need to move together.
*/}}
{{- define "direct-lab.mongoUri" -}}
mongodb://{{ .Values.app.mongoUser }}:$(MONGO_PASSWORD)@{{ .Values.mongodb.fullnameOverride }}:27017/{{ .Values.app.mongoDatabase }}
{{- end -}}
