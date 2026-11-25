"""Emergency department and critical care notes.

Two settings that write very differently from the ward. ED notes are built
around a timeline and a disposition decision, with heavy shorthand and
triage-scale codes. ICU notes are organised by organ system rather than by
problem, and are dense with drip rates, ventilator settings and hourly values —
so they carry far more numeric content per character than any other note type,
which matters for every numeric operator's denominator.
"""

from __future__ import annotations

from tests.fixtures.clinical import SyntheticNote

# --------------------------------------------------------------------------
# ED: timestamped timeline, triage codes, disposition, extreme abbreviation.
# --------------------------------------------------------------------------
ED_NOTE = SyntheticNote(
    id="ed_note",
    setting="emergency",
    specialty="emergency_medicine",
    note_type="ed_note",
    structure="telegraphic",
    source_style="ed_tracking_system",
    deid_scheme="angle_tag",
    hard_wrapped=False,
    language="en-CA",
    stresses="timestamped timeline entries, triage codes, dense abbreviation, disposition",
    text="""\
ED NOTE - <SITE>

Triage 21:14 CTAS 2. CC: chest pain.

21:20 Seen by RN. VS: HR 104, BP 156/92, RR 20, SpO2 96% RA, T 36.8.
21:26 ECG done - NSR, no acute ST changes, poor R wave progression V1-V3.
21:31 Seen by MD. <AGE>M, sudden onset substernal CP x 2h, radiating to L arm, assoc diaphoresis. No SOB. Hx HTN, DLD, smoker 20 pack-yr. Nil cardiac hx. NKDA.
21:35 ASA 162 chewed. Nitro spray x1 with partial relief.
21:52 Trop <0.01. CBC, lytes, Cr sent.
22:40 Repeat trop <0.01. Pain now 2/10.
23:15 Repeat ECG unchanged. Labs unremarkable.
23:30 D/W cardiology on call - low risk, HEART score 3. Agrees with outpatient w/u.

Dispo: discharged home 23:55. Rx nitro spray PRN. F/u with FD in 1 wk, referral to cardiology sent. Return precautions given verbally and in writing - understood.
""",
)

# --------------------------------------------------------------------------
# ICU: organ-system structure, drips, vent settings, very high numeric density.
# --------------------------------------------------------------------------
ICU_DAILY = SyntheticNote(
    id="icu_daily",
    setting="critical_care",
    specialty="critical_care",
    note_type="daily_progress",
    structure="problem_oriented",
    source_style="icu_flowsheet_emr",
    deid_scheme="asterisk_run",
    hard_wrapped=False,
    language="en-US",
    stresses="systems-based structure, drip rates with units, vent settings, extreme numeric density",
    text="""\
ICU DAILY PROGRESS - Day 5

*** yo M admitted with septic shock secondary to perforated diverticulitis, s/p Hartmann's procedure POD 4.

NEURO: RASS -1 on propofol 20 mcg/kg/min. CAM-ICU negative. Fentanyl 50 mcg/hr for analgesia. Plan: lighten sedation for SBT.

RESP: Intubated, AC/VC. Vt 420 mL (6 mL/kg PBW), RR 18, PEEP 8, FiO2 0.40. P/F ratio 210. ABG 7.36/42/84/24. CXR: improving bibasilar atelectasis. Plan: SBT this AM, PEEP wean as tolerated.

CV: Norepinephrine weaned to 0.04 mcg/kg/min overnight (was 0.12). MAP 68-74. HR 88 SR. Lactate 1.4 (down from 2.8). Echo: EF 55%, no RV strain. Plan: continue wean, target MAP >65.

GI/NUTRITION: NG tube to LIS. TF held for procedure, restart today at 20 mL/hr. LFTs normal. Ostomy output 400 mL/24h.

RENAL: UOP 0.7 mL/kg/hr. Cr 1.4 (peak 2.1). K 4.2, Mg 1.9 - repleted. Net balance -800 mL/24h, cumulative +6.2 L.

ID: Day 5 pip-tazo. Blood cx NGTD. Intraop cx: E. coli, sensitive. WBC 13.2 (down from 22). Tmax 37.4. Plan: narrow to ceftriaxone + metronidazole.

HEME: Hgb 8.9, stable. Plt 145. On heparin 5000 units SC TID for VTE ppx.

DISPO: remains critically ill but improving. Family updated at bedside.
""",
)

# --------------------------------------------------------------------------
# A note bloated by copy-forward, with stale content propagated verbatim from
# earlier days. This is the documented pathology the discourse operators model,
# so the corpus needs a real example of it.
# --------------------------------------------------------------------------
COPY_FORWARD_BLOATED = SyntheticNote(
    id="copy_forward_bloated",
    setting="inpatient",
    specialty="internal_medicine",
    note_type="daily_progress",
    structure="problem_oriented",
    source_style="epic",
    deid_scheme="asterisk_run",
    hard_wrapped=False,
    language="en-US",
    stresses="stale copy-forward, internally contradictory dates, near-duplicate lines",
    text="""\
PROGRESS NOTE - Hospital Day 6

SUBJECTIVE: Patient reports feeling better today. No chest pain overnight.

OBJECTIVE:
Vitals: T 36.9, BP 128/76, HR 72, RR 16, SpO2 97% RA

ASSESSMENT/PLAN:

# Community acquired pneumonia
Admitted *** with fevers, productive cough and RLL infiltrate on CXR.
Started on ceftriaxone and azithromycin in the ED.
Day 1 of ceftriaxone and azithromycin. Will follow clinically.
Day 1 of ceftriaxone and azithromycin. Will follow clinically.
Now afebrile x 48h, transitioned to oral amoxicillin-clavulanate yesterday.

# Type 2 diabetes mellitus
Home metformin held on admission due to AKI.
Home metformin held on admission due to AKI.
Cr now returned to baseline, metformin restarted.

# Acute kidney injury
Cr 1.8 on admission, baseline 1.0. Likely prerenal in setting of poor PO intake.
Gentle IV fluids. Avoid nephrotoxins.
Resolved, Cr 1.0 today.

# Dispo
Anticipate discharge home tomorrow if remains stable.
""",
)

NOTES: tuple[SyntheticNote, ...] = (
    ED_NOTE,
    ICU_DAILY,
    COPY_FORWARD_BLOATED,
)
