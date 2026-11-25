"""Synthetic clinical notes carrying the pathologies that break naive segmenters.

Every case here was observed in real MIMIC-IV discharge summaries, but the text
is written from scratch and describes no real patient — so these fixtures are
public. They serve three jobs at once: golden-test inputs, documentation
examples, and the sample rendering in shareable HTML reports, none of which may
contain restricted text.

Each note is annotated with the trap it encodes.
"""

from __future__ import annotations

# ``___.`` at the end of a lab value reads as a sentence terminator, and the
# next clause runs straight into it. A generic sentence splitter breaks here.
DEID_IN_LAB_LINE = """\
Pertinent Results:
___ 03:10PM   PLT COUNT-___. Mood disorder, pain disorder with both a general
medical condition and psychological factors.
___ 09:57PM BLOOD WBC-6.9 RBC-4.46 Hgb-12.8 Hct-38.2 Plt ___
"""

# De-identification consumed the list number itself, so "___." is a list marker
# rather than a sentence boundary.
DEID_AS_LIST_NUMBER = """\
Past Medical History:
1. Hypertension
2. Type 2 diabetes mellitus
___. Cholecystectomy
___. Tonsillectomy
"""

# A run of four or more underscores is a horizontal rule, not a PHI mask. A lazy
# `_+` regex conflates the two and would "protect" layout while corrupting PHI
# masks, or vice versa.
DIVIDER_RULE = """\
Discharge Instructions:
________________________________________________________
Please take all medications as prescribed.
"""

# The sentence spans four physical lines. Sentence-level operators must see one
# unit; line-level operators must see four.
HARD_WRAPPED = """\
History of Present Illness:
Ms. ___ is a ___ year old woman well known to the psychiatry
service, discharged recently from the inpatient unit where she
was hospitalized, transferred to medicine, and then transferred
back to psychiatry.
"""

# A blank line falls *inside* a wrapped sentence. Any paragraph segmenter keyed
# on `\\n\\s*\\n` is wrong here.
BLANK_LINE_MIDSENTENCE = """\
Brief Hospital Course:
- Diagnosed as orthostatic hypotension with positive tilt table

testing after several syncopal episodes; started on midodrine
and advised to increase fluid intake.
"""

# One negation cue governs three targets. Flipping the cue changes all three,
# so the operator must report its collateral effects.
SHARED_NEGATION_CUE = """\
Review of Systems:
Denies chest pain, shortness of breath, and fever.
"""

# Double negation, and a scope terminator ("but"). Naive cue replacement
# produces text that asserts the opposite of what was intended.
DOUBLE_NEGATION = """\
Assessment and Plan:
No evidence of no residual thrombus on repeat imaging, but the
patient continues to report calf tenderness.
"""

# Experiencer is the fourth ConText dimension and the original taxonomy omitted
# it. Family history sections appear in essentially every discharge summary.
FAMILY_HISTORY = """\
Family History:
Mother with rheumatoid arthritis and hypothyroidism. Father with
myocardial infarction at age ___.

Social History:
Patient denies tobacco use. Reports 2 alcoholic drinks per week.
"""

# "RA" three ways in one note: room air, rheumatoid arthritis, right atrium.
# In the development corpus RA occurs 2,136 times across 74% of notes and is
# overwhelmingly room air, against a true RA prevalence of 11.8% — which is why
# blind abbreviation expansion cannot be called phenotype-preserving.
AMBIGUOUS_RA = """\
Physical Exam:
VITALS: Temp 98.2 BP 128/74 HR 78 RR 16 SpO2 97% on RA
GEN: Chronically ill appearing, no acute distress.

Brief Hospital Course:
Seropositive RA treated with methotrexate and prednisone, with
active synovitis of the MCP joints.
Echocardiogram showed RA mildly enlarged with normal RV function.
"""

# "PE" as physical exam in one place and pulmonary embolism in another, plus a
# rule-out mention that is precision-side rather than recall-side.
AMBIGUOUS_PE = """\
Admission PE: unremarkable, no calf tenderness.

Assessment:
CTA obtained to rule out PE; study was negative. History of PE in
___ treated with six months of anticoagulation.
"""

# Interval-valued and inequality-valued measurements, plus a redacted one and a
# two-era value. A scalar numeric parser gets every one of these wrong.
NUMERIC_INTERVALS = """\
Pertinent Results:
Echocardiogram: EF 35-40%, moderate mitral regurgitation.
Prior study showed LVEF>55%.
Repeat echo: EF ___ (report pending).
EF 30% which improved to 50% after initiation of guideline therapy.
BMI 31.2 kg/m2.
"""

# Metoprolol is evidence for both hypertension and HFrEF; hydroxychloroquine for
# both SLE and rheumatoid arthritis. An operator touching either term must
# report a collateral effect on the phenotype it did not name.
OVERLAPPING_PHENOTYPE_TERMS = """\
Discharge Medications:
1. Metoprolol succinate 50 mg PO daily
2. Lisinopril 10 mg PO daily
3. Hydroxychloroquine 200 mg PO BID
4. Furosemide 20 mg PO daily

Discharge Diagnosis:
Primary: Acute on chronic systolic heart failure
Secondary: Essential hypertension, systemic lupus erythematosus
"""

# Whitespace-aligned key/value blocks, present in 100% of development-corpus
# notes. Collapsing the runs is preserving; shifting a column by one field
# re-associates values with the wrong labels and is not.
ALIGNED_LAB_BLOCK = """\
Discharge Labs:
WBC-6.9    RBC-4.46   Hgb-12.8   Hct-38.2   Plt-244
Na-138     K-4.1      Cl-102     HCO3-26    BUN-14
"""

#: Every fixture, keyed by the trap it encodes.
FIXTURES: dict[str, str] = {
    "deid_in_lab_line": DEID_IN_LAB_LINE,
    "deid_as_list_number": DEID_AS_LIST_NUMBER,
    "divider_rule": DIVIDER_RULE,
    "hard_wrapped": HARD_WRAPPED,
    "blank_line_midsentence": BLANK_LINE_MIDSENTENCE,
    "shared_negation_cue": SHARED_NEGATION_CUE,
    "double_negation": DOUBLE_NEGATION,
    "family_history": FAMILY_HISTORY,
    "ambiguous_ra": AMBIGUOUS_RA,
    "ambiguous_pe": AMBIGUOUS_PE,
    "numeric_intervals": NUMERIC_INTERVALS,
    "overlapping_phenotype_terms": OVERLAPPING_PHENOTYPE_TERMS,
    "aligned_lab_block": ALIGNED_LAB_BLOCK,
}

__all__ = ["FIXTURES"]
