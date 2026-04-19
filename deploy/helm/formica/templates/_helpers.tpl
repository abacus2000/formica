{{/*
Common helpers.
*/}}
{{- define "formica.name" -}}
formica
{{- end -}}

{{- define "formica.labels" -}}
app.kubernetes.io/name: {{ include "formica.name" . }}
app.kubernetes.io/instance: formica
app.kubernetes.io/managed-by: helm
formica.env: {{ .Values.env | quote }}
formica.region: {{ .Values.region | quote }}
{{- end -}}

{{- define "formica.s3bucket" -}}
{{- if .Values.otel.bucket -}}{{ .Values.otel.bucket }}{{- else -}}formica-otel-{{ .Values.env }}-{{ .Values.region }}{{- end -}}
{{- end -}}

{{- define "formica.errorsGroup" -}}
{{- if .Values.cloudwatch.errorsGroup -}}{{ .Values.cloudwatch.errorsGroup }}{{- else -}}/formica/{{ .Values.env }}/{{ .Values.region }}/errors{{- end -}}
{{- end -}}

{{- define "formica.driversGroup" -}}
{{- if .Values.cloudwatch.driversGroup -}}{{ .Values.cloudwatch.driversGroup }}{{- else -}}/formica/{{ .Values.env }}/{{ .Values.region }}/drivers{{- end -}}
{{- end -}}

{{- define "formica.retentionDays" -}}
{{- if eq .Values.env "prod" -}}{{ .Values.cloudwatch.retentionDaysProd }}{{- else -}}{{ .Values.cloudwatch.retentionDaysDev }}{{- end -}}
{{- end -}}
