"""Kinyarwanda text used by the farmer-facing system.

RULE: keep ALL farmer-facing wording here (greetings, menus, replies) so a
native speaker can review one file. Pest-specific treatment text lives in
`app/data/pests.json`, which is also marked for native review.

RW-CHECK = wording that still needs a native Kinyarwanda speaker / agronomist
to confirm before production.
"""

# RW-CHECK: "Twahisemo" = "we have chosen/identified". Confirm natural wording.
DIAGNOSIS_REPLY = (
    "Twahisemo: {name}. "
    "Icyo wakora: {steps} "
    "Kugira ngo bitazongere: {prevention}"
)

# RW-CHECK: low-confidence wording. Should sound polite and easy to understand
# when heard on a phone call.
LOW_CONFIDENCE_REPLY = (
    "Ntabwo numvise neza. Nyamuneka subiramo utubaze: "
    "ni ikihe kibimera kibabaje, kandi amababi cyangwa ibimera bigaragaza iki? "
    "Urugero: amababi y'ibigori arashye kandi afite uduhumbi."
)

# RW-CHECK: gentle reminder that this is general advice, not a field visit.
DIAGNOSIS_DISCLAIMER = "Ibi ni inama rusange. Baza n'umujyanama w'ubuhinzi."

# Kept for safety if a pest id is missing from the knowledge base.
PEST_NOT_FOUND_REPLY = "Ntabwo nabonye iyi ndwara mu bubumenyi bwanjye."

# RW-CHECK: spoken when speech recognition returns nothing (noisy call, expired
# token, timeout, or silence). Keep it short for a live call.
ASR_REPEAT_REPLY = (
    "Ntabwo numvise amajwi neza. Nyamuneka subiramo cyangwa uvuge buhoro: "
    "ni ikihe kibimera kibabaje, kandi amababi bigaragaza iki?"
)

# RW-CHECK: outbreak early-warning alert sent to farmers/cooperatives. Confirm
# natural Kinyarwanda and adjust length for SMS before production.
OUTBREAK_ALERT = (
    "Iki ni ubutumwa bwihutirwa: mu gace ka {sector}, abahinzi {count} "
    "bavuze ikibazo cya {pest} mu minsi {days} ishize. Nyamuneka sura "
    "imyaka yawe vuba, ukure ibihingwa birwaye, kandi ubaze umujyanama "
    "w'ubuhinzi."
)
