from __future__ import annotations

"""
Post-processing layer — cleans and improves AI output quality.

This runs AFTER the LLM generates the clinical note, BEFORE
showing it to the doctor. It fixes:

1. Common STT transcription errors in Norwegian medical terms
2. Repetitive text (LLM sometimes repeats phrases)
3. Grammar and formatting issues
4. Replaces informal language with medical terminology
5. Removes obvious hallucinations

Production clinical AI systems never show raw LLM output.
Every output goes through a quality pipeline.
"""

import re

import structlog

logger = structlog.get_logger()

# Norwegian medical terminology corrections
# Maps informal/wrong → correct medical Norwegian
MEDICAL_TERM_CORRECTIONS: dict[str, str] = {
    # Common STT errors
    "hunt i hudde": "smerter i huden",
    "hunt i hude": "smerter i huden",
    "hunt i hodet": "hodepine",
    "vondt i hodet": "hodepine",
    "vondt i magen": "magesmerter",
    "vondt i ryggen": "ryggsmerter",
    "vondt i brystet": "brystsmerter",
    "vondt i halsen": "halssmerter",
    "har feber": "febrilia",
    "er kvalm": "kvalme",
    "kaster opp": "oppkast",
    "har hostet": "hoste",
    "puster tungt": "dyspné",
    "svimmel": "svimmelhet",
    "trøtt": "fatigue/tretthet",
    "klør": "pruritus",
    "utslett": "eksantem",
    "hoven": "hevelse/ødem",
    "nummen": "parestesier",
    # Informal → medical
    "blodtrykket er bra": "normotensiv",
    "blodtrykket er normalt": "normotensiv",
    "blodtrykket er høyt": "hypertensjon",
    "blodtrykket er lavt": "hypotensjon",
    "hjertet er bra": "normale hjertetoner",
    "lungene er bra": "normale respirasjonslyder",
    "sukkersyke": "diabetes mellitus",
    "høyt blodtrykk": "hypertensjon",
    "lavt blodtrykk": "hypotensjon",
    # Drug names
    "paracet": "paracetamol",
    "ibux": "ibuprofen",
    "voltaren": "diklofenak",
    "sobril": "oksazepam",
}

# Phrases that indicate hallucination (should not appear in clinical notes)
HALLUCINATION_MARKERS = [
    "as an ai",
    "i cannot",
    "i don't have",
    "i'm not sure",
    "sorry",
    "please note",
    "disclaimer",
    "this is not medical advice",
]


def post_process_note(sections: dict[str, str]) -> dict[str, str]:
    """
    Full post-processing pipeline for clinical note sections.

    Steps:
    1. Fix medical terminology
    2. Remove repetitions
    3. Clean formatting
    4. Remove hallucination markers
    5. Validate quality
    """
    processed = {}
    for key, text in sections.items():
        if not text or text == "Not documented." or text == "Ikke dokumentert.":
            processed[key] = "Ikke dokumentert."
            continue

        text = fix_medical_terms(text)
        text = remove_repetitions(text)
        text = remove_hallucinations(text)
        text = clean_formatting(text)

        processed[key] = text

    logger.info("post_processing.completed", sections_processed=len(processed))
    return processed


def fix_medical_terms(text: str) -> str:
    """Replace informal/incorrect terms with proper medical Norwegian."""
    result = text
    for wrong, correct in MEDICAL_TERM_CORRECTIONS.items():
        # Use word boundary matching to avoid partial replacements
        # e.g., "paracet" should match "paracet" but NOT "paracetamol"
        pattern = re.compile(r'\b' + re.escape(wrong) + r'\b', re.IGNORECASE)
        result = pattern.sub(correct, result)
    return result


def remove_repetitions(text: str) -> str:
    """
    Remove repeated phrases — small models often repeat themselves.

    Example: "hodepine hodepine hodepine" → "hodepine"
    Example: "Pasienten har smerter. Pasienten har smerter." → "Pasienten har smerter."
    """
    # Remove consecutive duplicate sentences
    sentences = text.split('. ')
    seen = []
    for s in sentences:
        s_clean = s.strip().rstrip('.')
        if s_clean and s_clean not in [x.rstrip('.') for x in seen]:
            seen.append(s)
    result = '. '.join(seen)

    # Remove consecutive duplicate words (3+ times)
    result = re.sub(r'\b(\w+)(\s+\1){2,}\b', r'\1', result, flags=re.IGNORECASE)

    return result


def remove_hallucinations(text: str) -> str:
    """Remove obvious hallucination markers from LLM output."""
    text_lower = text.lower()
    for marker in HALLUCINATION_MARKERS:
        if marker in text_lower:
            # Remove the sentence containing the marker
            sentences = text.split('. ')
            sentences = [s for s in sentences if marker not in s.lower()]
            text = '. '.join(sentences)
    return text


def clean_formatting(text: str) -> str:
    """Clean up formatting issues."""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    # Remove leading/trailing punctuation oddities
    text = text.strip('.,;: ')

    # Capitalize first letter
    if text and text[0].islower():
        text = text[0].upper() + text[1:]

    # Ensure ends with period
    if text and not text.endswith(('.', '!', '?')):
        text += '.'

    return text
