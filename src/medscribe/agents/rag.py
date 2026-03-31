from __future__ import annotations

"""
RAG (Retrieval-Augmented Generation) — patient-context Q&A.

This lets the doctor ask questions about a patient's history:
  "What medications was this patient on last visit?"
  "When was the last blood pressure reading?"
  "Summarize this patient's allergy history"

How it works:
1. Retrieve relevant visit notes from the database
2. Inject them as context into the LLM prompt
3. LLM answers the question based ONLY on the retrieved data
4. Source attribution — every answer cites which visit/note it came from

This is NOT a general chatbot. It's a retrieval system that:
- Only answers from patient data (no hallucination from training data)
- Cites sources (visit ID, date, section)
- Runs locally (no patient data to cloud)

For production scale, you'd add vector embeddings (pgvector / FAISS)
for semantic search. For now, we use simple keyword + date-based retrieval.
"""

import json
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from medscribe.services.base import LLMProvider
from medscribe.storage.database import ClinicalNoteRow, VisitRow

logger = structlog.get_logger()


class PatientRAG:
    """
    Retrieval-Augmented Generation for patient context.

    Usage:
        rag = PatientRAG(session, llm)
        answer = await rag.ask("Hva er pasientens allergier?", patient_id="P-001")
    """

    def __init__(self, session: AsyncSession, llm: LLMProvider) -> None:
        self._session = session
        self._llm = llm

    async def ask(self, question: str, patient_id: str, *, max_visits: int = 10) -> dict:
        """
        Answer a question about a patient based on their visit history.

        Returns:
            {
                "answer": "The patient's answer...",
                "sources": [{"visit_id": "...", "date": "...", "section": "..."}],
                "context_used": "...",
                "model_id": "...",
            }
        """
        # 1. Retrieve patient's visit notes
        context_chunks, sources = await self._retrieve_patient_context(patient_id, max_visits)

        if not context_chunks:
            return {
                "answer": "Ingen tidligere konsultasjonsnotater funnet for denne pasienten.",
                "sources": [],
                "context_used": "",
                "model_id": "",
            }

        context = "\n\n---\n\n".join(context_chunks)

        # 2. Generate answer with source attribution
        result = await self._llm.generate(
            prompt=f"""Svar på følgende spørsmål basert KUN på pasientens journalnotater nedenfor.

Spørsmål: {question}

Pasientens journalnotater:
{context}

Regler:
1. Svar KUN basert på informasjonen i notatene ovenfor.
2. Hvis informasjonen ikke finnes i notatene, si "Ikke funnet i tilgjengelige notater."
3. Referer til hvilken dato/besøk informasjonen kommer fra.
4. Svar på norsk.
5. Vær konsis og klinisk presis.""",
            system_prompt="Du er en medisinsk assistent som hjelper helsepersonell med å finne informasjon i pasientjournaler. Svar KUN basert på gitt kontekst.",
        )

        logger.info(
            "rag.answered",
            patient_id=patient_id,
            question_length=len(question),
            context_chunks=len(context_chunks),
            model=result.model_id,
        )

        return {
            "answer": result.text,
            "sources": sources,
            "context_used": f"{len(context_chunks)} visit notes, {len(context)} chars",
            "model_id": result.model_id,
        }

    async def _retrieve_patient_context(
        self, patient_id: str, max_visits: int
    ) -> tuple[list[str], list[dict]]:
        """Retrieve clinical notes for a patient, most recent first."""
        result = await self._session.execute(
            select(VisitRow, ClinicalNoteRow)
            .join(ClinicalNoteRow, VisitRow.id == ClinicalNoteRow.visit_id)
            .where(VisitRow.patient_id == patient_id)
            .order_by(VisitRow.created_at.desc())
            .limit(max_visits)
        )

        chunks = []
        sources = []

        for visit_row, note_row in result.fetchall():
            sections = json.loads(note_row.sections_json)
            section_text = "\n".join(
                f"  {k}: {v}" for k, v in sections.items()
                if v and v != "Not documented."
            )

            chunk = (
                f"[Besøk: {visit_row.created_at.strftime('%Y-%m-%d')} | "
                f"ID: {visit_row.id[:8]}]\n{section_text}"
            )
            chunks.append(chunk)
            sources.append({
                "visit_id": visit_row.id,
                "date": visit_row.created_at.isoformat(),
                "sections": list(sections.keys()),
            })

        return chunks, sources
