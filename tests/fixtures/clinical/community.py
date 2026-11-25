"""Community, allied health, virtual and long-term care notes.

Written by nurses, therapists and physicians outside hospital, often into
systems with very different conventions from an acute-care EHR. These are the
note types most likely to be absent from a research corpus and most likely to
be encountered when a tool is deployed, so leaving them out of the fixture set
would hide exactly the failures that matter in practice.
"""

from __future__ import annotations

from tests.fixtures.clinical import SyntheticNote

HOME_CARE_NURSING = SyntheticNote(
    id="home_care_nursing",
    setting="community",
    specialty="nursing",
    note_type="home_visit",
    structure="telegraphic",
    source_style="home_care_system",
    deid_scheme="none",
    hard_wrapped=False,
    language="en-CA",
    stresses="fragmentary entries, wound measurements, no headers, social context",
    text="""\
Home visit 1030-1115. Client alert, oriented, sitting up in chair on arrival.

Wound care to R heel pressure ulcer. Stage 2, measures 2.1 x 1.8 x 0.3 cm, wound bed 90% granulation 10% slough, small amount serous exudate, periwound intact. Cleansed with NS, hydrocolloid dressing applied. No s/s infection.

Vitals: BP 128/74 sitting, HR 76, T 36.6, SpO2 96% RA.

Meds reviewed with client and daughter. Blister pack in use, appears compliant. Notes she sometimes forgets the evening dose.

Home environment: scatter rug in hallway removed at last visit, remains removed. Grab bars in bathroom in place. Daughter present, providing meals. Client reports feeling isolated since husband passed.

Next visit Thursday for dressing change. Will refer to OT re: bathing aids and to social work re: community programs.
""",
)

TELEHEALTH_VISIT = SyntheticNote(
    id="telehealth_visit",
    setting="virtual",
    specialty="family_medicine",
    note_type="virtual_visit",
    structure="free_text",
    source_style="telehealth_platform",
    deid_scheme="angle_tag",
    hard_wrapped=False,
    language="en-US",
    stresses="modality attestation, limitations of remote exam, consent language, no exam section",
    text="""\
Virtual visit conducted by video. Patient identity confirmed with two identifiers. Patient located at home in <STATE>, provider located at <SITE>. Verbal consent for telehealth obtained and documented. Patient advised of limitations of remote assessment.

Presenting concern: sore throat x 3 days, subjective fever, no cough, no SOB, no difficulty swallowing liquids. No known sick contacts. Immunizations up to date.

On video the patient appears well, speaking in full sentences, no respiratory distress, no drooling, no stridor. Unable to visualize the oropharynx adequately over video. No physical exam performed given the modality.

Centor criteria estimated at 2 based on history. Discussed that in-person assessment with throat swab would be needed to confirm or exclude strep. Patient prefers to trial supportive care first.

Plan: supportive care, fluids, acetaminophen. Return precautions reviewed in detail including difficulty breathing, inability to swallow, drooling, or neck swelling - patient to present to urgent care or ED. Will arrange in-person visit if not improving in 48-72h. Patient verbalized understanding.
""",
)

PHYSIOTHERAPY = SyntheticNote(
    id="physiotherapy",
    setting="community",
    specialty="physiotherapy",
    note_type="therapy_note",
    structure="semi_structured",
    source_style="allied_health_system",
    deid_scheme="square_tag",
    hard_wrapped=False,
    language="en-CA",
    stresses="ROM measurements in degrees, MMT grades as fractions, exercise prescription",
    text="""\
PHYSIOTHERAPY PROGRESS NOTE

Subjective: [PATIENT] reports R shoulder pain improved from 7/10 to 4/10 since last session. Able to sleep on the affected side for the first time. Still difficulty reaching overhead cupboards.

Objective:
R shoulder AROM: flexion 145 deg (was 120), abduction 130 deg (was 105), ER 55 deg, IR to L3.
Strength: supraspinatus 4/5, infraspinatus 4+/5, subscapularis 5/5.
Special tests: Hawkins-Kennedy positive, empty can negative, Neer equivocal.
Palpation: mild tenderness over greater tuberosity, no crepitus.

Analysis: Continued improvement in AROM and pain consistent with resolving subacromial impingement. Strength deficits persist in the posterior cuff.

Plan: Progress theraband external rotation from red to green, 3 x 15 BID. Add scapular retraction in prone. Continue postural education. Reassess in 2 weeks. Anticipate discharge in 4-6 weeks if trajectory maintained.
""",
)

DIALYSIS_RUN_SHEET = SyntheticNote(
    id="dialysis_run_sheet",
    setting="community",
    specialty="nephrology",
    note_type="treatment_record",
    structure="tabular",
    source_style="dialysis_unit_system",
    deid_scheme="xxx_run",
    hard_wrapped=False,
    language="en-US",
    stresses="tab-delimited hourly observations, machine parameters, pre/post weights",
    text="""\
HEMODIALYSIS TREATMENT RECORD

Patient: XXXXX\tAccess: L AVF\tPrescription: 4h, QB 400, QD 500

Pre-weight: 74.8 kg\tTarget: 72.0 kg\tUF goal: 2.8 L

Time\tBP\tHR\tUF removed\tComments
0800\t148/86\t78\t0.0 L\tInitiated without difficulty
0900\t142/84\t76\t0.7 L\tTolerating well
1000\t136/80\t80\t1.4 L\t
1100\t118/68\t92\t2.1 L\tCramping L calf, 100 mL NS bolus given
1200\t126/74\t82\t2.8 L\tUF goal achieved, discontinued

Post-weight: 72.1 kg\tTotal UF: 2.8 L\tKt/V: 1.42

Access assessment pre and post: thrill palpable, bruit audible, no signs of infiltration or infection. Needle sites held 10 minutes, hemostasis achieved.
""",
)

LONG_TERM_CARE = SyntheticNote(
    id="long_term_care",
    setting="community",
    specialty="geriatrics",
    note_type="quarterly_review",
    structure="free_text",
    source_style="ltc_system",
    deid_scheme="none",
    hard_wrapped=True,
    language="en-CA",
    stresses="goals-of-care language, functional scales, family discussion, prose with no headers",
    text="""\
Quarterly review completed. Resident is a woman in her late eighties with
advanced dementia, admitted to this facility two years ago. She is now
non-ambulatory, requires total assistance for all activities of daily
living, and communicates through facial expression rather than words.

Weight has declined 3 kg over the quarter despite fortified diet and
between-meal supplements. Speech-language pathology assessed swallowing and
recommended minced moist texture, which is in place. Staff report she
sometimes turns away after a few spoonfuls.

No falls this quarter. Skin remains intact. Bowel routine effective. She
appears comfortable at rest and settles readily with music.

Met with her son and daughter this afternoon to review goals of care. We
discussed the natural trajectory of advanced dementia including progressive
weight loss and recurrent aspiration. The family confirmed they do not wish
transfer to hospital or artificial feeding, and that comfort is the
priority. Existing DNR order reaffirmed. Documentation updated accordingly.

Continue current supportive measures. Will reassess in three months or
sooner if there is a change in condition.
""",
)

NOTES: tuple[SyntheticNote, ...] = (
    HOME_CARE_NURSING,
    TELEHEALTH_VISIT,
    PHYSIOTHERAPY,
    DIALYSIS_RUN_SHEET,
    LONG_TERM_CARE,
)
