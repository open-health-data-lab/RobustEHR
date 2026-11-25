# MTSamples — public-domain transcribed reports, downloaded, never committed

**What.** `mtsamples.csv`: about 5,000 sample medical transcription reports across 40
specialties, scraped from mtsamples.com and released on Kaggle under CC0 (columns
`description, medical_specialty, sample_name, transcription, keywords`). A real, non-MIMIC,
dictated-genre corpus used to show the structural layer and the operator suite run unchanged
on notes the package was not developed on.
**Get it.** https://www.kaggle.com/datasets/tboyle10/medicaltranscriptions, or a public mirror:
    curl -L -o data/mtsamples/mtsamples.csv \
      https://raw.githubusercontent.com/singla007/MTSamples/master/mtsamples.csv
The corpus loader needs `(note_id, text)`: `validation/pipeline/scripts/mtsamples_corpus.py`
writes `data/mtsamples/notes.csv` (deterministic hash-ranked sample) from the CSV.
**Licence.** CC0 1.0 (public domain). Kept out of the repository only because nothing in `src/`
needs 17 MB of text; the aggregate measurements ship under `validation/measurements/corpus/`.
**Needed by.** The cross-corpus characterisation in `validation/measurements/corpus/`. Not needed
by the core install.
**Never commit.** Denied by `data/*/*`; only this file is tracked.
