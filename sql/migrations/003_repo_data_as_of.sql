-- 003: one place for "when was this repo's data last fully collected".
-- data_as_of = finished_at of the latest successful sync run; NULL if none succeeded
-- (the success filter is in the JOIN, so repos without one are still included).
CREATE VIEW repo_data_as_of AS
SELECT r.id AS repo_id, max(s.finished_at) AS data_as_of
FROM repos r
LEFT JOIN sync_runs s ON s.repo_id = r.id AND s.status = 'success'
GROUP BY r.id;
