"""Outpatient and clinic notes.

The least uniform setting in the corpus, and the one most likely to break a
segmenter tuned on discharge summaries. Templates are optional here and many
clinicians ignore them: a family-medicine visit may be a single unbroken
paragraph, a dermatology note may be three lines, a psychiatry note may be
mostly verbatim patient speech. There is often no section header anywhere in
the document.
"""

from __future__ import annotations

from tests.fixtures.clinical import SyntheticNote

# --------------------------------------------------------------------------
# The common case nobody templates: one paragraph, no headers, no structure.
# --------------------------------------------------------------------------
FAMILY_MED_FREETEXT = SyntheticNote(
    id="family_med_freetext",
    setting="outpatient",
    specialty="family_medicine",
    note_type="clinic_note",
    structure="free_text",
    source_style="community_emr",
    deid_scheme="none",
    hard_wrapped=False,
    language="en-CA",
    stresses="no headers at all, run-on prose, inline abbreviations, pre-existing typos",
    text="""\
Pt seen today for f/u of htn and dyslipidemia. BP today 138/84, was 142/90 last visit. Reports good adherence to perindopril 8mg daily, no cough, no dizziness. Has been walking 30 min most days and cut back on salt. Denies chest pain, SOB, palpitations, headaches or visual changes. No LE edema. Recent bloodwork reviewed - LDL 2.4, HbA1c 5.8, creat stable at 78. Weight down 2kg since last visit which is encouraging. Discussed continuing current regimen, recheck BP in 3 months, repeat lipids in 6 months. Also breifly discussed shingles vaccine, pt will think about it. Reminded re: importance of ongoing lifestyle measures. Pt agreeable to plan, no questions at end of visit.
""",
)

# --------------------------------------------------------------------------
# Dictated and transcribed: spoken punctuation leaks through, and the
# transcriptionist's conventions differ from any template.
# --------------------------------------------------------------------------
CARDIOLOGY_DICTATED = SyntheticNote(
    id="cardiology_dictated",
    setting="outpatient",
    specialty="cardiology",
    note_type="consultation",
    structure="dictated",
    source_style="transcription_service",
    deid_scheme="bracket_star",
    hard_wrapped=True,
    language="en-US",
    stresses="dictation artifacts, spoken punctuation, device and EF values, run-on sentences",
    text="""\
CARDIOLOGY CONSULTATION NOTE

Thank you for referring [**Known patient**] who I had the pleasure of seeing
in clinic today period This is a [**Age**] year old gentleman with a known
history of ischemic cardiomyopathy comma status post anterior myocardial
infarction in [**Date**] comma with a most recent ejection fraction of
thirty to thirty five percent period

He reports New York Heart Association class two symptoms comma with dyspnea
on climbing one flight of stairs but no orthopnea or paroxysmal nocturnal
dyspnea period Weight has been stable period He denies syncope or
palpitations period

On examination blood pressure one hundred eighteen over seventy two heart
rate sixty four regular period JVP not elevated period Heart sounds normal
with no gallop period Chest clear period No peripheral edema period

Device interrogation today shows appropriate ICD function comma no
ventricular arrhythmias since last check comma battery longevity estimated
at four years period

Impression comma stable ischemic cardiomyopathy on optimal medical therapy
period Plan comma continue current medications comma repeat echocardiogram
in twelve months comma follow up in clinic in six months period
""",
)

# --------------------------------------------------------------------------
# Psychiatry: verbatim patient speech in quotes, a structured mental status
# exam embedded in prose, and risk documentation.
# --------------------------------------------------------------------------
PSYCHIATRY_CLINIC = SyntheticNote(
    id="psychiatry_clinic",
    setting="outpatient",
    specialty="psychiatry",
    note_type="follow_up",
    structure="semi_structured",
    source_style="community_emr",
    deid_scheme="square_tag",
    hard_wrapped=True,
    language="en-US",
    stresses="verbatim quotes containing punctuation, MSE sub-labels, negated risk assertions",
    text="""\
Interval History:
[PATIENT] returns four weeks after starting sertraline 50 mg daily. She
states, "I think it's helping a bit? I'm not crying every day anymore."
Sleep has improved from 4 to 6 hours nightly. Appetite remains poor. She
reports her mother asked her, "are you sure you need those pills?", which
she found upsetting.

Mental Status Exam:
Appearance: casually dressed, fair grooming. Behaviour: cooperative, good
eye contact. Speech: normal rate and volume. Mood: "okay I guess".
Affect: constricted, reactive. Thought process: linear. Thought content:
no delusions. Perception: no hallucinations. Cognition: alert, oriented x3.
Insight and judgement: fair.

Risk: Denies current suicidal ideation, intent or plan. No self-harm since
last visit. No access to firearms. Protective factors include her children
and her sister.

Plan: increase sertraline to 100 mg daily. Continue weekly CBT. Return in
4 weeks, sooner if worsening. Crisis line number provided and reviewed.
""",
)

# --------------------------------------------------------------------------
# Dermatology: extremely short, lesion morphology, site-specific shorthand.
# --------------------------------------------------------------------------
DERMATOLOGY_BRIEF = SyntheticNote(
    id="dermatology_brief",
    setting="outpatient",
    specialty="dermatology",
    note_type="clinic_note",
    structure="telegraphic",
    source_style="specialty_emr",
    deid_scheme="none",
    hard_wrapped=False,
    language="en-US",
    stresses="ultra-short note, measurement shorthand, site abbreviations, no sentences",
    text="""\
6mm irregular pigmented macule L upper back, asymmetric borders, variegated brown/black. Dermoscopy: atypical network, blue-white veil.
Shave bx performed, sent to path. Sutures n/a.
2 seborrheic keratoses R shoulder, benign appearance, no tx.
RTC pending path.
""",
)

# --------------------------------------------------------------------------
# Obstetrics: G/P notation, gestational age in weeks+days, fetal measurements.
# --------------------------------------------------------------------------
OBSTETRICS_PRENATAL = SyntheticNote(
    id="obstetrics_prenatal",
    setting="outpatient",
    specialty="obstetrics",
    note_type="prenatal_visit",
    structure="templated",
    source_style="specialty_emr",
    deid_scheme="xxx_run",
    hard_wrapped=False,
    language="en-US",
    stresses="G/P notation, weeks+days gestational age, pick-list residue, checkbox fields",
    text="""\
PRENATAL VISIT

G3P1A1  EDD: XX/XX/XXXX  GA today: 28w4d

Fundal height: 29 cm     FHR: 148 bpm     Presentation: cephalic
BP: 112/68     Wt: 71.2 kg (+0.9 kg)     Urine: protein [ ] glucose [ ]

Fetal movement:  [X] normal   [ ] decreased   [ ] absent
Contractions:    [ ] yes      [X] no
Bleeding:        [ ] yes      [X] no
Leaking fluid:   [ ] yes      [X] no

Reviewed 1hr GTT result 7.2 mmol/L - normal. Anti-D not indicated, mother Rh positive.
Discussed signs of preterm labour and when to present to triage.

Next visit: 2 weeks. Anticipate GBS swab at 36w.
""",
)

# --------------------------------------------------------------------------
# Oncology: staging, regimen and cycle notation, toxicity grading.
# --------------------------------------------------------------------------
ONCOLOGY_CLINIC = SyntheticNote(
    id="oncology_clinic",
    setting="outpatient",
    specialty="oncology",
    note_type="treatment_visit",
    structure="problem_oriented",
    source_style="specialty_emr",
    deid_scheme="underscore_run",
    hard_wrapped=True,
    language="en-US",
    stresses="staging notation, regimen abbreviations, CTCAE grades, cycle numbering",
    text="""\
Diagnosis: Stage IIIA (T2N2M0) adenocarcinoma of the left lower lobe,
EGFR wild type, ALK negative, PD-L1 TPS 40%.

Interval History:
___ presents for cycle 4 day 1 of carboplatin/pemetrexed. Tolerated cycle 3
reasonably. Reports grade 1 fatigue and grade 1 nausea controlled with
ondansetron. No neuropathy. No mucositis. No fevers.

Labs today: WBC 4.1, ANC 2.2, Hgb 10.4, Plt 168, Cr 0.9, LFTs within normal
limits.

Assessment and Plan:
# NSCLC: proceed with cycle 4 today at full dose. Restaging CT after cycle 4.
# Anemia: chemotherapy related, Hgb stable, no transfusion indicated.
# Nausea: continue ondansetron PRN, add prochlorperazine as second line.
# Supportive: continue dexamethasone premedication per protocol.
""",
)

# --------------------------------------------------------------------------
# Mixed French/English, as commonly written in Quebec. Diacritics and
# code-switching within a single sentence.
# --------------------------------------------------------------------------
QUEBEC_MIXED_LANGUAGE = SyntheticNote(
    id="quebec_mixed_language",
    setting="outpatient",
    specialty="endocrinology",
    note_type="follow_up",
    structure="free_text",
    source_style="quebec_emr",
    deid_scheme="square_tag",
    hard_wrapped=False,
    language="fr-CA-mixed",
    stresses="code-switching mid-sentence, accented characters, French drug names, metric units",
    text="""\
Suivi diabète type 2. Pt revu aujourd'hui, HbA1c à 7,9% (était 8,4% en [DATE]). Prend metformine 1000 mg BID et empagliflozine 10 mg die. Pas d'hypoglycémie rapportée. Glycémies à jeun entre 6,5 et 8,2 mmol/L selon son carnet.

Poids 88,4 kg, stable. TA 134/82. Examen des pieds fait aujourd'hui : monofilament normal bilatéralement, pas de lésion, pouls pédieux présents. Dernier fond d'oeil il y a 14 mois - à refaire.

Plan : on augmente empagliflozine à 25 mg die. Référence en ophtalmo pour rétinopathie screening. Bilan lipidique et créatinine dans 3 mois. Revoir dans 4 mois. Patient understands and agrees with the plan, will call if any issues.
""",
)

# --------------------------------------------------------------------------
# A two-line addendum. Real charts are full of these and they break anything
# that assumes a note has sections.
# --------------------------------------------------------------------------
ADDENDUM = SyntheticNote(
    id="addendum",
    setting="outpatient",
    specialty="family_medicine",
    note_type="addendum",
    structure="free_text",
    source_style="community_emr",
    deid_scheme="none",
    hard_wrapped=False,
    language="en-US",
    stresses="two lines, no structure, no de-identification, degenerate denominators",
    text="""\
Addendum: path result back, benign. Pt notified by phone, verbalized understanding.
No further follow up needed for this issue.
""",
)

# --------------------------------------------------------------------------
# Markdown-structured clinic note. Hash headings rather than colon labels,
# which collides with the clinical convention of "# Hypertension" as a
# problem-list bullet.
# --------------------------------------------------------------------------
MARKDOWN_CLINIC = SyntheticNote(
    id="markdown_clinic",
    setting="outpatient",
    specialty="rheumatology",
    note_type="clinic_note",
    structure="templated",
    source_style="modern_emr",
    deid_scheme="square_tag",
    hard_wrapped=False,
    language="en-US",
    stresses="markdown hash headings instead of colon labels, dash bullets",
    text="""\
# Rheumatology Follow-up

## Subjective

[PATIENT] returns for follow-up of seropositive rheumatoid arthritis. Reports improved morning stiffness, now lasting about 20 minutes compared with two hours at last visit. Denies new joint swelling.

## Objective

- Vitals within normal limits
- Joint exam: no active synovitis of the MCP or PIP joints bilaterally
- CRP 4 mg/L, ESR 12 mm/hr

## Assessment and Plan

- Rheumatoid arthritis, well controlled on methotrexate 20 mg weekly
- Continue folic acid supplementation
- Repeat liver function tests in three months
""",
)

NOTES: tuple[SyntheticNote, ...] = (
    FAMILY_MED_FREETEXT,
    MARKDOWN_CLINIC,
    CARDIOLOGY_DICTATED,
    PSYCHIATRY_CLINIC,
    DERMATOLOGY_BRIEF,
    OBSTETRICS_PRENATAL,
    ONCOLOGY_CLINIC,
    QUEBEC_MIXED_LANGUAGE,
    ADDENDUM,
)
