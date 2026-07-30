\pset pager off

-- I1 canonical gate plus all three Never passes and the absence check.
SELECT
  injection_id,
  prompt_text,
  scorer_version,
  memory_id,
  shown_as,
  rank,
  score,
  outcome,
  features
FROM injection_event
WHERE injection_id IN (
  '757de54b-d1b1-4a0a-8294-a3fbd43e3161',
  'c0261ada-60da-41f3-a031-4ff1caa4fd6e',
  '3c207a91-ac1b-49b5-8d66-9d965e049f2c',
  '7fcd64c0-30fc-454f-922b-c9dc54227bc5',
  '22d9370f-fc31-427c-9b3d-2de458428144'
)
ORDER BY ts, injection_id, rank, memory_id;

-- Immutable event snapshot versus the subsequently edited current head.
SELECT
  e.memory_id,
  e.shown_as,
  e.outcome,
  e.features -> '_memory' ->> 'body' AS frozen_body,
  u.body AS current_head_body,
  e.features -> '_memory' ->> 'body' = u.body
    AS snapshot_still_matches_head
FROM injection_event e
JOIN memory_unit u ON u.id = e.memory_id
WHERE e.injection_id = '757de54b-d1b1-4a0a-8294-a3fbd43e3161'
ORDER BY e.rank;

-- AC2 preference and AC5 /remember heads.
SELECT
  id,
  label,
  status,
  revision,
  pin,
  embedding IS NOT NULL AS has_embedding,
  body
FROM memory_unit
WHERE id IN (
  '5835cff3-a653-4627-8dbe-debdaed13694',
  'a93ae3df-9f28-4f68-95a9-d786deb284ad'
)
ORDER BY id;

SELECT
  memory_id,
  revision,
  rev_uid,
  parent_uid,
  editor,
  reason,
  body
FROM memory_revision
WHERE memory_id IN (
  '5835cff3-a653-4627-8dbe-debdaed13694',
  'a93ae3df-9f28-4f68-95a9-d786deb284ad'
)
ORDER BY memory_id, revision;

-- AC4 quarantine state and fourth-gate absence.
SELECT
  id,
  status,
  revision,
  bias,
  stats ->> 'never_kills' AS never_kills,
  stats ->> 'removals' AS removals,
  stats ->> 'injections' AS injections,
  body
FROM memory_unit
WHERE id = '694df145-0caf-46f0-97c4-8ba343f6e7c7';

SELECT count(*) AS llama_rows_in_fourth_gate
FROM injection_event
WHERE injection_id = '22d9370f-fc31-427c-9b3d-2de458428144'
  AND memory_id = '694df145-0caf-46f0-97c4-8ba343f6e7c7';
