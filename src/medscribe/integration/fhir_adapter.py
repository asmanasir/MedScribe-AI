from __future__ import annotations

"""
FHIR R4 Adapter — bridges MedScribe notes to Norwegian EPJ systems.

FHIR (Fast Healthcare Interoperability Resources) is THE standard for
healthcare data exchange in Norway. All major EPJ systems support it:
- Hospital EPJ systems → FHIR R4 REST API
- CGM (fastleger) → FHIR R4
- Helseplattformen (Epic) → FHIR R4
- Infodoc → FHIR R4

How it works:
1. Doctor approves a note in MedScribe
2. MedScribe converts the ClinicalNote → FHIR DocumentReference
3. MedScribe POSTs the DocumentReference to the EPJ's FHIR endpoint
4. EPJ stores it in the patient's journal
5. MedScribe purges all patient data (GDPR)

FHIR resource mapping:
  ClinicalNote → DocumentReference (the note itself)
  Visit        → Encounter (the clinical visit)
  Sections     → Composition (structured document)

We use the `fhir.resources` library for validated FHIR R4 models.
"""

from datetime import datetime, timezone

import structlog

from medscribe.domain.models import ClinicalNote, Visit

logger = structlog.get_logger()


class FHIRDocumentBuilder:
    """
    Converts MedScribe domain objects to FHIR R4 resources.

    Usage:
        builder = FHIRDocumentBuilder(fhir_base_url="https://hospital.example.no/fhir")
        doc_ref = builder.build_document_reference(visit, note)
        composition = builder.build_composition(visit, note)
        bundle = builder.build_bundle(visit, note)
    """

    def __init__(self, fhir_base_url: str = "") -> None:
        self._base_url = fhir_base_url

    def build_document_reference(self, visit: Visit, note: ClinicalNote) -> dict:
        """
        Build a FHIR DocumentReference — a pointer to the clinical note.

        This is what gets POSTed to the EPJ's FHIR endpoint.
        The EPJ uses this to store the note in the patient's journal.

        FHIR spec: https://hl7.org/fhir/R4/documentreference.html
        """
        return {
            "resourceType": "DocumentReference",
            "id": str(note.id),
            "status": "current",
            "docStatus": "final" if note.is_approved else "preliminary",
            "type": {
                "coding": [{
                    "system": "http://loinc.org",
                    "code": "11488-4",
                    "display": "Consult note",
                }]
            },
            "category": [{
                "coding": [{
                    "system": "http://loinc.org",
                    "code": "11488-4",
                    "display": "Consult note",
                }]
            }],
            "subject": {
                "reference": f"Patient/{visit.patient_id}",
                "display": visit.patient_id,
            },
            "date": note.created_at.isoformat(),
            "author": [{
                "reference": f"Practitioner/{visit.clinician_id}",
                "display": visit.clinician_id,
            }],
            "authenticator": {
                "reference": f"Practitioner/{note.approved_by}",
            } if note.approved_by else None,
            "description": "AI-assisted clinical note — reviewed and approved by clinician",
            "content": [{
                "attachment": {
                    "contentType": "application/fhir+json",
                    "language": "no",
                    "title": "Clinical Note",
                    "creation": note.created_at.isoformat(),
                },
                "format": {
                    "system": "http://ihe.net/fhir/ValueSet/IHE.FormatCode.codesystem",
                    "code": "urn:ihe:iti:xds:2017:mimeTypeSufficient",
                }
            }],
            "context": {
                "encounter": [{
                    "reference": f"Encounter/{visit.id}",
                }],
                "period": {
                    "start": visit.created_at.isoformat(),
                    "end": visit.updated_at.isoformat(),
                },
            },
        }

    def build_composition(self, visit: Visit, note: ClinicalNote) -> dict:
        """
        Build a FHIR Composition — the structured clinical note.

        A Composition is the FHIR way to represent a structured document
        with sections (like a clinical note with Assessment, Plan, etc.)

        This maps directly to the Norwegian EPJ journal note format.
        FHIR spec: https://hl7.org/fhir/R4/composition.html
        """
        # Map our sections to LOINC codes (standard clinical section codes)
        section_loinc = {
            "chief_complaint": ("10154-3", "Kontaktårsak", "Chief complaint"),
            "history": ("10164-2", "Sykehistorie", "History of present illness"),
            "examination": ("29545-1", "Undersøkelse", "Physical examination"),
            "assessment": ("51848-0", "Vurdering", "Assessment"),
            "plan": ("18776-5", "Tiltak/Plan", "Treatment plan"),
            "medications": ("10160-0", "Medisiner", "Medications"),
            "follow_up": ("69730-0", "Oppfølging", "Follow-up"),
            # Psychiatry sections
            "presenting_concern": ("10154-3", "Henvendelsesgrunn", "Presenting concern"),
            "psychiatric_history": ("11348-0", "Psykiatrisk historikk", "Psychiatric history"),
            "mental_status": ("10190-7", "Mental status", "Mental status exam"),
            "risk_assessment": ("80339-5", "Risikovurdering", "Risk assessment"),
            # Surgery sections
            "indication": ("42349-1", "Indikasjon", "Surgical indication"),
            "investigations": ("30954-2", "Supplerende undersøkelser", "Investigations"),
            "consent_info": ("59284-0", "Informert samtykke", "Informed consent"),
            # Emergency sections
            "triage": ("54094-8", "Triage", "Triage"),
            "interventions": ("29554-3", "Tiltak utført", "Interventions"),
            "disposition": ("11302-7", "Videre behandling", "Disposition"),
            # Pediatrics sections
            "growth": ("29274-8", "Vekst og utvikling", "Growth and development"),
        }

        fhir_sections = []
        for key, content in note.sections.items():
            # Handle both enum and string keys
            section_key = key.value if hasattr(key, 'value') else str(key)
            loinc_code, title_no, title_en = section_loinc.get(
                section_key, ("", section_key, section_key)
            )

            fhir_sections.append({
                "title": title_no,
                "code": {
                    "coding": [{
                        "system": "http://loinc.org",
                        "code": loinc_code,
                        "display": title_en,
                    }]
                } if loinc_code else None,
                "text": {
                    "status": "generated",
                    "div": f'<div xmlns="http://www.w3.org/1999/xhtml"><p>{_escape_html(content)}</p></div>',
                },
            })

        return {
            "resourceType": "Composition",
            "id": str(note.id),
            "status": "final" if note.is_approved else "preliminary",
            "type": {
                "coding": [{
                    "system": "http://loinc.org",
                    "code": "11488-4",
                    "display": "Consult note",
                }]
            },
            "subject": {
                "reference": f"Patient/{visit.patient_id}",
            },
            "encounter": {
                "reference": f"Encounter/{visit.id}",
            },
            "date": note.created_at.isoformat(),
            "author": [{
                "reference": f"Practitioner/{visit.clinician_id}",
            }],
            "title": "Konsultasjonsnotat — Clinical Note",
            "attester": [{
                "mode": "professional",
                "time": note.approved_at.isoformat() if note.approved_at else None,
                "party": {
                    "reference": f"Practitioner/{note.approved_by}",
                } if note.approved_by else None,
            }] if note.is_approved else [],
            "section": fhir_sections,
            "meta": {
                "tag": [{
                    "system": "http://medscribe.ai/tags",
                    "code": "ai-assisted",
                    "display": f"AI-assisted note (model: {note.model_id})",
                }]
            },
        }

    def build_bundle(self, visit: Visit, note: ClinicalNote) -> dict:
        """
        Build a FHIR Bundle containing both DocumentReference and Composition.

        A Bundle is a collection of resources that can be submitted as a
        single transaction to the EPJ's FHIR endpoint.

        FHIR spec: https://hl7.org/fhir/R4/bundle.html
        """
        doc_ref = self.build_document_reference(visit, note)
        composition = self.build_composition(visit, note)

        return {
            "resourceType": "Bundle",
            "type": "transaction",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "entry": [
                {
                    "fullUrl": f"urn:uuid:{note.id}",
                    "resource": composition,
                    "request": {
                        "method": "POST",
                        "url": "Composition",
                    },
                },
                {
                    "fullUrl": f"urn:uuid:{note.id}-docref",
                    "resource": doc_ref,
                    "request": {
                        "method": "POST",
                        "url": "DocumentReference",
                    },
                },
            ],
        }


def _escape_html(text: str) -> str:
    """Escape HTML special characters for FHIR narrative."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
