-- Pheromone deposits over time by channel, for a given run_id.
-- Each agent tick emits a span; pheromone write events are span events
-- with name 'pheromone.deposit'.
SELECT
  from_unixtime(start_time_unix_nano / 1000000000) AS ts,
  json_extract_scalar(attributes, '$["formica.channel"]') AS channel,
  cast(json_extract_scalar(attributes, '$["formica.amount"]') AS double) AS amount,
  json_extract_scalar(attributes, '$["formica.caste"]')     AS caste,
  json_extract_scalar(attributes, '$["formica.edge_id"]')   AS edge_id
FROM traces
WHERE name = 'pheromone.deposit'
  AND json_extract_scalar(resource, '$["formica.run_id"]') = :run_id
ORDER BY start_time_unix_nano ASC;
