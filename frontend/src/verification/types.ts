export type VerificationStatus = 'pending' | 'in_review' | 'approved' | 'rejected';

export type DocumentType =
  | 'national_id'
  | 'passport'
  | 'drivers_license'
  | 'certificate'
  | 'employment_doc'
  | 'other';

export interface VerificationRecord {
  id: string;
  user_id: string;
  full_name: string;
  email: string;
  status: VerificationStatus;
  version: number;
  rejection_reason: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface VerificationDocument {
  id: string;
  verification_id: string;
  document_type: DocumentType;
  file_name: string;
  file_size_bytes: number;
  file_hash: string;
  ai_confidence: number;
  uploaded_at: string;
  uploaded_by: string;
}

export type JobStatus = 'pending' | 'processing' | 'completed' | 'failed';
export type JobType = 'document_processing';

export interface VerificationJob {
  id: string;
  job_type: JobType;
  status: JobStatus;
  worker_id: string | null;
  retry_count: number;
  max_retries: number;
  last_error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface VerificationDetail {
  verification: VerificationRecord;
  documents: VerificationDocument[];
  jobs: VerificationJob[];
}

export interface AuditEntry {
  id: string;
  action: string;
  actor: string;
  detail: Record<string, unknown>;
  timestamp: string;
}
