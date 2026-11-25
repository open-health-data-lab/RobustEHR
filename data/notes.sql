-- Extraction query for the development corpus.
--
-- This is the one file in `data/` besides the README that is committed, and it
-- is committed for a specific reason: note text is restricted under the
-- PhysioNet Credentialed Health Data Use Agreement and can never be published,
-- but the *query that selects it* can. A credentialed reader runs this against
-- their own MIMIC-IV and gets the same corpus, which is what makes the edit
-- scripts and hashes RobustEHR publishes replayable by someone else.
--
-- Written for MIMIC-IV v2.2+ on PostgreSQL, against the `mimiciv_note` schema.
-- BigQuery works with the table names changed to
-- `physionet-data.mimiciv_note.discharge` and `...mimiciv_hosp.admissions`.
--
-- Usage:
--   psql -d mimiciv -v ON_ERROR_STOP=1 -f data/notes.sql \
--        --csv -o data/golden_notes.csv
--
-- Output columns are exactly what the corpus reader expects:
--
--   note_id     required, unique, stable
--   text        required, the note body
--   patient_id  optional; enables `discourse.stale_copy_forward` and
--               patient-clustered resampling
--   timestamp   optional; orders the copy-forward donor
--
-- No label column is selected, and none is needed: choosing phenotypes drives
-- protect/target behaviour through concept sets, never through labels.

SELECT
    d.note_id                       AS note_id,
    d.subject_id                    AS patient_id,
    d.charttime                     AS timestamp,
    d.text                          AS text
FROM mimiciv_note.discharge AS d
-- Restrict to admissions, so `patient_id` and `timestamp` are meaningful for
-- the copy-forward operator. An inner join is deliberate: a note whose
-- admission is missing cannot be ordered against its siblings, and a donor
-- chosen from an unordered set would make copy-forward non-deterministic.
JOIN mimiciv_hosp.admissions AS a
    ON a.hadm_id = d.hadm_id
WHERE d.text IS NOT NULL
  AND length(d.text) > 0
-- Deterministic order. Not cosmetic: the corpus reader assigns nothing from
-- row position, but a stable dump means two credentialed readers produce
-- byte-identical CSVs, and therefore identical hashes to compare against ours.
ORDER BY d.note_id;
