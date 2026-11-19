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


# --- Africa's Talking USSD and voice menus ---------------------------------
# Everything below is farmer-facing wording. Every Kinyarwanda string is
# marked RW-CHECK for review by a native speaker / agronomist before production.

USSD_WELCOME = "Muraho kuri Umuhinzi AI! Hitamo ururimi: 1 Ikinyarwanda 2 English"  # RW-CHECK
LANGUAGE_EN_NOTICE = "English selected. Kinyarwanda menus are used in this demo."
USSD_DISTRICT = "Hitamo akarere: 1 Gasabo 2 Kicukiro 3 Nyarugenge 4 Andika izina"  # RW-CHECK
USSD_DISTRICT_OTHER = "Andika izina rya akarere kawe:"  # RW-CHECK
USSD_SECTOR = "Hitamo sektori: 1 Kacyiru 2 Remera 3 Kimihurura 4 Andika izina"  # RW-CHECK
USSD_SECTOR_OTHER = "Andika izina rya sektori yawe:"  # RW-CHECK
USSD_MAIN_MENU = "Hitamo: 1 Sobanura ikibazo 2 Inama ku cyonnyi 3 Ibyihutirwa"  # RW-CHECK
USSD_SYMPTOMS = (  # RW-CHECK
    "Ikimenyetso: 1 Amababi y'ibigori arashye 2 Inyo mu giti "
    "3 Imyumbati y'umuhondo 4 Isazi y'ibishyimbo 5 Ibitoke biraba "
    "6 Ibirayi 7 Andika ubwawe"
)
USSD_SYMPTOM_OTHER = "Andika ikimenyetso cy'ibihingwa byawe:"  # RW-CHECK
USSD_PESTS = (  # RW-CHECK
    "Cyonnyi: 1 Inyo y'ibigori 2 Inyo y'umushyitsi 3 Mosaic "
    "4 Isazi y'ibishyimbo 5 Igitoke 6 Ibirayi"
)
USSD_ALERT_NONE = "Nta byihutirwa muri sektori yawe ubu."  # RW-CHECK
USSD_ALERT = "Ibyihutirwa muri {sector}: {message}"  # RW-CHECK
USSD_INVALID = "Ntibyemewe. Subiramo ushyiremo umubare ukwiye."  # RW-CHECK

SHORT_DIAGNOSIS_REPLY = "{name}: {step} Kugira ngo bitazongere: {prevention}"  # RW-CHECK
SHORT_LOW_CONFIDENCE_REPLY = (  # RW-CHECK
    "Ntabwo numvise neza. Subiramo uvuge ikihingwa n'ikimenyetso cyacyo."
)
OUTBREAK_NOTICE = " Hari ubutumwa bwihutirwa muri sektori yawe."  # RW-CHECK

VOICE_WELCOME = (  # RW-CHECK
    "Muraho kuri Umuhinzi AI. Tugufashije kumenya ikibazo cy'ibihingwa byawe."
)
VOICE_DISTRICT = "Hitamo akarere: kanda 1 Gasabo, 2 Kicukiro, 3 Nyarugenge."  # RW-CHECK
VOICE_SECTOR = "Hitamo sektori: kanda 1 Kacyiru, 2 Remera, 3 Kimihurura."  # RW-CHECK
VOICE_MENU = (  # RW-CHECK
    "Kanda 1 usobanure ikibazo, 2 wumve inama ku cyonnyi, "
    "3 wumve ibyihutirwa bya sektori."
)
VOICE_RECORD = "Vuga muri make ikibazo cy'ibihingwa byawe, hanyuma uhagarike."  # RW-CHECK
VOICE_PESTS = (  # RW-CHECK
    "Hitamo cyonnyi: kanda 1 Inyo y'ibigori, 2 Inyo y'umushyitsi, "
    "3 Mosaic, 4 Isazi y'ibishyimbo, 5 Igitoke, 6 Ibirayi."
)
VOICE_REPEAT = "Ntabwo numvise amajwi neza. Subiramo cyangwa uvuge buhoro."  # RW-CHECK
VOICE_GOODBYE = (  # RW-CHECK
    "Murakoze. Ibi ni inama rusange; baza umujyanama w'ubuhinzi."
)
