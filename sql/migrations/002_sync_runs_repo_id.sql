-- 002: link each sync run to its repo. NULL when the repo was never saved (e.g. a 404).
ALTER TABLE sync_runs ADD COLUMN repo_id bigint REFERENCES repos (id);

UPDATE sync_runs s
SET repo_id = r.id
FROM repos r
WHERE lower(r.full_name) = lower(s.repo_full_name);
