-- Validator verdicts grouped by validator kind and outcome for a run.
SELECT
  json_extract_scalar(attributes, '$["formica.validator_kind"]') AS kind,
  split_part(name, '.', 2) AS verdict,
  count(*) AS n,
  avg(cast(json_extract_scalar(attributes, '$["formica.confidence"]') AS double)) AS avg_confidence
FROM traces
WHERE name LIKE 'validator.%'
  AND json_extract_scalar(resource, '$["formica.run_id"]') = :run_id
GROUP BY json_extract_scalar(attributes, '$["formica.validator_kind"]'), split_part(name, '.', 2)
ORDER BY n DESC;
