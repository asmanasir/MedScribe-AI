from __future__ import annotations

"""
GDPR Data Lifecycle — the most critical module in the system.

Vidd's approach (and ours):
- MedScribe is a TRANSIT system, not a STORAGE system
- Patient data exists temporarily for processing only
- Once the note is approved and transferred to EPJ, ALL patient data is deleted
- Only audit logs remain (anonymized — no patient content)

GDPR principles enforced:
1. Data minimization — only process what's needed
2. Purpose limitation — data used only for note generation
3. Storage limitation — auto-delete after EPJ transfer
4. No persistent patient data — MedScribe is NOT the source of truth, the EPJ is

Data flow:
  Audio → [temp] → Transcript → [temp] → Note → [temp] → EPJ transfer → DELETE ALL

What stays after deletion:
- Audit log (WHO did WHAT, WHEN — but NOT the clinical content)
- System metrics (processing times, model versions — no PHI)

What gets deleted:
- Audio data (never stored on disk in the first place)
- Transcript text
- Clinical note content
- Visit metadata with patient identifiers
"""

import structlog
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from medscribe.storage.database import (
    ClinicalNoteRow,
    SafetyFlagRow,
    TranscriptRow,
    VisitRow,
    AuditEntryRow,
)

logger = structlog.get_logger()


class DataLifecycleManager:
    """
    Manages the lifecycle of patient data per GDPR requirements.

    Core rule: MedScribe holds patient data TEMPORARILY.
    Once transferred to EPJ, everything is purged.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def purge_visit_data(self, visit_id: UUID, *, actor: str) -> dict:
        """
        Delete ALL patient data for a visit after EPJ transfer.

        This is called after the approved note has been successfully
        transferred to the EPJ system. It removes:
        - Transcript (raw text, segments)
        - Clinical note (all sections, LLM output)
        - Safety flags (may contain clinical content)
        - Visit metadata (patient ID, clinician ID)

        It KEEPS:
        - Audit log entries (anonymized — detail field cleared of PHI)

        Returns a summary of what was deleted.
        """
        vid = str(visit_id)

        # 1. Delete transcript
        result = await self._session.execute(
            delete(TranscriptRow).where(TranscriptRow.visit_id == vid)
        )
        transcripts_deleted = result.rowcount

        # 2. Delete clinical note
        result = await self._session.execute(
            delete(ClinicalNoteRow).where(ClinicalNoteRow.visit_id == vid)
        )
        notes_deleted = result.rowcount

        # 3. Delete safety flags
        result = await self._session.execute(
            delete(SafetyFlagRow).where(SafetyFlagRow.visit_id == vid)
        )
        flags_deleted = result.rowcount

        # 4. Anonymize audit entries (keep structure, remove PHI from details)
        await self._session.execute(
            update(AuditEntryRow)
            .where(AuditEntryRow.visit_id == vid)
            .values(detail_json='{"purged": true}')
        )

        # 5. Delete visit record (contains patient_id)
        result = await self._session.execute(
            delete(VisitRow).where(VisitRow.id == vid)
        )
        visits_deleted = result.rowcount

        await self._session.flush()

        summary = {
            "visit_id": vid,
            "transcripts_deleted": transcripts_deleted,
            "notes_deleted": notes_deleted,
            "flags_deleted": flags_deleted,
            "visits_deleted": visits_deleted,
            "audit_entries": "anonymized (kept for compliance)",
            "purged_at": datetime.now(timezone.utc).isoformat(),
            "purged_by": actor,
        }

        logger.info(
            "privacy.visit_purged",
            visit_id=vid,
            actor=actor,
            transcripts=transcripts_deleted,
            notes=notes_deleted,
        )

        return summary

    async def purge_expired_visits(self, max_age_hours: int = 24, *, actor: str = "system") -> list[dict]:
        """
        Auto-purge visits older than max_age_hours.

        Safety net: even if EPJ transfer fails or is forgotten,
        patient data is automatically deleted after 24 hours.

        This should run as a scheduled task (cron job).
        """
        from sqlalchemy import select
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

        # Find expired visits
        result = await self._session.execute(
            select(VisitRow.id).where(VisitRow.created_at < cutoff)
        )
        expired_ids = [UUID(row[0]) for row in result.fetchall()]

        summaries = []
        for vid in expired_ids:
            summary = await self.purge_visit_data(vid, actor=actor)
            summaries.append(summary)

        if summaries:
            logger.info(
                "privacy.expired_visits_purged",
                count=len(summaries),
                max_age_hours=max_age_hours,
            )

        return summaries


class AudioDataPolicy:
    """
    Audio data handling policy.

    CRITICAL: Audio data (WAV/WebM) is NEVER written to disk.
    It exists only in memory during transcription, then is discarded.

    The only exception is faster-whisper which needs a temp file —
    that file is deleted immediately after transcription (see stt_local.py).
    """

    @staticmethod
    def validate_no_audio_on_disk(upload_dir: str = ".") -> bool:
        """
        Verify no audio files are stored on disk.
        Run this as a health check / compliance check.
        """
        import os
        audio_extensions = {".wav", ".mp3", ".m4a", ".webm", ".ogg", ".flac"}
        for root, dirs, files in os.walk(upload_dir):
            # Skip .git and venv
            dirs[:] = [d for d in dirs if d not in {".git", ".venv", "venv", "node_modules"}]
            for f in files:
                if any(f.lower().endswith(ext) for ext in audio_extensions):
                    logger.warning("privacy.audio_file_found", path=os.path.join(root, f))
                    return False
        return True
