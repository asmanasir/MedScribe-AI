/**
 * MedScribe API client — typed, clean, single source of truth.
 */

const BASE = import.meta.env.VITE_API_URL || '';  // Empty = same origin (dev proxy), or full URL for production

let token: string | null = null;

function headers(json = false): HeadersInit {
  const h: Record<string, string> = {};
  if (token) h['Authorization'] = `Bearer ${token}`;
  if (json) h['Content-Type'] = 'application/json';
  return h;
}

// --- Auth ---
export async function authenticate(clientId: string, secret: string): Promise<string> {
  const resp = await fetch(`${BASE}/api/v1/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id: clientId, client_secret: secret, role: 'clinician' }),
  });
  const data = await resp.json();
  token = data.access_token;
  return token!;
}

// --- Health ---
export async function getHealth(): Promise<{
  status: string;
  services: { llm: boolean; stt: boolean };
}> {
  const resp = await fetch(`${BASE}/health`);
  return resp.json();
}

// --- Visit ---
export interface Visit {
  id: string;
  patient_id: string;
  clinician_id: string;
  status: string;
  allowed_transitions: string[];
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export async function createVisit(patientId: string, clinicianId: string, metadata: Record<string, unknown> = {}): Promise<Visit> {
  const resp = await fetch(`${BASE}/api/v1/visits`, {
    method: 'POST',
    headers: headers(true),
    body: JSON.stringify({ patient_id: patientId, clinician_id: clinicianId, metadata }),
  });
  return resp.json();
}

export async function getVisit(visitId: string): Promise<Visit> {
  const resp = await fetch(`${BASE}/api/v1/visits/${visitId}`, { headers: headers() });
  return resp.json();
}

// --- Transcribe ---
export interface Transcript {
  id: string;
  visit_id: string;
  raw_text: string;
  language: string;
  model_id: string;
  confidence: number;
  duration_seconds: number;
  segment_count: number;
  created_at: string;
}

export async function transcribeAudio(visitId: string, audioBlob: Blob): Promise<Transcript> {
  const form = new FormData();
  form.append('audio', audioBlob, 'recording.webm');
  const resp = await fetch(`${BASE}/api/v1/visits/${visitId}/transcribe`, {
    method: 'POST',
    headers: headers(),
    body: form,
  });
  if (!resp.ok) throw new Error((await resp.json()).detail || 'Transcription failed');
  return resp.json();
}

// --- Structure ---
export interface ClinicalNote {
  id: string;
  visit_id: string;
  sections: Record<string, string>;
  model_id: string;
  is_approved: boolean;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
}

export async function structureVisit(visitId: string): Promise<ClinicalNote> {
  const resp = await fetch(`${BASE}/api/v1/visits/${visitId}/structure`, {
    method: 'POST',
    headers: headers(),
  });
  if (!resp.ok) throw new Error((await resp.json()).detail || 'Structuring failed');
  return resp.json();
}

// --- Note Actions ---
export async function editNote(visitId: string, sections: Record<string, string>): Promise<ClinicalNote> {
  const resp = await fetch(`${BASE}/api/v1/visits/${visitId}/note`, {
    method: 'PUT',
    headers: headers(true),
    body: JSON.stringify({ sections }),
  });
  return resp.json();
}

export async function approveNote(visitId: string, approvedBy: string): Promise<ClinicalNote> {
  const resp = await fetch(`${BASE}/api/v1/visits/${visitId}/approve`, {
    method: 'POST',
    headers: headers(true),
    body: JSON.stringify({ approved_by: approvedBy }),
  });
  if (!resp.ok) throw new Error((await resp.json()).detail || 'Approval failed');
  return resp.json();
}

// --- Audit ---
export interface AuditEntry {
  id: string;
  action: string;
  actor: string;
  detail: Record<string, unknown>;
  model_id: string | null;
  timestamp: string;
}

export async function getAudit(visitId: string): Promise<AuditEntry[]> {
  const resp = await fetch(`${BASE}/api/v1/visits/${visitId}/audit`, { headers: headers() });
  return resp.json();
}

// --- Templates ---
export interface Template {
  id: string;
  name: string;
  name_en: string;
  specialty: string;
  description: string;
  section_count: number;
}

export interface TemplateDetail {
  id: string;
  name: string;
  name_en: string;
  specialty: string;
  description: string;
  sections: { key: string; label: string; label_en: string; required: boolean }[];
}

export async function getTemplates(): Promise<Template[]> {
  const resp = await fetch(`${BASE}/api/v1/templates`, { headers: headers() });
  return resp.json();
}

export async function getTemplate(id: string): Promise<TemplateDetail> {
  const resp = await fetch(`${BASE}/api/v1/templates/${id}`, { headers: headers() });
  return resp.json();
}

// --- Streaming WebSocket ---
export function createStreamingSocket(language: string = 'no'): WebSocket {
  const wsBase = window.location.origin.replace('http', 'ws');
  return new WebSocket(`${wsBase}/api/v1/ws/transcribe?language=${language}`);
}

// --- Agent / Agentic AI ---
export interface AgentPlan {
  id: string;
  visit_id: string | null;
  name: string;
  description: string;
  status: string;
  progress: { total: number; completed: number; percent: number };
  actions: AgentActionItem[];
}

export interface AgentActionItem {
  id: string;
  agent_id: string;
  name: string;
  description: string;
  risk: string;
  status: string;
  preview: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error: string | null;
}

export async function createAgentPlan(visitId: string, opts: { include_referral?: boolean; include_letter?: boolean; letter_type?: string } = {}): Promise<AgentPlan> {
  const resp = await fetch(`${BASE}/api/v1/agent/plan`, {
    method: 'POST', headers: headers(true),
    body: JSON.stringify({ visit_id: visitId, ...opts }),
  });
  if (!resp.ok) throw new Error((await resp.json()).detail || 'Plan failed');
  return resp.json();
}

export async function getAgentPlan(planId: string): Promise<AgentPlan> {
  const resp = await fetch(`${BASE}/api/v1/agent/plan/${planId}`, { headers: headers() });
  return resp.json();
}

export async function approveAgentAction(planId: string, actionId: string): Promise<void> {
  await fetch(`${BASE}/api/v1/agent/plan/${planId}/actions/${actionId}/approve`, { method: 'POST', headers: headers() });
}

export async function skipAgentAction(planId: string, actionId: string): Promise<void> {
  await fetch(`${BASE}/api/v1/agent/plan/${planId}/actions/${actionId}/skip`, { method: 'POST', headers: headers() });
}

export async function executeAgentAction(planId: string, actionId: string): Promise<AgentActionItem> {
  const resp = await fetch(`${BASE}/api/v1/agent/plan/${planId}/actions/${actionId}/execute`, { method: 'POST', headers: headers() });
  return resp.json();
}

// --- RAG / Patient Q&A ---
export interface RAGAnswer {
  answer: string;
  sources: { visit_id: string; date: string; sections: string[] }[];
  context_used: string;
  model_id: string;
}

export async function askPatient(patientId: string, question: string): Promise<RAGAnswer> {
  const resp = await fetch(`${BASE}/api/v1/agent/ask`, {
    method: 'POST', headers: headers(true),
    body: JSON.stringify({ patient_id: patientId, question }),
  });
  if (!resp.ok) throw new Error((await resp.json()).detail || 'Q&A failed');
  return resp.json();
}
