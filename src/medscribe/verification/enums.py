from __future__ import annotations

from enum import Enum


class VerificationStatus(str, Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentType(str, Enum):
    NATIONAL_ID = "national_id"
    PASSPORT = "passport"
    DRIVERS_LICENSE = "drivers_license"
    CERTIFICATE = "certificate"
    EMPLOYMENT_DOC = "employment_doc"
    OTHER = "other"


class VerificationAction(str, Enum):
    SUBMITTED = "verification_submitted"
    DOCUMENT_UPLOADED = "document_uploaded"
    REVIEW_STARTED = "review_started"
    APPROVED = "verification_approved"
    REJECTED = "verification_rejected"
    RESUBMITTED = "verification_resubmitted"


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(str, Enum):
    DOCUMENT_PROCESSING = "document_processing"  # OCR + AI confidence scoring
