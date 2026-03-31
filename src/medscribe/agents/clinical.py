from __future__ import annotations

"""
Clinical agents — specialized AI actions for healthcare workflows.

Each agent handles one specific clinical task:
- ReferralDraftAgent: Draft a referral letter to a specialist
- FollowUpAgent: Create follow-up tasks and appointments
- CarePlanAgent: Update the patient's care plan
- MedicationSummaryAgent: Summarize medication changes
- LetterDraftAgent: Draft patient letters (innkalling, epikriser)
- CodingAgent: Suggest ICD-10/ICPC-2 codes

These agents are composed into multi-step workflows by the Orchestrator.
"""

from medscribe.agents.base import ActionRisk, Agent
from medscribe.services.base import LLMProvider


class ReferralDraftAgent(Agent):
    """
    Drafts a referral letter (henvisning) to a specialist.

    Input: clinical note + reason for referral
    Output: formatted referral letter in Norwegian

    Risk: MEDIUM — doctor must review and approve before sending
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @property
    def agent_id(self) -> str:
        return "referral_draft"

    @property
    def name(self) -> str:
        return "Henvisningsutkast / Referral Draft"

    @property
    def risk(self) -> ActionRisk:
        return ActionRisk.MEDIUM

    async def preview(self, context: dict) -> dict:
        note_text = context.get("note_text", "")
        reason = context.get("referral_reason", "Vurdering hos spesialist")
        specialist = context.get("specialist", "Ikke spesifisert")

        result = await self._llm.generate(
            prompt=f"""Basert på følgende konsultasjonsnotat, skriv et utkast til henvisning.

Notat:
{note_text}

Henvisningsgrunn: {reason}
Henvises til: {specialist}

Skriv henvisningen på norsk i standard format med:
1. Pasientopplysninger (bruk [PASIENT-ID] som plassholder)
2. Henvisende lege
3. Henvisningsgrunn
4. Aktuell sykehistorie
5. Relevante funn
6. Tentativ diagnose
7. Ønsket vurdering/tiltak

Returner KUN henvisningsteksten.""",
            system_prompt="Du er en medisinsk dokumentasjonsassistent. Skriv profesjonelle, konsise henvisninger på norsk.",
        )

        return {
            "draft_letter": result.text,
            "specialist": specialist,
            "reason": reason,
            "model_id": result.model_id,
            "action": "Send this referral letter to specialist",
        }

    async def execute(self, context: dict) -> dict:
        # In production: send to EPJ referral system
        preview = context.get("preview_data", {})
        return {
            "referral_created": True,
            "letter": preview.get("draft_letter", ""),
            "specialist": preview.get("specialist", ""),
            "status": "draft_saved",
        }


class FollowUpAgent(Agent):
    """
    Creates follow-up tasks based on the clinical note.

    Analyzes the note and suggests follow-up actions:
    - Next appointment
    - Lab orders
    - Referral needed?
    - Prescription renewal
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @property
    def agent_id(self) -> str:
        return "follow_up"

    @property
    def name(self) -> str:
        return "Oppfølgingstiltak / Follow-up Tasks"

    async def preview(self, context: dict) -> dict:
        note_text = context.get("note_text", "")

        result = await self._llm.generate(
            prompt=f"""Analyser følgende konsultasjonsnotat og foreslå oppfølgingstiltak.

Notat:
{note_text}

Returner en JSON-liste med oppfølgingstiltak:
[
  {{"type": "appointment|lab|referral|prescription|other", "description": "...", "priority": "high|medium|low", "deadline": "..."}}
]

Returner KUN JSON-listen.""",
            system_prompt="Du er en medisinsk assistent som identifiserer nødvendige oppfølgingstiltak fra konsultasjonsnotater.",
        )

        import json
        try:
            text = result.text.strip()
            if text.startswith("```"):
                text = "\n".join(text.split("\n")[1:-1])
            tasks = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            tasks = [{"type": "other", "description": result.text, "priority": "medium", "deadline": ""}]

        return {
            "suggested_tasks": tasks,
            "task_count": len(tasks),
            "model_id": result.model_id,
        }

    async def execute(self, context: dict) -> dict:
        preview = context.get("preview_data", {})
        tasks = preview.get("suggested_tasks", [])
        return {
            "tasks_created": len(tasks),
            "tasks": tasks,
            "status": "tasks_saved",
        }


class CarePlanAgent(Agent):
    """
    Suggests updates to the patient's care plan (behandlingsplan).

    Analyzes the consultation and proposes care plan changes.
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @property
    def agent_id(self) -> str:
        return "care_plan"

    @property
    def name(self) -> str:
        return "Behandlingsplan / Care Plan Update"

    async def preview(self, context: dict) -> dict:
        note_text = context.get("note_text", "")
        current_plan = context.get("current_care_plan", "Ingen eksisterende plan.")

        result = await self._llm.generate(
            prompt=f"""Basert på konsultasjonsnotatet, foreslå oppdateringer til behandlingsplanen.

Gjeldende plan:
{current_plan}

Nytt konsultasjonsnotat:
{note_text}

Foreslå endringer i format:
- Nye tiltak å legge til
- Tiltak å fjerne eller endre
- Oppdaterte mål

Skriv på norsk.""",
            system_prompt="Du er en medisinsk assistent som hjelper med behandlingsplanlegging.",
        )

        return {
            "suggested_updates": result.text,
            "current_plan": current_plan,
            "model_id": result.model_id,
        }

    async def execute(self, context: dict) -> dict:
        preview = context.get("preview_data", {})
        return {
            "plan_updated": True,
            "updates": preview.get("suggested_updates", ""),
            "status": "plan_saved",
        }


class CodingAgent(Agent):
    """
    Suggests ICD-10 and ICPC-2 diagnosis codes.

    Risk: LOW — just suggestions, never auto-applied.
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @property
    def agent_id(self) -> str:
        return "coding"

    @property
    def name(self) -> str:
        return "Diagnosekoder / Diagnosis Coding"

    @property
    def risk(self) -> ActionRisk:
        return ActionRisk.LOW

    async def preview(self, context: dict) -> dict:
        note_text = context.get("note_text", "")

        # Also use our built-in ICD-10 hints
        from medscribe.services.norwegian import suggest_icd10
        keyword_suggestions = suggest_icd10(note_text)

        result = await self._llm.generate(
            prompt=f"""Basert på følgende konsultasjonsnotat, foreslå relevante diagnosekoder.

Notat:
{note_text}

Returner JSON:
[
  {{"code": "ICD-10 kode", "description": "Beskrivelse", "confidence": "high|medium|low"}}
]

Bruk norske ICD-10 koder. Returner KUN JSON.""",
            system_prompt="Du er en medisinsk kodeassistent. Foreslå ICD-10 og ICPC-2 koder basert på klinisk dokumentasjon.",
        )

        import json
        try:
            text = result.text.strip()
            if text.startswith("```"):
                text = "\n".join(text.split("\n")[1:-1])
            llm_codes = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            llm_codes = []

        return {
            "suggested_codes": llm_codes,
            "keyword_matches": keyword_suggestions,
            "model_id": result.model_id,
        }

    async def execute(self, context: dict) -> dict:
        preview = context.get("preview_data", {})
        return {
            "codes_suggested": True,
            "codes": preview.get("suggested_codes", []),
        }


class LetterDraftAgent(Agent):
    """
    Drafts patient letters: innkalling, epikrise, sykemelding.
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @property
    def agent_id(self) -> str:
        return "letter_draft"

    @property
    def name(self) -> str:
        return "Brevutkast / Letter Draft"

    @property
    def risk(self) -> ActionRisk:
        return ActionRisk.MEDIUM

    async def preview(self, context: dict) -> dict:
        note_text = context.get("note_text", "")
        letter_type = context.get("letter_type", "epikrise")
        recipient = context.get("recipient", "Pasient")

        type_instructions = {
            "epikrise": "Skriv en epikrise (utskrivningssammendrag) med diagnoser, behandling, og oppfølgingsplan.",
            "innkalling": "Skriv en innkalling til kontrolltime med dato, tid, forberedelser.",
            "sykemelding": "Skriv en medisinsk vurdering for sykemelding med diagnose, funksjonsvurdering, og varighet.",
            "informasjon": "Skriv et informasjonsbrev til pasienten om resultater eller tiltak.",
        }

        instruction = type_instructions.get(letter_type, f"Skriv et {letter_type}-brev.")

        result = await self._llm.generate(
            prompt=f"""Basert på konsultasjonsnotatet, {instruction}

Notat:
{note_text}

Mottaker: {recipient}

Skriv brevet på norsk i profesjonelt format.""",
            system_prompt="Du er en medisinsk dokumentasjonsassistent som skriver profesjonelle kliniske brev på norsk.",
        )

        return {
            "draft_letter": result.text,
            "letter_type": letter_type,
            "recipient": recipient,
            "model_id": result.model_id,
        }

    async def execute(self, context: dict) -> dict:
        preview = context.get("preview_data", {})
        return {
            "letter_created": True,
            "letter_type": preview.get("letter_type", ""),
            "letter": preview.get("draft_letter", ""),
            "status": "draft_saved",
        }
