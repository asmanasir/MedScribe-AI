from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from medscribe.api.auth import AuthenticatedUser, get_current_user, require_role
from medscribe.api.dependencies import get_db_session
from medscribe.verification import storage
from medscribe.verification.enums import DocumentType, JobStatus, JobType, VerificationStatus
from medscribe.verification.models import (
    Verification,
    VerificationAuditEntry,
    VerificationDocument,
    VerificationJob,
)
from medscribe.verification.repository import VerificationDocumentRepository, VerificationRepository
from medscribe.verification.service import VerificationService

router = APIRouter(prefix="/api/v1/verification", tags=["Verification"])


# --- Request / Response schemas ---

class SubmitVerificationRequest(BaseModel):
    full_name: str
    email: str


class ReviewDecisionRequest(BaseModel):
    action: str  # "approve" | "reject" | "start_review"
    rejection_reason: str | None = None


class VerificationResponse(BaseModel):
    id: UUID
    user_id: str
    full_name: str
    email: str
    status: VerificationStatus
    version: int
    rejection_reason: str | None
    reviewed_by: str | None
    reviewed_at: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_model(cls, v: Verification) -> VerificationResponse:
        return cls(
            id=v.id,
            user_id=v.user_id,
            full_name=v.full_name,
            email=v.email,
            status=v.status,
            version=v.version,
            rejection_reason=v.rejection_reason,
            reviewed_by=v.reviewed_by,
            reviewed_at=v.reviewed_at.isoformat() if v.reviewed_at else None,
            created_at=v.created_at.isoformat(),
            updated_at=v.updated_at.isoformat(),
        )


class JobResponse(BaseModel):
    id: UUID
    job_type: JobType
    status: JobStatus
    worker_id: str | None
    retry_count: int
    max_retries: int
    last_error: str | None
    started_at: str | None
    completed_at: str | None
    created_at: str

    @classmethod
    def from_model(cls, j: VerificationJob) -> JobResponse:
        return cls(
            id=j.id,
            job_type=j.job_type,
            status=j.status,
            worker_id=j.worker_id,
            retry_count=j.retry_count,
            max_retries=j.max_retries,
            last_error=j.last_error,
            started_at=j.started_at.isoformat() if j.started_at else None,
            completed_at=j.completed_at.isoformat() if j.completed_at else None,
            created_at=j.created_at.isoformat(),
        )


class DocumentResponse(BaseModel):
    id: UUID
    verification_id: UUID
    document_type: DocumentType
    file_name: str
    file_size_bytes: int
    file_hash: str
    ai_confidence: float
    uploaded_at: str
    uploaded_by: str

    @classmethod
    def from_model(cls, d: VerificationDocument) -> DocumentResponse:
        return cls(
            id=d.id,
            verification_id=d.verification_id,
            document_type=d.document_type,
            file_name=d.file_name,
            file_size_bytes=d.file_size_bytes,
            file_hash=d.file_hash,
            ai_confidence=d.ai_confidence,
            uploaded_at=d.uploaded_at.isoformat(),
            uploaded_by=d.uploaded_by,
        )


class AuditEntryResponse(BaseModel):
    id: UUID
    action: str
    actor: str
    detail: dict
    timestamp: str

    @classmethod
    def from_model(cls, e: VerificationAuditEntry) -> AuditEntryResponse:
        return cls(
            id=e.id,
            action=e.action.value,
            actor=e.actor,
            detail=e.detail,
            timestamp=e.timestamp.isoformat(),
        )


class VerificationDetailResponse(BaseModel):
    verification: VerificationResponse
    documents: list[DocumentResponse]
    jobs: list[JobResponse] = []


# --- User endpoints ---

@router.post("/", response_model=VerificationResponse, status_code=201)
async def submit_verification(
    body: SubmitVerificationRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Submit a new verification request."""
    svc = VerificationService(session)
    v = await svc.submit(user_id=user.user_id, full_name=body.full_name, email=body.email)
    return VerificationResponse.from_model(v)


@router.post("/{verification_id}/documents", response_model=DocumentResponse, status_code=201)
async def upload_document(
    verification_id: UUID,
    document_type: DocumentType = Form(...),
    file: UploadFile = ...,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Upload an ID or document file to a verification case."""
    svc = VerificationService(session)
    doc = await svc.upload_document(
        verification_id=verification_id,
        document_type=document_type,
        file=file,
        actor=user.user_id,
    )
    return DocumentResponse.from_model(doc)


@router.get("/", response_model=list[VerificationResponse])
async def list_my_verifications(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """List all verification cases for the authenticated user."""
    repo = VerificationRepository(session)
    verifications = await repo.list_by_user(user.user_id)
    return [VerificationResponse.from_model(v) for v in verifications]


@router.get("/{verification_id}", response_model=VerificationDetailResponse)
async def get_verification(
    verification_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get verification status and all uploaded documents."""
    svc = VerificationService(session)
    v, docs = await svc.get_with_documents(verification_id)
    jobs = await svc.get_jobs(verification_id)
    return VerificationDetailResponse(
        verification=VerificationResponse.from_model(v),
        documents=[DocumentResponse.from_model(d) for d in docs],
        jobs=[JobResponse.from_model(j) for j in jobs],
    )


@router.get("/{verification_id}/documents/{document_id}/download")
async def download_document(
    verification_id: UUID,
    document_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Download a verification document (admin or owner)."""
    doc_repo = VerificationDocumentRepository(session)
    docs = await doc_repo.list_by_verification(verification_id)
    doc = next((d for d in docs if d.id == document_id), None)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Load file from storage
    storage_path = storage.STORAGE_ROOT / str(verification_id) / f"{document_id}_{doc.file_name}"
    try:
        content = storage.load_document(str(storage_path))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found on disk.")

    # Determine media type from file name
    ext = doc.file_name.rsplit('.', 1)[-1].lower() if '.' in doc.file_name else ''
    media_type = {
        'pdf': 'application/pdf',
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'png': 'image/png',
        'webp': 'image/webp',
    }.get(ext, 'application/octet-stream')

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{doc.file_name}"'},
    )


@router.post("/{verification_id}/resubmit", response_model=VerificationResponse)
async def resubmit_verification(
    verification_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Resubmit a rejected verification."""
    svc = VerificationService(session)
    v = await svc.resubmit(verification_id, user.user_id)
    return VerificationResponse.from_model(v)


@router.get("/{verification_id}/audit", response_model=list[AuditEntryResponse])
async def get_audit_trail(
    verification_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get full audit trail for a verification case."""
    svc = VerificationService(session)
    entries = await svc.get_audit_trail(verification_id)
    return [AuditEntryResponse.from_model(e) for e in entries]


# --- Admin endpoints ---

@router.get("/admin/all", response_model=list[VerificationResponse])
async def admin_list_all(
    status: VerificationStatus | None = None,
    admin: AuthenticatedUser = Depends(require_role(["admin"])),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin: list all verification cases, optionally filtered by status."""
    repo = VerificationRepository(session)
    verifications = await repo.list_all(status=status)
    return [VerificationResponse.from_model(v) for v in verifications]


@router.put("/admin/{verification_id}/review", response_model=VerificationResponse)
async def admin_review(
    verification_id: UUID,
    body: ReviewDecisionRequest,
    admin: AuthenticatedUser = Depends(require_role(["admin"])),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin: start review, approve, or reject a verification case."""
    svc = VerificationService(session)

    if body.action == "start_review":
        v = await svc.start_review(verification_id, admin.user_id)
    elif body.action == "approve":
        v = await svc.approve(verification_id, admin.user_id)
    elif body.action == "reject":
        if not body.rejection_reason:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="rejection_reason is required.")
        v = await svc.reject(verification_id, admin.user_id, body.rejection_reason)
    else:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unknown action '{body.action}'.")

    return VerificationResponse.from_model(v)
