-- Spawn/retire events by caste for a given env+region, last 6 hours.
SELECT
  from_unixtime(start_time_unix_nano / 1000000000) AS ts,
  name AS event,
  json_extract_scalar(attributes, '$["formica.caste"]')   AS caste,
  json_extract_scalar(attributes, '$["formica.agent_id"]') AS agent_id,
  json_extract_scalar(attributes, '$["formica.reason"]')   AS reason
FROM traces
WHERE name IN ('controller.spawn', 'controller.retire')
  AND json_extract_scalar(resource, '$["formica.env"]')    = :env
  AND json_extract_scalar(resource, '$["formica.region"]') = :region
  AND start_time_unix_nano >= (to_unixtime(current_timestamp) - 21600) * 1000000000
ORDER BY start_time_unix_nano DESC;
