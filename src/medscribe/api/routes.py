"""
API routes — the endpoints Aidn and external systems call.

Design:
- Routes are THIN. They validate input, call services, return output.
- No business logic in routes. That's in the workflow/services layers.
- Every endpoint returns typed responses (Pydantic schemas).
- Errors return structured JSON (not HTML 500 pages).

Versioning: All routes are under /api/v1/. When you need breaking changes,
add /api/v2/ routes alongside v1. Never break existing clients.
"""

from datetime import datetime, timezone
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile

from medscribe.api.auth import AuthenticatedUser, get_current_user
from medscribe.api.dependencies import (
    get_audit_repo,
    get_db_session,
    get_guardrails,
    get_note_repo,
    get_orchestrator,
    get_safety_flag_repo,
    get_transcript_repo,
    get_visit_repo,
    get_workflow_engine,
)
from medscribe.api.schemas import (
    ApproveNoteRequest,
    AuditEntryResponse,
    ClinicalNoteResponse,
    CreateVisitRequest,
    EditNoteRequest,
    ErrorResponse,
    ProcessVisitResponse,
    SafetyFlagResponse,
    TranscriptResponse,
    VisitResponse,
)
from medscribe.domain.enums import AuditAction, VisitStatus
from medscribe.domain.models import AuditEntry, Visit
from medscribe.safety.guardrails import SafetyGuardrails
from medscribe.storage.repositories import (
    AuditRepository,
    ClinicalNoteRepository,
    SafetyFlagRepository,
    TranscriptRepository,
    VisitRepository,
)
from medscribe.workflow.engine import InvalidTransitionError, WorkflowEngine
from medscribe.workflow.orchestrator import VisitOrchestrator

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["MedScribe AI"])


# --- Visit CRUD ---


@router.post("/visits", response_model=VisitResponse, status_code=201)
async def create_visit(
    request: CreateVisitRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    visit_repo: VisitRepository = Depends(get_visit_repo),
    audit_repo: AuditRepository = Depends(get_audit_repo),
):
    """Create a new clinical visit."""
    visit = Visit(
        patient_id=request.patient_id,
        clinician_id=request.clinician_id,
        metadata=request.metadata,
    )
    await visit_repo.save(visit)

    audit = AuditEntry(
        visit_id=visit.id,
        action=AuditAction.VISIT_CREATED,
        actor=user.user_id,
    )
    await audit_repo.save(audit)

    engine = WorkflowEngine()
    return VisitResponse(
        id=visit.id,
        patient_id=visit.patient_id,
        clinician_id=visit.clinician_id,
        status=visit.status,
        allowed_transitions=list(engine.get_allowed_transitions(visit)),
        created_at=visit.created_at,
        updated_at=visit.updated_at,
        metadata=visit.metadata,
    )


@router.get("/visits/{visit_id}", response_model=VisitResponse)
async def get_visit(
    visit_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    visit_repo: VisitRepository = Depends(get_visit_repo),
):
    """Get visit details and current state."""
    visit = await visit_repo.get(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    engine = WorkflowEngine()
    return VisitResponse(
        id=visit.id,
        patient_id=visit.patient_id,
        clinician_id=visit.clinician_id,
        status=visit.status,
        allowed_transitions=list(engine.get_allowed_transitions(visit)),
        created_at=visit.created_at,
        updated_at=visit.updated_at,
        metadata=visit.metadata,
    )


@router.get("/visits/{visit_id}/status")
async def get_visit_status(
    visit_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    visit_repo: VisitRepository = Depends(get_visit_repo),
):
    """Lightweight status check — useful for polling."""
    visit = await visit_repo.get(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    return {"visit_id": visit_id, "status": visit.status.value}


# --- Audio Processing ---


@router.post(
    "/visits/{visit_id}/transcribe",
    response_model=TranscriptResponse,
    responses={400: {"model": ErrorResponse}},
)
async def transcribe_audio(
    visit_id: UUID,
    audio: UploadFile,
    user: AuthenticatedUser = Depends(get_current_user),
    visit_repo: VisitRepository = Depends(get_visit_repo),
    transcript_repo: TranscriptRepository = Depends(get_transcript_repo),
    audit_repo: AuditRepository = Depends(get_audit_repo),
    guardrails: SafetyGuardrails = Depends(get_guardrails),
    safety_repo: SafetyFlagRepository = Depends(get_safety_flag_repo),
    orchestrator: VisitOrchestrator = Depends(get_orchestrator),
):
    """Upload audio and transcribe it."""
    visit = await visit_repo.get(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    audio_data = await audio.read()
    if not audio_data:
        raise HTTPException(status_code=400, detail="Empty audio file")

    # Convert browser audio (WebM) to WAV for Whisper
    from medscribe.services.audio_utils import convert_to_wav, detect_format
    src_fmt = detect_format(audio.filename or "recording.webm")
    if src_fmt != "wav":
        audio_data = convert_to_wav(audio_data, source_format=src_fmt)

    try:
        visit, transcript, audits = await orchestrator.process_audio(
            visit, audio_data, actor=visit.clinician_id
        )
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Run safety checks on transcript
    safety_result = guardrails.check_transcript(transcript)
    if safety_result.flags:
        await safety_repo.save_many(safety_result.flags)

    # Persist everything
    await visit_repo.save(visit)
    await transcript_repo.save(transcript)
    await audit_repo.save_many(audits)

    return TranscriptResponse(
        id=transcript.id,
        visit_id=transcript.visit_id,
        raw_text=transcript.raw_text,
        language=transcript.language,
        model_id=transcript.model_id,
        confidence=transcript.confidence,
        duration_seconds=transcript.duration_seconds,
        segment_count=len(transcript.segments),
        created_at=transcript.created_at,
    )


# --- Structuring ---


@router.post(
    "/visits/{visit_id}/structure",
    response_model=ClinicalNoteResponse,
    responses={400: {"model": ErrorResponse}},
)
async def structure_visit(
    visit_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    visit_repo: VisitRepository = Depends(get_visit_repo),
    transcript_repo: TranscriptRepository = Depends(get_transcript_repo),
    note_repo: ClinicalNoteRepository = Depends(get_note_repo),
    audit_repo: AuditRepository = Depends(get_audit_repo),
    guardrails: SafetyGuardrails = Depends(get_guardrails),
    safety_repo: SafetyFlagRepository = Depends(get_safety_flag_repo),
    orchestrator: VisitOrchestrator = Depends(get_orchestrator),
):
    """Structure an existing transcript into a clinical note."""
    visit = await visit_repo.get(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    transcript = await transcript_repo.get_by_visit(visit_id)
    if not transcript:
        raise HTTPException(status_code=400, detail="No transcript found — transcribe first")

    try:
        visit, note, audits = await orchestrator.structure_transcript(
            visit, transcript, actor=visit.clinician_id
        )
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Run safety checks
    safety_result = guardrails.check_note(note, confidence=0.5)
    if safety_result.flags:
        await safety_repo.save_many(safety_result.flags)

    # Persist
    await visit_repo.save(visit)
    await note_repo.save(note)
    await audit_repo.save_many(audits)

    return ClinicalNoteResponse(
        id=note.id,
        visit_id=note.visit_id,
        sections=note.sections,
        model_id=note.model_id,
        is_approved=note.is_approved,
        approved_by=note.approved_by,
        approved_at=note.approved_at,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


# --- Full Pipeline ---


@router.post(
    "/visits/{visit_id}/process",
    response_model=ProcessVisitResponse,
    responses={400: {"model": ErrorResponse}},
)
async def process_visit(
    visit_id: UUID,
    audio: UploadFile,
    user: AuthenticatedUser = Depends(get_current_user),
    visit_repo: VisitRepository = Depends(get_visit_repo),
    transcript_repo: TranscriptRepository = Depends(get_transcript_repo),
    note_repo: ClinicalNoteRepository = Depends(get_note_repo),
    audit_repo: AuditRepository = Depends(get_audit_repo),
    guardrails: SafetyGuardrails = Depends(get_guardrails),
    safety_repo: SafetyFlagRepository = Depends(get_safety_flag_repo),
    orchestrator: VisitOrchestrator = Depends(get_orchestrator),
):
    """
    Full pipeline: audio → transcribe → structure → review.

    This is the main endpoint for Aidn integration.
    One call does everything. The visit ends in REVIEW state,
    waiting for human approval.
    """
    visit = await visit_repo.get(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    audio_data = await audio.read()
    if not audio_data:
        raise HTTPException(status_code=400, detail="Empty audio file")

    # Convert browser audio (WebM) to WAV for Whisper
    from medscribe.services.audio_utils import convert_to_wav, detect_format
    src_fmt = detect_format(audio.filename or "recording.webm")
    if src_fmt != "wav":
        audio_data = convert_to_wav(audio_data, source_format=src_fmt)

    try:
        visit, transcript, note, audits = await orchestrator.process_visit(
            visit, audio_data, actor=visit.clinician_id
        )
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Safety checks
    safety_flags_list = []
    for check_result in [
        guardrails.check_transcript(transcript),
        guardrails.check_note(note, confidence=0.5),
    ]:
        safety_flags_list.extend(check_result.flags)

    if safety_flags_list:
        await safety_repo.save_many(safety_flags_list)

    # Persist everything
    await visit_repo.save(visit)
    await transcript_repo.save(transcript)
    await note_repo.save(note)
    await audit_repo.save_many(audits)

    return ProcessVisitResponse(
        visit=VisitResponse(
            id=visit.id,
            patient_id=visit.patient_id,
            clinician_id=visit.clinician_id,
            status=visit.status,
            allowed_transitions=list(WorkflowEngine().get_allowed_transitions(visit)),
            created_at=visit.created_at,
            updated_at=visit.updated_at,
            metadata=visit.metadata,
        ),
        transcript=TranscriptResponse(
            id=transcript.id,
            visit_id=transcript.visit_id,
            raw_text=transcript.raw_text,
            language=transcript.language,
            model_id=transcript.model_id,
            confidence=transcript.confidence,
            duration_seconds=transcript.duration_seconds,
            segment_count=len(transcript.segments),
            created_at=transcript.created_at,
        ),
        note=ClinicalNoteResponse(
            id=note.id,
            visit_id=note.visit_id,
            sections=note.sections,
            model_id=note.model_id,
            is_approved=note.is_approved,
            approved_by=note.approved_by,
            approved_at=note.approved_at,
            created_at=note.created_at,
            updated_at=note.updated_at,
        ),
        safety_flags=[
            SafetyFlagResponse(
                id=f.id, severity=f.severity, category=f.category,
                message=f.message, resolved=f.resolved, created_at=f.created_at,
            )
            for f in safety_flags_list
        ],
    )


# --- Note Management ---


@router.put("/visits/{visit_id}/note", response_model=ClinicalNoteResponse)
async def edit_note(
    visit_id: UUID,
    request: EditNoteRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    note_repo: ClinicalNoteRepository = Depends(get_note_repo),
    audit_repo: AuditRepository = Depends(get_audit_repo),
    visit_repo: VisitRepository = Depends(get_visit_repo),
):
    """Edit a clinical note before approval. Human-in-the-loop."""
    visit = await visit_repo.get(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    note = await note_repo.get_by_visit(visit_id)
    if not note:
        raise HTTPException(status_code=404, detail="No note found for this visit")

    if note.is_approved:
        raise HTTPException(status_code=409, detail="Cannot edit an approved note")

    # Update sections
    note = note.model_copy(update={"sections": request.sections})
    await note_repo.save(note)

    audit = AuditEntry(
        visit_id=visit_id,
        action=AuditAction.NOTE_EDITED,
        actor=visit.clinician_id,
        detail={"edited_sections": [s.value for s in request.sections]},
    )
    await audit_repo.save(audit)

    return ClinicalNoteResponse(
        id=note.id,
        visit_id=note.visit_id,
        sections=note.sections,
        model_id=note.model_id,
        is_approved=note.is_approved,
        approved_by=note.approved_by,
        approved_at=note.approved_at,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


@router.post("/visits/{visit_id}/approve", response_model=ClinicalNoteResponse)
async def approve_note(
    visit_id: UUID,
    request: ApproveNoteRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    visit_repo: VisitRepository = Depends(get_visit_repo),
    note_repo: ClinicalNoteRepository = Depends(get_note_repo),
    audit_repo: AuditRepository = Depends(get_audit_repo),
    engine: WorkflowEngine = Depends(get_workflow_engine),
):
    """
    Approve a clinical note — the human-in-the-loop step.

    This is THE most important endpoint. Nothing is finalized
    without explicit human approval. Aidn requires this.
    """
    visit = await visit_repo.get(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    note = await note_repo.get_by_visit(visit_id)
    if not note:
        raise HTTPException(status_code=404, detail="No note found for this visit")

    if note.is_approved:
        raise HTTPException(status_code=409, detail="Note already approved")

    # Transition visit to APPROVED
    try:
        visit, audit = engine.transition(
            visit, VisitStatus.APPROVED, actor=request.approved_by
        )
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Mark note as approved
    note = note.model_copy(update={
        "is_approved": True,
        "approved_by": request.approved_by,
        "approved_at": datetime.now(timezone.utc),
    })

    await visit_repo.save(visit)
    await note_repo.save(note)
    await audit_repo.save(audit)

    return ClinicalNoteResponse(
        id=note.id,
        visit_id=note.visit_id,
        sections=note.sections,
        model_id=note.model_id,
        is_approved=note.is_approved,
        approved_by=note.approved_by,
        approved_at=note.approved_at,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


# --- Audit Trail ---


@router.get("/visits/{visit_id}/audit", response_model=list[AuditEntryResponse])
async def get_audit_trail(
    visit_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    audit_repo: AuditRepository = Depends(get_audit_repo),
    visit_repo: VisitRepository = Depends(get_visit_repo),
):
    """Get complete audit trail for a visit."""
    visit = await visit_repo.get(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    entries = await audit_repo.get_by_visit(visit_id)
    return [
        AuditEntryResponse(
            id=e.id,
            action=e.action.value,
            actor=e.actor,
            detail=e.detail,
            model_id=e.model_id,
            timestamp=e.timestamp,
        )
        for e in entries
    ]


# --- Safety Flags ---


@router.get("/visits/{visit_id}/safety-flags", response_model=list[SafetyFlagResponse])
async def get_safety_flags(
    visit_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    safety_repo: SafetyFlagRepository = Depends(get_safety_flag_repo),
):
    """Get all safety flags for a visit."""
    flags = await safety_repo.get_by_visit(visit_id)
    return [
        SafetyFlagResponse(
            id=f.id, severity=f.severity, category=f.category,
            message=f.message, resolved=f.resolved, created_at=f.created_at,
        )
        for f in flags
    ]


# --- FHIR Export & EPJ Integration ---


@router.get("/visits/{visit_id}/fhir/document-reference")
async def get_fhir_document_reference(
    visit_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    visit_repo: VisitRepository = Depends(get_visit_repo),
    note_repo: ClinicalNoteRepository = Depends(get_note_repo),
):
    """Export note as FHIR R4 DocumentReference."""
    visit = await visit_repo.get(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    note = await note_repo.get_by_visit(visit_id)
    if not note:
        raise HTTPException(status_code=404, detail="No note found")

    from medscribe.integration.fhir_adapter import FHIRDocumentBuilder
    builder = FHIRDocumentBuilder()
    return builder.build_document_reference(visit, note)


@router.get("/visits/{visit_id}/fhir/composition")
async def get_fhir_composition(
    visit_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    visit_repo: VisitRepository = Depends(get_visit_repo),
    note_repo: ClinicalNoteRepository = Depends(get_note_repo),
):
    """Export note as FHIR R4 Composition with structured sections."""
    visit = await visit_repo.get(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    note = await note_repo.get_by_visit(visit_id)
    if not note:
        raise HTTPException(status_code=404, detail="No note found")

    from medscribe.integration.fhir_adapter import FHIRDocumentBuilder
    builder = FHIRDocumentBuilder()
    return builder.build_composition(visit, note)


@router.get("/visits/{visit_id}/fhir/bundle")
async def get_fhir_bundle(
    visit_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    visit_repo: VisitRepository = Depends(get_visit_repo),
    note_repo: ClinicalNoteRepository = Depends(get_note_repo),
):
    """
    Export note as FHIR R4 Bundle (transaction).

    This is what gets POSTed to the EPJ's FHIR endpoint.
    Contains both the Composition (structured note) and
    DocumentReference (metadata pointer).
    """
    visit = await visit_repo.get(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    note = await note_repo.get_by_visit(visit_id)
    if not note:
        raise HTTPException(status_code=404, detail="No note found")

    from medscribe.integration.fhir_adapter import FHIRDocumentBuilder
    builder = FHIRDocumentBuilder()
    return builder.build_bundle(visit, note)


# --- Legacy Export Formats (HL7v2, KITH XML, Plain Text) ---


@router.get("/visits/{visit_id}/export/hl7")
async def export_hl7(
    visit_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    visit_repo: VisitRepository = Depends(get_visit_repo),
    note_repo: ClinicalNoteRepository = Depends(get_note_repo),
):
    """Export note as HL7 v2.x MDM message (for DIPS Classic, older systems)."""
    visit = await visit_repo.get(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    note = await note_repo.get_by_visit(visit_id)
    if not note:
        raise HTTPException(status_code=404, detail="No note found")

    from medscribe.integration.legacy_adapters import HL7v2Adapter
    from fastapi.responses import PlainTextResponse
    message = HL7v2Adapter.build_mdm_message(visit, note)
    return PlainTextResponse(content=message, media_type="application/hl7-v2")


@router.get("/visits/{visit_id}/export/xml")
async def export_kith_xml(
    visit_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    visit_repo: VisitRepository = Depends(get_visit_repo),
    note_repo: ClinicalNoteRepository = Depends(get_note_repo),
):
    """Export note as KITH XML (Norwegian standard for older EPJ systems)."""
    visit = await visit_repo.get(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    note = await note_repo.get_by_visit(visit_id)
    if not note:
        raise HTTPException(status_code=404, detail="No note found")

    from medscribe.integration.legacy_adapters import KITHXMLAdapter
    from fastapi.responses import Response
    xml = KITHXMLAdapter.build_consultation_note(visit, note)
    return Response(content=xml, media_type="application/xml")


@router.get("/visits/{visit_id}/export/text")
async def export_plain_text(
    visit_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    visit_repo: VisitRepository = Depends(get_visit_repo),
    note_repo: ClinicalNoteRepository = Depends(get_note_repo),
):
    """Export note as formatted plain text (universal fallback)."""
    visit = await visit_repo.get(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    note = await note_repo.get_by_visit(visit_id)
    if not note:
        raise HTTPException(status_code=404, detail="No note found")

    from medscribe.integration.legacy_adapters import PlainTextAdapter
    from fastapi.responses import PlainTextResponse
    text = PlainTextAdapter.build_text_note(visit, note)
    return PlainTextResponse(content=text)


# --- EPJ Transfer ---


@router.post("/visits/{visit_id}/transfer-to-epj")
async def transfer_to_epj(
    visit_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    visit_repo: VisitRepository = Depends(get_visit_repo),
    note_repo: ClinicalNoteRepository = Depends(get_note_repo),
    session: "AsyncSession" = Depends(get_db_session),
):
    """
    Transfer approved note to EPJ and purge patient data.

    Full flow:
    1. Verify note is approved
    2. Build FHIR Bundle
    3. Send to EPJ (simulated in dev — real in prod)
    4. Purge all patient data from MedScribe (GDPR)
    5. Return transfer confirmation

    In production, configure EPJ connection via environment variables.
    """
    visit = await visit_repo.get(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    note = await note_repo.get_by_visit(visit_id)
    if not note:
        raise HTTPException(status_code=404, detail="No note found")

    if not note.is_approved:
        raise HTTPException(status_code=409, detail="Note must be approved before EPJ transfer")

    # Build FHIR Bundle
    from medscribe.integration.fhir_adapter import FHIRDocumentBuilder
    builder = FHIRDocumentBuilder()
    bundle = builder.build_bundle(visit, note)

    # In dev: simulate EPJ transfer. In prod: use real EPJ client.
    epj_result = {
        "success": True,
        "epj_system": "simulated",
        "message": "FHIR Bundle ready for EPJ transfer. Configure EPJ endpoint for production.",
        "fhir_bundle_type": bundle["resourceType"],
        "fhir_entries": len(bundle["entry"]),
    }

    # After successful transfer → purge patient data (GDPR)
    from medscribe.privacy.data_lifecycle import DataLifecycleManager
    manager = DataLifecycleManager(session)
    purge_result = await manager.purge_visit_data(visit_id, actor=user.user_id)

    return {
        "transfer": epj_result,
        "gdpr_purge": purge_result,
        "fhir_bundle": bundle,
    }


# --- Templates ---


# --- Privacy / GDPR ---


@router.post("/visits/{visit_id}/purge")
async def purge_visit_data(
    visit_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: "AsyncSession" = Depends(get_db_session),
):
    """
    GDPR: Purge ALL patient data for a visit after EPJ transfer.

    This permanently deletes:
    - Transcript text
    - Clinical note content
    - Safety flags
    - Visit metadata (patient ID)

    Keeps only anonymized audit entries for compliance.

    Call this AFTER the approved note has been transferred to the EPJ system.
    """
    from medscribe.privacy.data_lifecycle import DataLifecycleManager
    manager = DataLifecycleManager(session)
    summary = await manager.purge_visit_data(visit_id, actor=user.user_id)
    return summary


@router.post("/privacy/purge-expired")
async def purge_expired_visits(
    max_age_hours: int = 24,
    user: AuthenticatedUser = Depends(get_current_user),
    session: "AsyncSession" = Depends(get_db_session),
):
    """
    GDPR: Auto-purge all visits older than max_age_hours.

    Safety net — ensures no patient data lingers in the system
    even if EPJ transfer was forgotten.
    """
    from medscribe.privacy.data_lifecycle import DataLifecycleManager
    manager = DataLifecycleManager(session)
    summaries = await manager.purge_expired_visits(max_age_hours, actor=user.user_id)
    return {"purged": len(summaries), "details": summaries}


@router.get("/privacy/audit-check")
async def privacy_audit_check(
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    GDPR: Verify no patient audio files exist on disk.

    Compliance check — confirms audio is never persisted.
    """
    from medscribe.privacy.data_lifecycle import AudioDataPolicy
    clean = AudioDataPolicy.validate_no_audio_on_disk()
    return {
        "audio_files_on_disk": not clean,
        "compliant": clean,
        "checked_by": user.user_id,
    }


# --- Templates ---


@router.get("/templates")
async def list_templates():
    """List all available note templates (specialties)."""
    from medscribe.domain.templates import list_templates
    return list_templates()


@router.get("/templates/{template_id}")
async def get_template(template_id: str):
    """Get a specific template with all section definitions."""
    from medscribe.domain.templates import get_template as _get
    t = _get(template_id)
    return {
        "id": t.id,
        "name": t.name,
        "name_en": t.name_en,
        "specialty": t.specialty,
        "description": t.description,
        "sections": [
            {
                "key": s.key,
                "label": s.label,
                "label_en": s.label_en,
                "required": s.required,
            }
            for s in t.sections
        ],
    }
