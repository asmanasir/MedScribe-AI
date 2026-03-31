from __future__ import annotations

"""
Norwegian medical language support.

Clinical Norwegian has specific terminology, abbreviations, and conventions
that general-purpose LLMs often get wrong. This module provides:

1. System prompts optimized for Norwegian clinical language
2. Common Norwegian medical abbreviations and expansions
3. ICD-10 mapping hints for Norwegian diagnoses
4. Post-processing corrections for common STT errors in Norwegian medical terms

This is what differentiates a production clinical system from a demo.
Existing clinical AI systems handle Norwegian — so must we, and better.
"""

# Norwegian clinical system prompt — used in structuring
NORWEGIAN_CLINICAL_SYSTEM_PROMPT = """Du er en medisinsk dokumentasjonsassistent for norsk helsevesen.

Regler:
1. Ekstraher informasjon KUN fra transkripsjonen. Aldri oppfinn eller anta.
2. Hvis en seksjon mangler relevant informasjon, skriv "Ikke dokumentert."
3. Bruk norsk medisinsk terminologi tilpasset kliniske journaler.
4. Behold originalspråket fra transkripsjonen.
5. Vær konsis men komplett — alle klinisk relevante detaljer er viktige.
6. Merk usikker informasjon med [VERIFISER].
7. Bruk standard norske medisinske forkortelser der det er passende.
8. Følg norsk journalformat og dokumentasjonspraksis.

Vanlige norske medisinske forkortelser:
- BT = blodtrykk
- P = puls
- T = temperatur
- RR = respirasjonsrate
- sat = oksygenmetning
- us = undersøkelse
- beh = behandling
- rtg = røntgen
- lab = laboratorieprøver
- anamn = anamnese
- obj = objektiv undersøkelse
- subj = subjektiv
- dg/diag = diagnose
- cave = advarsel/allergi
- ctr = kontroll
- ø.hj. = øyeblikkelig hjelp
- polikl = poliklinisk
- innl = innleggelse

Output format: Returner KUN gyldig JSON med de angitte nøklene."""

# Common Norwegian medical terms that STT often misrecognizes
# Maps common STT errors → correct medical terms
NORWEGIAN_STT_CORRECTIONS: dict[str, str] = {
    # Common STT errors for Norwegian medical terms
    "paracet": "paracetamol",
    "ibux": "ibuprofen",
    "blodtrykket": "blodtrykk",
    "hølser": "halsere",
    "feberen": "feber",
    "hode pine": "hodepine",
    "hodepinen": "hodepine",
    "mage smerter": "magesmerter",
    "bryst smerter": "brystsmerter",
    "rygg smerter": "ryggsmerter",
    "ledd smerter": "leddsmerter",
    "pusten": "pustebesvær",
    "allergisk": "allergi",
    "sukkersyke": "diabetes",
    "høyt blodtrykk": "hypertensjon",
    "lavt blodtrykk": "hypotensjon",
    "hjerteinfarkt": "myokardinfarkt",
    "hjerneslag": "cerebrovaskulær hendelse",
}

# ICD-10 mapping hints for common Norwegian diagnoses
# These help the LLM suggest correct codes
NORWEGIAN_ICD10_HINTS: dict[str, str] = {
    "hodepine": "R51 - Hodepine",
    "migrene": "G43 - Migrene",
    "hypertensjon": "I10 - Essensiell hypertensjon",
    "diabetes type 2": "E11 - Diabetes mellitus type 2",
    "diabetes type 1": "E10 - Diabetes mellitus type 1",
    "astma": "J45 - Astma",
    "kols": "J44 - Kronisk obstruktiv lungesykdom",
    "depresjon": "F32 - Depressiv episode",
    "angst": "F41 - Angstlidelser",
    "ryggsmerte": "M54 - Ryggsmerter",
    "urinveisinfeksjon": "N39.0 - Urinveisinfeksjon",
    "øvre luftveisinfeksjon": "J06 - Øvre luftveisinfeksjon",
    "pneumoni": "J18 - Pneumoni",
    "influensa": "J11 - Influensa",
    "covid": "U07.1 - COVID-19",
    "allergi": "T78.4 - Allergi",
    "eksem": "L30 - Dermatitt",
    "tensjonshodepine": "G44.2 - Tensjonshodepine",
}


def apply_stt_corrections(text: str) -> str:
    """
    Post-process STT output to fix common Norwegian medical term errors.

    This runs AFTER Whisper transcription, BEFORE sending to the LLM.
    It's a simple find-replace for known STT mistakes.
    """
    import re
    corrected = text
    for wrong, right in NORWEGIAN_STT_CORRECTIONS.items():
        pattern = re.compile(re.escape(wrong), re.IGNORECASE)
        corrected = pattern.sub(right, corrected)
    return corrected


def get_system_prompt(language: str = "no") -> str:
    """Get the appropriate system prompt based on language."""
    if language in ("no", "nb", "nn"):
        return NORWEGIAN_CLINICAL_SYSTEM_PROMPT
    # Default to English system prompt
    from medscribe.services.structuring import STRUCTURING_SYSTEM_PROMPT
    return STRUCTURING_SYSTEM_PROMPT


def suggest_icd10(text: str) -> list[dict[str, str]]:
    """
    Suggest ICD-10 codes based on text content.

    This is a simple keyword match. In production, you'd use
    a proper medical NLP model or ICD-10 search API.
    """
    suggestions = []
    text_lower = text.lower()
    for keyword, code in NORWEGIAN_ICD10_HINTS.items():
        if keyword in text_lower:
            suggestions.append({"keyword": keyword, "code": code})
    return suggestions
