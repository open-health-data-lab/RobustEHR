"""Procedural and diagnostic reports.

These are not clinical *notes* in the narrative sense — they are structured
reports with their own internal field grammar. A radiology report's
``TECHNIQUE:`` / ``COMPARISON:`` / ``FINDINGS:`` / ``IMPRESSION:`` labels look
exactly like section headers but structure a nested report rather than the
record, which is why the header layer classifies them separately. Operative and
pathology reports add their own conventions again.
"""

from __future__ import annotations

from tests.fixtures.clinical import SyntheticNote

RADIOLOGY_REPORT = SyntheticNote(
    id="radiology_report",
    setting="procedural",
    specialty="radiology",
    note_type="imaging_report",
    structure="templated",
    source_style="ris",
    deid_scheme="underscore_run",
    hard_wrapped=True,
    language="en-US",
    stresses="report fields rather than note sections, measurements, comparison language",
    text="""\
EXAMINATION:  CT ANGIOGRAM CHEST

INDICATION:  ___ year old with pleuritic chest pain, evaluate for
pulmonary embolism.

TECHNIQUE:  Axial images acquired through the chest following
administration of intravenous contrast.

COMPARISON:  Chest radiograph from ___.

FINDINGS:
No filling defect within the pulmonary arterial tree to suggest acute
pulmonary embolism. Small bilateral pleural effusions, right greater
than left, measuring up to 1.8 cm in depth. No focal consolidation.
The heart is mildly enlarged.

IMPRESSION:
1. No evidence of pulmonary embolism.
2. Small bilateral pleural effusions.
""",
)

OPERATIVE_NOTE = SyntheticNote(
    id="operative_note",
    setting="procedural",
    specialty="orthopedic_surgery",
    note_type="operative_note",
    structure="templated",
    source_style="or_system",
    deid_scheme="bracket_star",
    hard_wrapped=True,
    language="en-US",
    stresses="strict field template, laterality, implant catalogue numbers, counts",
    text="""\
OPERATIVE REPORT

SURGEON: [**Name**]
ASSISTANT: [**Name**]
ANESTHESIA: Spinal with sedation

PREOPERATIVE DIAGNOSIS: End-stage osteoarthritis, right knee
POSTOPERATIVE DIAGNOSIS: Same
PROCEDURE PERFORMED: Right total knee arthroplasty
ESTIMATED BLOOD LOSS: 150 mL
SPECIMENS: None
COMPLICATIONS: None
IMPLANTS: Femoral component size 5 right, tibial baseplate size 4,
polyethylene insert 10 mm, patellar button 32 mm

INDICATIONS: The patient is a [**Age**] year old with longstanding right
knee pain refractory to conservative management, with radiographs showing
tricompartmental degenerative change.

DESCRIPTION OF PROCEDURE: After adequate spinal anesthesia the right lower
extremity was prepped and draped in the usual sterile fashion. A midline
incision was made followed by a medial parapatellar arthrotomy. Distal
femoral and proximal tibial cuts were made using standard instrumentation.
Trial components were placed and the knee was taken through a full range of
motion with excellent stability. Final components were cemented in place.
The wound was irrigated and closed in layers. Sponge and needle counts were
correct at the conclusion of the case.

DISPOSITION: To PACU in stable condition.
""",
)

PATHOLOGY_REPORT = SyntheticNote(
    id="pathology_report",
    setting="procedural",
    specialty="pathology",
    note_type="pathology_report",
    structure="tabular",
    source_style="lis",
    deid_scheme="curly_tag",
    hard_wrapped=False,
    language="en-US",
    stresses="specimen enumeration, synoptic table, staging codes, tab-delimited fields",
    text="""\
SURGICAL PATHOLOGY REPORT

Accession: {{ACCESSION}}\tCollected: {{DATE}}\tReceived: {{DATE}}

SPECIMENS SUBMITTED
A. Colon, sigmoid, resection
B. Lymph nodes, pericolic

DIAGNOSIS

A. COLON, SIGMOID, SEGMENTAL RESECTION:
   - Invasive adenocarcinoma, moderately differentiated
   - Tumor size: 3.8 cm
   - Invades through muscularis propria into pericolic soft tissue
   - Margins negative, closest radial margin 1.2 cm
   - Lymphovascular invasion: present
   - Perineural invasion: not identified

B. LYMPH NODES, PERICOLIC:
   - Metastatic adenocarcinoma in 2 of 14 lymph nodes

SYNOPTIC SUMMARY
| Element        | Finding          |
|----------------|------------------|
| Histologic type| Adenocarcinoma   |
| Grade          | G2               |
| pT             | pT3              |
| pN             | pN1b             |
| Margins        | Negative         |

Pathologic stage: pT3 pN1b (AJCC 8th edition)
""",
)

ENDOSCOPY_REPORT = SyntheticNote(
    id="endoscopy_report",
    setting="procedural",
    specialty="gastroenterology",
    note_type="endoscopy_report",
    structure="semi_structured",
    source_style="endoscopy_suite",
    deid_scheme="none",
    hard_wrapped=False,
    language="en-GB",
    stresses="British spelling, anatomical landmarks with distances, scoring scales",
    text="""\
COLONOSCOPY REPORT

Indication: Iron deficiency anaemia, screening.
Sedation: Midazolam 3 mg, fentanyl 50 mcg IV.
Bowel preparation: Boston Bowel Prep Scale 8/9 (good).
Extent: Caecum reached, confirmed by appendiceal orifice and ileocaecal valve. Withdrawal time 9 minutes.

Findings: Two sessile polyps identified. A 6 mm polyp at 35 cm from the anal verge, removed by cold snare, retrieved. A 4 mm polyp in the ascending colon, removed by cold biopsy forceps, retrieved. Mild diverticulosis throughout the sigmoid colon. No mass, no ulceration, no active bleeding. Retroflexion in the rectum was normal, no haemorrhoids of significance.

Complications: nil.

Plan: Await histology. If tubular adenomas, repeat colonoscopy in 5 years per guideline. Patient given written discharge advice and warned regarding delayed bleeding.
""",
)

NOTES: tuple[SyntheticNote, ...] = (
    RADIOLOGY_REPORT,
    OPERATIVE_NOTE,
    PATHOLOGY_REPORT,
    ENDOSCOPY_REPORT,
)
