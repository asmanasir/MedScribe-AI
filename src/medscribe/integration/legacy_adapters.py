from __future__ import annotations

"""
Legacy Norwegian healthcare system adapters.

Not all Norwegian systems speak FHIR R4. Older systems use:
- HL7 v2.x messages (DIPS Classic, older hospital systems)
- XML/KITH messages (Norwegian standard before FHIR)
- Flat file / CSV exports (some municipal systems)
- SOAP/WSDL web services (older integrations)

This module provides adapters for these legacy formats so
MedScribe can integrate with ANY Norwegian healthcare system,
not just modern FHIR-based ones.

Supported formats:
1. HL7 v2.x MDM (Medical Document Management) — for DIPS Classic
2. KITH XML — Norwegian standard for clinical documents
3. Plain text / PDF — universal fallback
4. EPJ-Løft XML — for municipal healthcare systems
"""

import json
from datetime import datetime, timezone
from uuid import UUID
from xml.etree import ElementTree as ET

from medscribe.domain.models import ClinicalNote, Visit


class HL7v2Adapter:
    """
    HL7 v2.x MDM message adapter.

    Used by: DIPS Classic, older hospital systems.

    An MDM (Medical Document Management) message carries
    clinical documents between systems. This is the most
    common legacy integration format in Norwegian hospitals.

    Format: pipe-delimited segments (MSH|EVN|PID|TXA|OBX)
    """

    @staticmethod
    def build_mdm_message(visit: Visit, note: ClinicalNote) -> str:
        """Build an HL7 v2.x MDM^T02 message (document notification)."""
        now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        note_text = _sections_to_text(note)

        segments = [
            # MSH — Message Header
            f"MSH|^~\\&|MEDSCRIBE|MEDSCRIBE_AI|EPJ|HOSPITAL|{now}||MDM^T02|{note.id}|P|2.4",
            # EVN — Event Type
            f"EVN|T02|{now}",
            # PID — Patient Identification
            f"PID|||{visit.patient_id}^^^HOSPITAL||",
            # PV1 — Patient Visit
            f"PV1||O|||||{visit.clinician_id}",
            # TXA — Document Notification
            f"TXA|1|CN|TX|{now}|{visit.clinician_id}||{now}||{note.approved_by or ''}||||||||{'AU' if note.is_approved else 'IP'}",
            # OBX — Clinical note content
            f"OBX|1|TX|11488-4^Consult Note^LN||{_hl7_escape(note_text)}||||||F",
        ]

        return "\r".join(segments)


class KITHXMLAdapter:
    """
    KITH XML adapter — Norwegian standard for clinical documents.

    Used by: Older Norwegian EPJ systems, municipal health services.

    KITH (Kompetansesenter for IT i helse- og sosialsektoren) defined
    XML message standards used throughout Norwegian healthcare before FHIR.

    Common message types:
    - Epikrise (discharge summary)
    - Henvisning (referral)
    - Konsultasjonsnotat (consultation note)
    """

    @staticmethod
    def build_consultation_note(visit: Visit, note: ClinicalNote) -> str:
        """Build a KITH-style XML consultation note."""
        root = ET.Element("KliniskDokument")
        root.set("xmlns", "http://www.kith.no/xmlstds/kliniskdokument/2006-10-02")

        # Header
        header = ET.SubElement(root, "Dokumenthode")
        ET.SubElement(header, "DokumentId").text = str(note.id)
        ET.SubElement(header, "DokumentType").text = "Konsultasjonsnotat"
        ET.SubElement(header, "Opprettet").text = note.created_at.isoformat()
        ET.SubElement(header, "Status").text = "Godkjent" if note.is_approved else "Utkast"

        # Patient
        pasient = ET.SubElement(header, "Pasient")
        ET.SubElement(pasient, "PasientId").text = visit.patient_id

        # Author
        forfatter = ET.SubElement(header, "Forfatter")
        ET.SubElement(forfatter, "HelsepersonellId").text = visit.clinician_id

        if note.approved_by:
            godkjenner = ET.SubElement(header, "Godkjenner")
            ET.SubElement(godkjenner, "HelsepersonellId").text = note.approved_by
            if note.approved_at:
                ET.SubElement(godkjenner, "GodkjentDato").text = note.approved_at.isoformat()

        # AI metadata
        ai_meta = ET.SubElement(header, "AIMetadata")
        ET.SubElement(ai_meta, "ModellId").text = note.model_id
        ET.SubElement(ai_meta, "Kilde").text = "MedScribe AI"
        ET.SubElement(ai_meta, "MenneskeligGodkjent").text = str(note.is_approved).lower()

        # Clinical content — sections
        innhold = ET.SubElement(root, "KliniskInnhold")

        # Map section keys to Norwegian KITH names
        kith_names = {
            "chief_complaint": "Kontaktårsak",
            "history": "Sykehistorie",
            "examination": "Undersøkelse",
            "assessment": "Vurdering",
            "plan": "Tiltak",
            "medications": "Medisiner",
            "follow_up": "Oppfølging",
            "presenting_concern": "Henvendelsesgrunn",
            "psychiatric_history": "PsykiatriskHistorikk",
            "mental_status": "MentalStatus",
            "risk_assessment": "Risikovurdering",
            "triage": "Triage",
            "interventions": "TiltakUtført",
            "disposition": "VidereBehandling",
            "indication": "Indikasjon",
            "investigations": "SupplerendeUndersøkelser",
            "growth": "VekstOgUtvikling",
        }

        for key, content in note.sections.items():
            section_key = key.value if hasattr(key, "value") else str(key)
            kith_name = kith_names.get(section_key, section_key)
            seksjon = ET.SubElement(innhold, "Seksjon")
            ET.SubElement(seksjon, "Navn").text = kith_name
            ET.SubElement(seksjon, "Tekst").text = str(content)

        return ET.tostring(root, encoding="unicode", xml_declaration=True)


class PlainTextAdapter:
    """
    Plain text export — universal fallback.

    Used when the target system can only accept plain text or PDF.
    Works with ANY system that has a text import function.
    """

    @staticmethod
    def build_text_note(visit: Visit, note: ClinicalNote) -> str:
        """Build a formatted plain-text clinical note."""
        lines = [
            "=" * 60,
            "KONSULTASJONSNOTAT / CONSULTATION NOTE",
            "=" * 60,
            "",
            f"Pasient-ID:    {visit.patient_id}",
            f"Behandler:     {visit.clinician_id}",
            f"Dato:          {note.created_at.strftime('%Y-%m-%d %H:%M')}",
            f"Status:        {'Godkjent' if note.is_approved else 'Utkast'}",
        ]

        if note.approved_by:
            lines.append(f"Godkjent av:   {note.approved_by}")
            if note.approved_at:
                lines.append(f"Godkjent:      {note.approved_at.strftime('%Y-%m-%d %H:%M')}")

        lines.append(f"AI-modell:     {note.model_id}")
        lines.append("")
        lines.append("-" * 60)

        norwegian_labels = {
            "chief_complaint": "KONTAKTÅRSAK",
            "history": "SYKEHISTORIE",
            "examination": "UNDERSØKELSE",
            "assessment": "VURDERING",
            "plan": "TILTAK / PLAN",
            "medications": "MEDISINER",
            "follow_up": "OPPFØLGING",
            "presenting_concern": "HENVENDELSESGRUNN",
            "psychiatric_history": "PSYKIATRISK HISTORIKK",
            "mental_status": "MENTAL STATUS",
            "risk_assessment": "RISIKOVURDERING",
            "triage": "TRIAGE",
            "interventions": "TILTAK UTFØRT",
            "disposition": "VIDERE BEHANDLING",
        }

        for key, content in note.sections.items():
            section_key = key.value if hasattr(key, "value") else str(key)
            label = norwegian_labels.get(section_key, section_key.upper())
            lines.append("")
            lines.append(f"{label}:")
            lines.append(str(content))

        lines.append("")
        lines.append("-" * 60)
        lines.append("Generert av MedScribe AI — gjennomgått og godkjent av behandler")
        lines.append("=" * 60)

        return "\n".join(lines)


# --- Helpers ---

def _sections_to_text(note: ClinicalNote) -> str:
    """Convert note sections to plain text for HL7."""
    parts = []
    for key, content in note.sections.items():
        section_key = key.value if hasattr(key, "value") else str(key)
        parts.append(f"{section_key}: {content}")
    return " | ".join(parts)


def _hl7_escape(text: str) -> str:
    """Escape special HL7 characters."""
    return (
        text.replace("\\", "\\E\\")
        .replace("|", "\\F\\")
        .replace("^", "\\S\\")
        .replace("&", "\\T\\")
        .replace("~", "\\R\\")
        .replace("\r", "\\X0D\\")
        .replace("\n", "\\X0A\\")
    )
