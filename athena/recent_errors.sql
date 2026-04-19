-- Recent errors across all components in the last 24 hours.
-- Run against the formica_otel_{env}_{region} database.
SELECT
  from_unixtime(time_unix_nano / 1000000000) AS ts,
  severity_text,
  trace_id,
  json_extract_scalar(resource, '$["formica.component"]') AS component,
  body
FROM logs
WHERE year  = year(current_date)
  AND month = month(current_date)
  AND severity_text IN ('ERROR', 'CRITICAL', 'FATAL')
  AND time_unix_nano >= (to_unixtime(current_timestamp) - 86400) * 1000000000
ORDER BY time_unix_nano DESC
LIMIT 500;
