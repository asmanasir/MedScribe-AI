import { getAuthHeaders } from '../api';
import type {
  AuditEntry,
  DocumentType,
  VerificationDetail,
  VerificationRecord,
  VerificationStatus,
} from './types';

const BASE = '/api/v1/verification';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? 'Request failed');
  }
  return res.json();
}

export async function submitVerification(full_name: string, email: string): Promise<VerificationRecord> {
  const res = await fetch(`${BASE}/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ full_name, email }),
  });
  return handleResponse(res);
}

export async function uploadDocument(
  verificationId: string,
  documentType: DocumentType,
  file: File,
): Promise<VerificationRecord> {
  const form = new FormData();
  form.append('document_type', documentType);
  form.append('file', file);
  const res = await fetch(`${BASE}/${verificationId}/documents`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: form,
  });
  return handleResponse(res);
}

export async function openDocument(verificationId: string, documentId: string): Promise<void> {
  const res = await fetch(`${BASE}/${verificationId}/documents/${documentId}/download`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Could not load document');
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  window.open(url, '_blank');
}

export async function listMyVerifications(): Promise<VerificationRecord[]> {
  const res = await fetch(`${BASE}/`, { headers: getAuthHeaders() });
  return handleResponse(res);
}

export async function getVerification(id: string): Promise<VerificationDetail> {
  const res = await fetch(`${BASE}/${id}`, { headers: getAuthHeaders() });
  return handleResponse(res);
}

export async function getAuditTrail(id: string): Promise<AuditEntry[]> {
  const res = await fetch(`${BASE}/${id}/audit`, { headers: getAuthHeaders() });
  return handleResponse(res);
}

export async function resubmit(id: string): Promise<VerificationRecord> {
  const res = await fetch(`${BASE}/${id}/resubmit`, { method: 'POST', headers: getAuthHeaders() });
  return handleResponse(res);
}

// Admin
export async function adminListAll(status?: VerificationStatus): Promise<VerificationRecord[]> {
  const url = `${BASE}/admin/all${status ? `?status=${status}` : ''}`;
  const res = await fetch(url, { headers: getAuthHeaders() });
  return handleResponse(res);
}

export async function adminReview(
  id: string,
  action: 'start_review' | 'approve' | 'reject',
  rejection_reason?: string,
): Promise<VerificationRecord> {
  const res = await fetch(`${BASE}/admin/${id}/review`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ action, rejection_reason }),
  });
  return handleResponse(res);
}
