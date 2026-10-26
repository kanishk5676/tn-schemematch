"""Consent, the notice behind it, and a person's copy of their own data.

India's Digital Personal Data Protection Act, 2023 asks for consent given on a clear notice
— in English or a language of the Eighth Schedule, so Tamil and Malayalam qualify — and
lets a person see, correct and erase what is held about them and withdraw consent. This
module holds the notice, and :func:`export` builds the copy a person may ask for.

The notice is versioned by date. A consent records which version was shown, so a change
to the notice is a reason to ask again rather than a silent change of terms.
"""

from __future__ import annotations

import time
from typing import Any

NOTICE_VERSION = "2026-10-26"
GIVEN_BY = ("self", "helper")

NOTICE: dict[str, dict[str, Any]] = {
    "en": {
        "title": "Before we save your details",
        "points": [
            "What we keep: the facts you tell us or that are read from your documents, the "
            "photos you upload, and the applications you track.",
            "Why: only to find the government schemes you can get, and to help you apply.",
            "Where: on the computer that runs this app. If the assistant or photo reading is "
            "switched on, what you type and your photos are sent to an AI service to be read; "
            "it never decides who is eligible.",
            "Who can see it: you, and a helper who signs in to this app.",
            "Aadhaar and other ID numbers are cut to their last four digits before anything "
            "is kept.",
            "Your rights: you can see everything kept about you, correct it, download it, and "
            "delete it at any time. Withdrawing consent deletes it.",
        ],
        "agree": "I agree",
    },
    "ta": {
        "title": "உங்கள் விவரங்களைச் சேமிக்கும் முன்",
        "points": [
            "நாங்கள் வைத்திருப்பவை: நீங்கள் சொல்லும் அல்லது உங்கள் ஆவணங்களில் இருந்து "
            "படிக்கப்படும் விவரங்கள், நீங்கள் பதிவேற்றும் புகைப்படங்கள், நீங்கள் கண்காணிக்கும் "
            "விண்ணப்பங்கள்.",
            "ஏன்: நீங்கள் பெறக்கூடிய அரசுத் திட்டங்களைக் கண்டறிந்து, விண்ணப்பிக்க உதவுவதற்கு "
            "மட்டும்.",
            "எங்கே: இந்தச் செயலியை இயக்கும் கணினியில். உதவியாளர் அல்லது புகைப்படம் படிக்கும் "
            "வசதி இயங்கினால், நீங்கள் எழுதுவதும் புகைப்படங்களும் படிப்பதற்காக ஒரு AI "
            "சேவைக்கு அனுப்பப்படும்; தகுதியை அது ஒருபோதும் முடிவு செய்வதில்லை.",
            "யார் பார்க்கலாம்: நீங்களும், இந்தச் செயலியில் உள்நுழையும் உதவியாளரும்.",
            "ஆதார் போன்ற அடையாள எண்களின் கடைசி நான்கு இலக்கங்கள் மட்டுமே வைக்கப்படும்.",
            "உங்கள் உரிமைகள்: உங்களைப் பற்றி வைத்திருக்கும் அனைத்தையும் பார்க்கலாம், "
            "திருத்தலாம், பதிவிறக்கலாம், எப்போது வேண்டுமானாலும் நீக்கலாம். ஒப்புதலைத் "
            "திரும்பப் பெற்றால் அனைத்தும் நீக்கப்படும்.",
        ],
        "agree": "ஒப்புக்கொள்கிறேன்",
    },
    "ml": {
        "title": "നിങ്ങളുടെ വിവരങ്ങൾ സൂക്ഷിക്കുന്നതിന് മുമ്പ്",
        "points": [
            "ഞങ്ങൾ സൂക്ഷിക്കുന്നത്: നിങ്ങൾ പറയുന്നതോ നിങ്ങളുടെ രേഖകളിൽ നിന്ന് വായിക്കുന്നതോ "
            "ആയ വിവരങ്ങൾ, നിങ്ങൾ അപ്‌ലോഡ് ചെയ്യുന്ന ഫോട്ടോകൾ, നിങ്ങൾ ട്രാക്ക് ചെയ്യുന്ന "
            "അപേക്ഷകൾ.",
            "എന്തിന്: നിങ്ങൾക്ക് ലഭിക്കാവുന്ന സർക്കാർ പദ്ധതികൾ കണ്ടെത്താനും അപേക്ഷിക്കാൻ "
            "സഹായിക്കാനും മാത്രം.",
            "എവിടെ: ഈ ആപ്പ് പ്രവർത്തിക്കുന്ന കമ്പ്യൂട്ടറിൽ. അസിസ്റ്റന്റോ ഫോട്ടോ വായനയോ "
            "ഓണാണെങ്കിൽ, നിങ്ങൾ എഴുതുന്നതും ഫോട്ടോകളും വായിക്കാനായി ഒരു AI സേവനത്തിലേക്ക് "
            "അയയ്ക്കും; യോഗ്യത തീരുമാനിക്കുന്നത് ഒരിക്കലും അതല്ല.",
            "ആർക്ക് കാണാം: നിങ്ങൾക്കും, ഈ ആപ്പിൽ ലോഗിൻ ചെയ്യുന്ന സഹായിക്കും.",
            "ആധാർ പോലുള്ള തിരിച്ചറിയൽ നമ്പറുകളുടെ അവസാന നാല് അക്കങ്ങൾ മാത്രമേ സൂക്ഷിക്കൂ.",
            "നിങ്ങളുടെ അവകാശങ്ങൾ: നിങ്ങളെക്കുറിച്ച് സൂക്ഷിച്ചിരിക്കുന്നതെല്ലാം കാണാനും "
            "തിരുത്താനും ഡൗൺലോഡ് ചെയ്യാനും എപ്പോൾ വേണമെങ്കിലും ഇല്ലാതാക്കാനും കഴിയും. "
            "സമ്മതം പിൻവലിച്ചാൽ എല്ലാം ഇല്ലാതാകും.",
        ],
        "agree": "ഞാൻ സമ്മതിക്കുന്നു",
    },
}


def notice(lang: str = "en") -> dict[str, Any]:
    return {"version": NOTICE_VERSION, "lang": lang if lang in NOTICE else "en",
            **NOTICE.get(lang, NOTICE["en"])}


def export(vault: Any, pid: str) -> dict[str, Any]:
    """Everything held about one person, as one JSON document.

    Uploaded photos are listed but not embedded — they can be downloaded one by one —
    and the on-disk path of each is left out, as everywhere else.
    """
    return {
        "exported_at": time.time(),
        "profile": vault.get_profile(pid),
        "facts_now": vault.fact_rows(pid),
        "fact_history": vault.history(pid),
        "documents": [{k: v for k, v in d.items() if k != "stored_path"}
                      for d in vault.documents(pid)],
        "applications": vault.applications(pid),
        "consents": vault.consents(pid),
        "access_log": vault.audit_log(pid),
    }
