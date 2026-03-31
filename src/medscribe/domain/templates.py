from __future__ import annotations

"""
Clinical note templates — configurable per medical specialty.

Different specialties need different note structures:
- General Practice: SOAP format
- Psychiatry: Mental status exam, risk assessment
- Surgery: Pre-op, procedure, post-op
- Pediatrics: Growth, development, vaccination
- Emergency: Triage, interventions, disposition

Each template defines:
1. Which sections to include
2. Section labels (can be Norwegian or English)
3. Prompts that guide the LLM on what to extract
4. Default values

Doctors can select a template before recording.
The structuring LLM uses the template to produce the right format.
"""

from dataclasses import dataclass, field


@dataclass
class TemplateSection:
    """A single section in a clinical note template."""
    key: str                  # Internal identifier
    label: str                # Display label (Norwegian)
    label_en: str             # Display label (English)
    prompt_hint: str          # Guides the LLM on what to extract for this section
    required: bool = True     # Must be filled
    default: str = ""         # Default text if nothing extracted


@dataclass
class NoteTemplate:
    """A complete clinical note template for a specialty."""
    id: str
    name: str                 # Norwegian name
    name_en: str              # English name
    specialty: str
    description: str
    sections: list[TemplateSection] = field(default_factory=list)

    def section_keys(self) -> list[str]:
        return [s.key for s in self.sections]

    def to_llm_prompt(self) -> str:
        """Generate the JSON schema instruction for the LLM."""
        lines = []
        for s in self.sections:
            req = "(required)" if s.required else "(optional)"
            lines.append(f'- {s.key}: {s.prompt_hint} {req}')
        return "\n".join(lines)

    def to_json_keys(self) -> str:
        """Generate the JSON keys the LLM should return."""
        return ", ".join(f'"{s.key}"' for s in self.sections)


# ============================================================
# Built-in templates
# ============================================================

GENERAL_PRACTICE = NoteTemplate(
    id="general_practice",
    name="Allmennpraksis",
    name_en="General Practice",
    specialty="general",
    description="Standard SOAP-basert konsultasjonsnotat",
    sections=[
        TemplateSection(
            key="chief_complaint",
            label="Kontaktårsak",
            label_en="Chief Complaint",
            prompt_hint="The main reason for the visit, in the patient's own words",
        ),
        TemplateSection(
            key="history",
            label="Sykehistorie",
            label_en="History",
            prompt_hint="Relevant medical history, current illness timeline, previous treatments",
        ),
        TemplateSection(
            key="examination",
            label="Undersøkelse",
            label_en="Examination",
            prompt_hint="Physical examination findings, vital signs, observations",
        ),
        TemplateSection(
            key="assessment",
            label="Vurdering",
            label_en="Assessment",
            prompt_hint="Clinical assessment, working diagnosis, differential diagnoses",
        ),
        TemplateSection(
            key="plan",
            label="Tiltak / Plan",
            label_en="Plan",
            prompt_hint="Treatment plan, referrals, tests ordered, follow-up actions",
        ),
        TemplateSection(
            key="medications",
            label="Medisiner",
            label_en="Medications",
            prompt_hint="New prescriptions, medication changes, or continued medications discussed",
            required=False,
        ),
        TemplateSection(
            key="follow_up",
            label="Oppfølging",
            label_en="Follow-up",
            prompt_hint="Follow-up appointments, patient instructions, when to return",
            required=False,
        ),
    ],
)

PSYCHIATRY = NoteTemplate(
    id="psychiatry",
    name="Psykiatri",
    name_en="Psychiatry",
    specialty="psychiatry",
    description="Psykiatrisk konsultasjonsnotat med mental status",
    sections=[
        TemplateSection(
            key="presenting_concern",
            label="Henvendelsesgrunn",
            label_en="Presenting Concern",
            prompt_hint="Main psychiatric complaint or reason for consultation",
        ),
        TemplateSection(
            key="psychiatric_history",
            label="Psykiatrisk historikk",
            label_en="Psychiatric History",
            prompt_hint="Past psychiatric diagnoses, hospitalizations, treatments, substance use",
        ),
        TemplateSection(
            key="mental_status",
            label="Mental status",
            label_en="Mental Status Examination",
            prompt_hint="Appearance, behavior, speech, mood, affect, thought process, thought content, cognition, insight, judgment",
        ),
        TemplateSection(
            key="risk_assessment",
            label="Risikovurdering",
            label_en="Risk Assessment",
            prompt_hint="Suicidal ideation, self-harm risk, violence risk, protective factors",
        ),
        TemplateSection(
            key="assessment",
            label="Vurdering",
            label_en="Assessment",
            prompt_hint="Clinical assessment and diagnostic impression",
        ),
        TemplateSection(
            key="plan",
            label="Behandlingsplan",
            label_en="Treatment Plan",
            prompt_hint="Therapy, medications, safety plan, referrals, follow-up schedule",
        ),
        TemplateSection(
            key="medications",
            label="Medisiner",
            label_en="Medications",
            prompt_hint="Psychotropic medications: new, adjusted, or continued",
            required=False,
        ),
    ],
)

SURGERY = NoteTemplate(
    id="surgery",
    name="Kirurgi",
    name_en="Surgery",
    specialty="surgery",
    description="Kirurgisk konsultasjon / pre-operativ vurdering",
    sections=[
        TemplateSection(
            key="indication",
            label="Indikasjon",
            label_en="Indication",
            prompt_hint="Surgical indication and reason for referral",
        ),
        TemplateSection(
            key="history",
            label="Sykehistorie",
            label_en="History",
            prompt_hint="Relevant surgical history, comorbidities, previous operations",
        ),
        TemplateSection(
            key="examination",
            label="Klinisk undersøkelse",
            label_en="Clinical Examination",
            prompt_hint="Physical exam findings relevant to the surgical condition",
        ),
        TemplateSection(
            key="investigations",
            label="Supplerende undersøkelser",
            label_en="Investigations",
            prompt_hint="Lab results, imaging findings, other diagnostic results",
        ),
        TemplateSection(
            key="assessment",
            label="Vurdering",
            label_en="Assessment",
            prompt_hint="Surgical assessment, ASA classification if applicable",
        ),
        TemplateSection(
            key="plan",
            label="Operativ plan",
            label_en="Surgical Plan",
            prompt_hint="Planned procedure, approach, timing, pre-op preparations",
        ),
        TemplateSection(
            key="consent_info",
            label="Informert samtykke",
            label_en="Informed Consent",
            prompt_hint="Risks and benefits discussed with patient, consent status",
            required=False,
        ),
    ],
)

EMERGENCY = NoteTemplate(
    id="emergency",
    name="Akuttmedisin",
    name_en="Emergency Medicine",
    specialty="emergency",
    description="Akuttmedisinsk notat med triage",
    sections=[
        TemplateSection(
            key="triage",
            label="Triage",
            label_en="Triage",
            prompt_hint="Triage level, chief complaint, mechanism of injury/illness",
        ),
        TemplateSection(
            key="history",
            label="Anamnese",
            label_en="History",
            prompt_hint="History of present illness, SAMPLE history (Signs, Allergies, Medications, Past history, Last meal, Events)",
        ),
        TemplateSection(
            key="examination",
            label="Undersøkelse",
            label_en="Examination",
            prompt_hint="Primary and secondary survey findings, vital signs, GCS if applicable",
        ),
        TemplateSection(
            key="interventions",
            label="Tiltak utført",
            label_en="Interventions",
            prompt_hint="Procedures performed, medications administered, fluids given",
        ),
        TemplateSection(
            key="assessment",
            label="Vurdering",
            label_en="Assessment",
            prompt_hint="Working diagnosis, differential diagnoses, severity assessment",
        ),
        TemplateSection(
            key="disposition",
            label="Videre behandling",
            label_en="Disposition",
            prompt_hint="Admitted/discharged, ward, follow-up plan, discharge instructions",
        ),
    ],
)

PEDIATRICS = NoteTemplate(
    id="pediatrics",
    name="Pediatri",
    name_en="Pediatrics",
    specialty="pediatrics",
    description="Barnelegenotat med vekst og utvikling",
    sections=[
        TemplateSection(
            key="chief_complaint",
            label="Kontaktårsak",
            label_en="Chief Complaint",
            prompt_hint="Main concern, reported by parent/guardian or child",
        ),
        TemplateSection(
            key="history",
            label="Sykehistorie",
            label_en="History",
            prompt_hint="Birth history, developmental milestones, vaccination status, previous illnesses",
        ),
        TemplateSection(
            key="growth",
            label="Vekst og utvikling",
            label_en="Growth & Development",
            prompt_hint="Weight, height, head circumference, growth percentiles, developmental concerns",
            required=False,
        ),
        TemplateSection(
            key="examination",
            label="Undersøkelse",
            label_en="Examination",
            prompt_hint="Physical examination findings appropriate for age",
        ),
        TemplateSection(
            key="assessment",
            label="Vurdering",
            label_en="Assessment",
            prompt_hint="Clinical assessment considering age-specific differentials",
        ),
        TemplateSection(
            key="plan",
            label="Plan",
            label_en="Plan",
            prompt_hint="Treatment, referrals, vaccinations, parent guidance, follow-up",
        ),
    ],
)


# Registry of all templates
TEMPLATE_REGISTRY: dict[str, NoteTemplate] = {
    t.id: t for t in [GENERAL_PRACTICE, PSYCHIATRY, SURGERY, EMERGENCY, PEDIATRICS]
}


def get_template(template_id: str) -> NoteTemplate:
    """Get a template by ID. Falls back to general practice."""
    return TEMPLATE_REGISTRY.get(template_id, GENERAL_PRACTICE)


def list_templates() -> list[dict]:
    """List all available templates (for the UI dropdown)."""
    return [
        {
            "id": t.id,
            "name": t.name,
            "name_en": t.name_en,
            "specialty": t.specialty,
            "description": t.description,
            "section_count": len(t.sections),
        }
        for t in TEMPLATE_REGISTRY.values()
    ]
