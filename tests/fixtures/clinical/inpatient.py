"""Inpatient ward notes, across vendors, countries and eras.

The most templated setting, and the one most research corpora are drawn from —
which is precisely why it must not be the only thing the segmenter is tested
against. Even here the conventions diverge sharply: a MIMIC-IV discharge
summary, an i2b2-lineage note with typed masks, an NHS discharge letter written
as prose correspondence, a French consultation and an all-caps mainframe export
share almost no surface features.
"""

from __future__ import annotations

from tests.fixtures.clinical import SyntheticNote

MIMIC_DISCHARGE = SyntheticNote(
    id="mimic_discharge",
    setting="inpatient",
    specialty="internal_medicine",
    note_type="discharge_summary",
    structure="templated",
    source_style="mimic_iv",
    deid_scheme="underscore_run",
    hard_wrapped=True,
    language="en-US",
    stresses="underscore masks, hard wrap at ~63, aligned labs, ALLCAPS subheaders",
    text="""\
Name:  ___                    Unit No:   ___

Admission Date:  ___              Discharge Date:   ___

Date of Birth:  ___             Sex:   F

Service: MEDICINE

Allergies:
Penicillins / Sulfa

Chief Complaint:
Shortness of breath

History of Present Illness:
___ year old woman with a history of hypertension and type 2
diabetes presenting with three days of progressive dyspnea on
exertion and bilateral lower extremity swelling.

Past Medical History:
1. Hypertension
2. Type 2 diabetes mellitus
3. Chronic kidney disease stage 3

Physical Exam:
VITALS: T 98.4 BP 148/86 HR 92 RR 20 SpO2 94% on RA
GEN: Elderly woman in mild respiratory distress.
CARDIAC: Regular rate, ___ systolic murmur.

Pertinent Results:
___ 09:57PM BLOOD WBC-6.9 RBC-4.46 Hgb-12.8 Hct-38.2 Plt ___
Na-138     K-4.1      Cl-102     HCO3-26    BUN-14

Brief Hospital Course:
Diuresed with IV furosemide with good response. Echocardiogram
showed EF 35-40% consistent with reduced ejection fraction.

Discharge Medications:
1. Furosemide 40 mg PO daily
Disp:*30 Tablet(s)* Refills:*2*

Discharge Diagnosis:
Primary: Acute on chronic systolic heart failure
Secondary: Essential hypertension

Discharge Condition:
Mental Status: Clear and coherent.
Level of Consciousness: Alert and interactive.
""",
)

I2B2_DISCHARGE = SyntheticNote(
    id="i2b2_discharge",
    setting="inpatient",
    specialty="cardiothoracic_surgery",
    note_type="discharge_summary",
    structure="templated",
    source_style="i2b2",
    deid_scheme="bracket_star",
    hard_wrapped=True,
    language="en-US",
    stresses="typed bracket masks, nested brackets, type labels inside the mask",
    text="""\
Admission Date: [**2178-4-17**]     Discharge Date: [**2178-4-23**]

Date of Birth: [**2110-8-2**]      Sex: M

Service: CARDIOTHORACIC

HISTORY OF PRESENT ILLNESS:
Mr. [**Known lastname 1234**] is a 67 year old man referred by Dr.
[**First Name (STitle) 567**] for evaluation of exertional angina.

PAST MEDICAL HISTORY:
1. Coronary artery disease
2. Hyperlipidemia

MEDICATIONS ON ADMISSION:
Aspirin 81 mg daily, atorvastatin 40 mg nightly.

DISCHARGE DIAGNOSIS:
Coronary artery disease status post coronary artery bypass grafting.

FOLLOWUP INSTRUCTIONS:
Follow up with Dr. [**Last Name (NamePattern1) 890**] in [**Hospital 12**]
clinic in two weeks.
""",
)

EPIC_PROGRESS = SyntheticNote(
    id="epic_progress",
    setting="inpatient",
    specialty="internal_medicine",
    note_type="progress_note",
    structure="problem_oriented",
    source_style="epic",
    deid_scheme="asterisk_run",
    hard_wrapped=False,
    language="en-US",
    stresses="unwrapped long lines, single-letter SOAP headers, asterisk placeholders, tabs",
    text="""\
PROGRESS NOTE

S:
Patient reports feeling improved this morning. Denies chest pain, shortness of breath, fever, or chills. Tolerating a regular diet without nausea. Ambulated in the hallway twice overnight with physical therapy and reports no dizziness.

O:
Vitals:\tT 37.1\tBP 132/78\tHR 74\tRR 16\tSpO2 96% RA
Physical exam: General - well appearing, no acute distress. Cardiovascular - regular rate and rhythm, no murmurs, rubs or gallops. Respiratory - clear to auscultation bilaterally without wheezes or crackles. Abdomen - soft, nontender, nondistended with normal bowel sounds.

Labs this morning: WBC 7.2, Hgb 11.9, Plt 210, Na 139, K 4.0, Cr 1.1, glucose 142.

A:
*** year old patient admitted with community acquired pneumonia, clinically improving on day 3 of ceftriaxone and azithromycin.

P:
#Pneumonia: Continue current antibiotics, transition to oral therapy today. Repeat chest imaging not indicated at this time.
#Type 2 diabetes: Continue home metformin, sliding scale insulin coverage.
#Dispo: Anticipate discharge tomorrow pending clinical stability.

Signed by: *** MD
""",
)

NHS_LETTER = SyntheticNote(
    id="nhs_letter",
    setting="inpatient",
    specialty="respiratory_medicine",
    note_type="discharge_letter",
    structure="letter",
    source_style="nhs_cris",
    deid_scheme="angle_tag",
    hard_wrapped=True,
    language="en-GB",
    stresses="letter prose format, British spelling, angle-tag masks, few colon headers",
    text="""\
Dear Dr <GP_NAME>,

Re: <PATIENT_NAME>, DOB <DATE>, NHS number <NHS_NUMBER>

Thank you for referring this patient, who was admitted on <DATE> and
discharged on <DATE>.

Diagnosis: Acute exacerbation of chronic obstructive pulmonary disease

She presented with a four day history of worsening breathlessness and
increased sputum production. On examination she was tachypnoeic with
widespread wheeze. There was no peripheral oedema. Haemoglobin was
118 g/L and there was no evidence of anaemia.

She was treated with nebulised salbutamol, oral prednisolone and a
five day course of amoxicillin, with good clinical response.

Medications on discharge: Salbutamol inhaler as required, tiotropium
18 micrograms once daily, prednisolone 30 mg once daily for a further
three days.

Follow up: Respiratory clinic in six weeks. Please review her inhaler
technique at your earliest convenience.

Yours sincerely,
<CLINICIAN_NAME>
Consultant Respiratory Physician
""",
)

FRENCH_CONSULTATION = SyntheticNote(
    id="french_consultation",
    setting="inpatient",
    specialty="internal_medicine",
    note_type="consultation",
    structure="semi_structured",
    source_style="quebec_emr",
    deid_scheme="square_tag",
    hard_wrapped=True,
    language="fr-CA",
    stresses="accented characters throughout, French section labels, comma decimal separator",
    text="""\
Note de consultation

Nom : [NOM]                    Date de naissance : [DATE]
Numéro de dossier : [DOSSIER]  Sexe : F

Motif de consultation :
Dyspnée à l'effort progressive

Histoire de la maladie actuelle :
Patiente de [AGE] ans, connue pour une hypertension artérielle et un
diabète de type 2, se présente avec une dyspnée d'effort évoluant
depuis trois semaines, accompagnée d'un œdème des membres inférieurs.

Antécédents médicaux :
1. Hypertension artérielle
2. Diabète de type 2
3. Insuffisance rénale chronique

Examen physique :
Signes vitaux : TA 152/88, FC 88, SpO2 95% à l'air ambiant
Cardiaque : rythme régulier, souffle systolique
Membres inférieurs : œdème bilatéral prenant le godet

Impression et plan :
Insuffisance cardiaque probable. Échographie cardiaque demandée.
Ajout de furosémide 40 mg par voie orale une fois par jour.
""",
)

ALLCAPS_LEGACY = SyntheticNote(
    id="allcaps_legacy",
    setting="inpatient",
    specialty="gastroenterology",
    note_type="discharge_summary",
    structure="templated",
    source_style="legacy_mainframe",
    deid_scheme="xxx_run",
    hard_wrapped=True,
    language="en-US",
    stresses="entire note uppercase, XXX masks, no case signal to separate abbreviations",
    text="""\
PATIENT NAME: XXXXX                    MRN: XXXXXXX

ADMISSION DATE: XX/XX/XXXX             DISCHARGE DATE: XX/XX/XXXX

CHIEF COMPLAINT:
ABDOMINAL PAIN

HISTORY OF PRESENT ILLNESS:
XX YEAR OLD MALE WITH HISTORY OF ETOH ABUSE PRESENTING WITH EPIGASTRIC
PAIN RADIATING TO THE BACK. DENIES FEVER OR VOMITING.

PAST MEDICAL HISTORY:
ALCOHOL ABUSE, HYPERTENSION, GERD

PHYSICAL EXAMINATION:
VITALS: T 99.1 BP 138/84 HR 96 RR 18 O2 SAT 98% ON RA
ABDOMEN: TENDER IN THE EPIGASTRIUM WITHOUT REBOUND OR GUARDING

LABORATORY DATA:
LIPASE 840, AST 112, ALT 74, TOTAL BILIRUBIN 1.2

HOSPITAL COURSE:
TREATED FOR ACUTE ALCOHOLIC PANCREATITIS WITH BOWEL REST AND IV FLUIDS.

DISCHARGE DIAGNOSIS:
ACUTE PANCREATITIS SECONDARY TO ALCOHOL USE
""",
)

TABULAR_EXPORT = SyntheticNote(
    id="tabular_export",
    setting="inpatient",
    specialty="internal_medicine",
    note_type="discharge_summary",
    structure="tabular",
    source_style="structured_export",
    deid_scheme="curly_tag",
    hard_wrapped=False,
    language="en-US",
    stresses="pipe tables, tab-separated flowsheet rows, markdown headings, curly masks",
    text="""\
DISCHARGE SUMMARY | Patient: {{PATIENT}} | MRN: {{MRN}}

## Medications on Discharge

| Medication  | Dose   | Route | Frequency |
|-------------|--------|-------|-----------|
| Metoprolol  | 25 mg  | PO    | BID       |
| Lisinopril  | 10 mg  | PO    | daily     |
| Metformin   | 500 mg | PO    | BID       |

## Vitals Trend

Date\tTemp\tBP\tHR\tSpO2
{{DATE}}\t37.0\t142/88\t78\t97%
{{DATE}}\t36.8\t134/80\t72\t98%

## Assessment

Hypertension, reasonably controlled on discharge regimen. Type 2 diabetes mellitus with hemoglobin A1c of 7.4%.
""",
)

WARD_NURSING = SyntheticNote(
    id="ward_nursing",
    setting="inpatient",
    specialty="nursing",
    note_type="nursing_note",
    structure="telegraphic",
    source_style="epic",
    deid_scheme="none",
    hard_wrapped=False,
    language="en-US",
    stresses="timestamped entries, no terminators, no de-identification at all",
    text="""\
0700 Pt awake alert oriented x3
0715 VSS afebrile, IV site clean dry intact
0800 Ambulated to bathroom with 1 assist, steady gait
0900 Tolerating clear liquids, no nausea
1030 Family at bedside, questions answered
1200 Lunch tray 75% consumed
1400 Pain 3/10, declined medication
1600 Report given to oncoming RN
""",
)

PEDIATRIC_ADMISSION = SyntheticNote(
    id="pediatric_admission",
    setting="inpatient",
    specialty="pediatrics",
    note_type="admission_note",
    structure="semi_structured",
    source_style="childrens_hospital_emr",
    deid_scheme="square_tag",
    hard_wrapped=True,
    language="en-US",
    stresses="weight-based dosing, growth percentiles, age in months, caregiver as informant",
    text="""\
PEDIATRIC ADMISSION NOTE

Patient: [PATIENT]   Age: 14 months   Weight: 9.8 kg (25th percentile)
Length: 76 cm (30th percentile)   Head circumference: 46.5 cm (40th)
Informant: mother, appears reliable.

HPI:
Previously well 14 month old male, fully immunized, brought in by mother
with 3 days of fever to 39.2 C, decreased oral intake and increased work of
breathing. Fewer wet diapers than usual, last one about 6 hours ago. No
vomiting. Attends daycare where several children have been unwell.

Exam:
T 38.8 HR 158 RR 48 SpO2 92% RA BP 92/54
General: fussy but consolable in mother's arms.
Resp: subcostal and intercostal retractions, diffuse wheeze and crackles
bilaterally, prolonged expiratory phase.
CVS: tachycardic, regular, cap refill 2 seconds.
Hydration: tacky mucous membranes, tears present.

Assessment: Bronchiolitis with mild to moderate respiratory distress and
mild dehydration.

Plan:
- Admit to pediatric ward
- Nasal suctioning PRN, humidified oxygen to keep SpO2 above 90%
- Trial of NG feeds if oral intake remains poor
- Acetaminophen 15 mg/kg PO q6h PRN (150 mg per dose)
- No routine chest radiograph or antibiotics indicated
- Reassess in 4 hours or sooner if deterioration
""",
)

PALLIATIVE_CONSULT = SyntheticNote(
    id="palliative_consult",
    setting="inpatient",
    specialty="palliative_care",
    note_type="consultation",
    structure="free_text",
    source_style="epic",
    deid_scheme="underscore_run",
    hard_wrapped=True,
    language="en-US",
    stresses="prose-heavy with no exam, goals-of-care language, reported speech, negated interventions",
    text="""\
Asked to see this ___ year old gentleman with metastatic pancreatic
adenocarcinoma, now with progressive disease after second line
chemotherapy, for symptom management and goals of care discussion.

I met with him and his wife at the bedside for approximately forty
minutes. He is alert and able to participate fully in the conversation. He
told me that he understands his cancer is not curable and said, "I've made
my peace with that, I just don't want to be in pain." His wife was tearful
but engaged.

His main symptoms are abdominal pain, rated 6 out of 10 at rest and worse
with movement, and profound fatigue. He denies nausea, denies dyspnea and
denies constipation on his current regimen. Appetite is poor but he is not
distressed by this.

We discussed what to expect in the coming weeks. He was clear that he does
not wish resuscitation, does not wish transfer to intensive care, and does
not wish artificial nutrition. He would like to be at home if that can be
arranged safely. His wife expressed concern about managing at home alone
overnight.

Recommendations: rotate to long acting oral opioid with short acting for
breakthrough, continue bowel regimen, and refer to community palliative
care for home support. Code status updated to DNR after discussion. I have
offered to meet again with the family later this week.
""",
)

# --------------------------------------------------------------------------
# A long, complex, multi-problem discharge summary. Every other fixture here is
# short enough to read at a glance, but real discharge summaries run to a median
# of ~11,500 characters and a maximum of ~33,000, and length is not cosmetic: it
# is what makes per-note wrap-width estimation stable, gives section and list
# denominators a realistic magnitude, and exposes any per-character cost in the
# segmentation layer.
# --------------------------------------------------------------------------
COMPLEX_DISCHARGE = SyntheticNote(
    id="complex_discharge",
    setting="inpatient",
    specialty="geriatrics",
    note_type="discharge_summary",
    structure="problem_oriented",
    source_style="academic_centre_emr",
    deid_scheme="underscore_run",
    hard_wrapped=True,
    language="en-US",
    stresses="realistic length, many sections, long problem-based course, polypharmacy list",
    text="""\
Name:  ___                         Unit No:   ___

Admission Date:  ___               Discharge Date:   ___

Date of Birth:  ___                Sex:   M

Service: MEDICINE

Attending: ___

Allergies:
Codeine (nausea) / Ciprofloxacin (rash)

Chief Complaint:
Confusion and fall at home

Major Surgical or Invasive Procedure:
None

History of Present Illness:
___ year old man with a history of atrial fibrillation on apixaban,
chronic kidney disease stage 3b, type 2 diabetes mellitus, heart failure
with preserved ejection fraction and mild cognitive impairment, brought in
by his daughter after an unwitnessed fall at home.

She reports that over the preceding four days he had become increasingly
confused, sleeping more during the day and up at night. He had been
complaining of burning on urination for about a week but had not mentioned
this to anyone until she asked directly. On the morning of admission she
found him on the bathroom floor, awake and able to speak but unable to
explain what had happened. There was no head strike that she could
identify and no loss of consciousness that she witnessed.

He normally mobilises with a four wheeled walker and is independent for
most activities of daily living, with his daughter managing his
medications in a blister pack and preparing his meals. He does not drive.
He has had two other falls in the past year, neither resulting in injury.

In the emergency department he was febrile to 38.4, tachycardic and
hypotensive to 96/54, which improved after a fluid bolus. Urinalysis
showed pyuria and nitrites. CT head was negative for acute intracranial
process.

Past Medical History:
1. Atrial fibrillation, on apixaban, CHA2DS2-VASc 5
2. Chronic kidney disease stage 3b, baseline creatinine 1.6
3. Type 2 diabetes mellitus, on metformin and linagliptin
4. Heart failure with preserved ejection fraction, last EF 60%
5. Mild cognitive impairment, MoCA 22 two years ago
6. Benign prostatic hyperplasia
7. Osteoarthritis, bilateral knees
8. Hypertension

Social History:
Widowed, lives alone in a single storey home. Daughter lives nearby and
visits daily. Former accountant. Never smoker. Rare alcohol use, perhaps
one glass of wine at family gatherings. No illicit substance use.

Family History:
Father with myocardial infarction in his sixties. Mother with dementia in
her eighties. No known family history of malignancy.

Physical Exam:
ADMISSION EXAM:
VITALS: T 38.4 BP 96/54 HR 112 irregular RR 20 SpO2 94% on room air
GEN: Frail elderly man, appears older than stated age, drowsy but rousable.
HEENT: Dry mucous membranes. No scalp haematoma or laceration.
NECK: Supple. JVP not elevated.
CARDIAC: Irregularly irregular, tachycardic, no murmur appreciated.
LUNGS: Clear to auscultation bilaterally, no crackles or wheeze.
ABD: Soft, mild suprapubic tenderness, no guarding or rebound.
EXT: No peripheral oedema. Bruising over the right hip, no deformity.
NEURO: Oriented to person only. Follows simple commands. No focal deficit.
Moves all four limbs. No neck stiffness.

DISCHARGE EXAM:
VITALS: T 36.7 BP 124/70 HR 78 RR 16 SpO2 96% on room air
GEN: Alert, sitting up in chair, conversant and appropriate.
NEURO: Oriented to person, place and approximate date. No focal deficit.
EXT: Resolving bruise over the right hip. Ambulating with walker.

Pertinent Results:
ADMISSION LABS:
___ 08:14AM BLOOD WBC-16.2 RBC-3.98 Hgb-11.4 Hct-34.1 Plt ___
___ 08:14AM BLOOD Neuts-84.2 Lymphs-9.1 Monos-5.8 Eos-0.6
___ 08:14AM BLOOD Glucose-198 UreaN-42 Creat-2.4 Na-131 K-4.8 Cl-97
___ 08:14AM BLOOD ALT-22 AST-26 AlkPhos-84 TotBili-0.6 Albumin-3.1
___ 08:14AM BLOOD Lactate-2.6
___ 09:02AM URINE Color-Yellow Appear-Cloudy Sp ___
___ 09:02AM URINE Blood-SM Nitrite-POS Protein-30 Leuks-LG

MICROBIOLOGY:
Urine culture: greater than 100,000 CFU/mL Escherichia coli, sensitive to
ceftriaxone, nitrofurantoin and trimethoprim-sulfamethoxazole, resistant
to ciprofloxacin.
Blood cultures x2: no growth to date at time of discharge.

IMAGING:
CT head without contrast: No acute intracranial haemorrhage, mass effect
or midline shift. Chronic small vessel ischaemic change. No fracture.
Chest radiograph: No focal consolidation. Cardiomegaly.
Right hip radiograph: No acute fracture or dislocation.

DISCHARGE LABS:
___ 06:30AM BLOOD WBC-8.1 Hgb-10.9 Plt ___
___ 06:30AM BLOOD Glucose-142 UreaN-24 Creat-1.7 Na-137 K-4.1

Brief Hospital Course:
# Urinary tract infection with sepsis: He met sepsis criteria on arrival
with fever, tachycardia, hypotension and a raised lactate in the setting
of a urinary source. Blood and urine cultures were drawn and he was
started on empiric ceftriaxone after a two litre crystalloid resuscitation,
with prompt haemodynamic improvement. Urine culture grew Escherichia coli
resistant to ciprofloxacin but sensitive to ceftriaxone, and he completed
a total of seven days of therapy, transitioning to oral
trimethoprim-sulfamethoxazole for the final three days. He remained
afebrile from hospital day two onward.

# Delirium: His confusion was felt to be hypoactive delirium precipitated
by infection, dehydration and an unfamiliar environment, on a background
of mild cognitive impairment. Non-pharmacological measures were used
throughout, including maintaining a day and night routine, ensuring his
glasses and hearing aid were available, early mobilisation and family
presence. No antipsychotics were required. His orientation improved
steadily and by discharge he was back to his baseline per his daughter.

# Acute kidney injury on chronic kidney disease: Creatinine rose from a
baseline of 1.6 to 2.4 on admission, consistent with a prerenal insult.
Apixaban was held on admission and metformin, lisinopril and
hydrochlorothiazide were all held. With volume resuscitation his
creatinine improved to 1.7 by discharge. Metformin and lisinopril were
restarted prior to discharge; hydrochlorothiazide was discontinued given
the fall risk and the modest contribution to blood pressure control.

# Atrial fibrillation: He remained in atrial fibrillation throughout,
initially with a rapid ventricular response in the setting of sepsis,
which settled with treatment of the infection and did not require rate
control beyond his home metoprolol. Apixaban was held for four days during
the acute kidney injury and restarted at a renally adjusted dose of 2.5 mg
twice daily once creatinine had improved.

# Falls: Physiotherapy and occupational therapy assessed him. Orthostatic
vitals were negative once euvolaemic. A medication review identified
hydrochlorothiazide as a contributor and it was stopped. Home safety
recommendations were made including removal of loose rugs and installation
of a raised toilet seat and grab rails, and a referral to community
occupational therapy was sent.

# Type 2 diabetes mellitus: Metformin was held during the acute kidney
injury and he was covered with a correction insulin scale, with glucose
readings ranging from 138 to 212. Metformin was restarted at a reduced
dose of 500 mg twice daily at discharge given his renal function.
Linagliptin was continued.

# Goals of care: A discussion was held with the patient and his daughter.
He wishes to remain at home for as long as possible and does not want
prolonged intensive care or resuscitation if his heart were to stop. A
do-not-resuscitate order was entered with his agreement and that of his
daughter, and this was documented in the chart.

Medications on Admission:
1. Apixaban 5 mg PO BID
2. Metoprolol succinate 50 mg PO daily
3. Lisinopril 10 mg PO daily
4. Hydrochlorothiazide 25 mg PO daily
5. Metformin 1000 mg PO BID
6. Linagliptin 5 mg PO daily
7. Tamsulosin 0.4 mg PO nightly
8. Acetaminophen 650 mg PO TID PRN
9. Vitamin D 1000 units PO daily

Discharge Medications:
1. Apixaban 2.5 mg PO BID
Disp:*60 Tablet(s)* Refills:*2*
2. Metoprolol succinate 50 mg PO daily
Disp:*30 Tablet(s)* Refills:*2*
3. Lisinopril 10 mg PO daily
Disp:*30 Tablet(s)* Refills:*2*
4. Metformin 500 mg PO BID
Disp:*60 Tablet(s)* Refills:*2*
5. Linagliptin 5 mg PO daily
Disp:*30 Tablet(s)* Refills:*2*
6. Tamsulosin 0.4 mg PO nightly
Disp:*30 Capsule(s)* Refills:*2*
7. Trimethoprim-sulfamethoxazole DS 1 tablet PO BID for 3 days
Disp:*6 Tablet(s)* Refills:*0*
8. Acetaminophen 650 mg PO TID PRN pain
9. Vitamin D 1000 units PO daily

STOPPED: Hydrochlorothiazide, discontinued due to fall risk.
CHANGED: Apixaban reduced from 5 mg to 2.5 mg twice daily for renal
function. Metformin reduced from 1000 mg to 500 mg twice daily.

Discharge Disposition:
Home with services

Discharge Diagnosis:
Primary: Escherichia coli urinary tract infection with sepsis
Secondary: Hypoactive delirium; acute kidney injury on chronic kidney
disease stage 3b; atrial fibrillation; type 2 diabetes mellitus;
mechanical fall

Discharge Condition:
Mental Status: Returned to baseline per family.
Level of Consciousness: Alert and interactive.
Activity Status: Ambulatory with four wheeled walker.

Discharge Instructions:
You were admitted to the hospital because you had a urinary tract
infection that had spread to your bloodstream, which made you confused and
caused you to fall. You were treated with antibiotics and fluids and you
improved.

Please take the antibiotic tablets until they are finished, even if you
feel completely well before then.

Two of your medicines have changed. Your blood thinner apixaban is now a
lower dose because of your kidneys, and your water pill
hydrochlorothiazide has been stopped because it may have contributed to
your fall. Please do not restart it.

Please have blood work to check your kidney function within one week.

Return to the emergency department if you develop fever, shaking chills,
burning when you pass urine, new confusion, or if you fall again.

TRANSITIONAL ISSUES:
- Repeat creatinine and potassium within 7 days; consider further apixaban
  dose adjustment if renal function changes.
- Blood cultures were negative at 3 days at the time of discharge; final
  result to be followed up by the primary care physician.
- Community occupational therapy referral sent for home safety assessment.
- Consider formal cognitive reassessment in an outpatient setting once the
  delirium has fully resolved, no sooner than three months.

Followup Instructions:
Primary care physician within one week.
Geriatrics clinic in six weeks.
""",
)

NOTES: tuple[SyntheticNote, ...] = (
    MIMIC_DISCHARGE,
    COMPLEX_DISCHARGE,
    I2B2_DISCHARGE,
    EPIC_PROGRESS,
    NHS_LETTER,
    FRENCH_CONSULTATION,
    ALLCAPS_LEGACY,
    TABULAR_EXPORT,
    WARD_NURSING,
    PEDIATRIC_ADMISSION,
    PALLIATIVE_CONSULT,
)
