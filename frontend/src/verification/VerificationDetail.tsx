import { useEffect, useState } from 'react';
import {
  ArrowLeft, CheckCircle, XCircle, Clock, FileText,
  ShieldCheck, AlertCircle, RotateCcw, Cpu, RefreshCw,
  GitBranch, Layers, BrainCircuit, Server, Activity, ExternalLink,
} from 'lucide-react';
import * as verificationApi from './api';
import type { AuditEntry, VerificationDetail, VerificationJob, VerificationStatus } from './types';

const STATUS_COLOR: Record<VerificationStatus, string> = {
  pending:   'bg-amber-100 text-amber-700 border-amber-200',
  in_review: 'bg-blue-100 text-blue-700 border-blue-200',
  approved:  'bg-emerald-100 text-emerald-700 border-emerald-200',
  rejected:  'bg-red-100 text-red-700 border-red-200',
};

interface Props {
  verificationId: string;
  isAdmin?: boolean;
  onBack: () => void;
  onUpdated?: () => void;
}

export default function VerificationDetail({ verificationId, isAdmin = false, onBack, onUpdated }: Props) {
  const [detail, setDetail] = useState<VerificationDetail | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [showRejectForm, setShowRejectForm] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [d, a] = await Promise.all([
        verificationApi.getVerification(verificationId),
        verificationApi.getAuditTrail(verificationId),
      ]);
      setDetail(d);
      setAudit(a);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [verificationId]);

  const adminAction = async (action: 'start_review' | 'approve' | 'reject') => {
    if (action === 'reject' && !rejectReason.trim()) {
      setError('Please enter a rejection reason.'); return;
    }
    setActionLoading(true); setError(null);
    try {
      await verificationApi.adminReview(verificationId, action, rejectReason || undefined);
      await load();
      setShowRejectForm(false);
      setRejectReason('');
      onUpdated?.();
    } catch (e: any) { setError(e.message); }
    finally { setActionLoading(false); }
  };

  const handleResubmit = async () => {
    setActionLoading(true); setError(null);
    try {
      await verificationApi.resubmit(verificationId);
      await load(); onUpdated?.();
    } catch (e: any) { setError(e.message); }
    finally { setActionLoading(false); }
  };

  if (loading) return <div className="flex items-center justify-center py-20 text-slate-400 text-sm">Loading...</div>;
  if (!detail) return null;

  const { verification: v, documents } = detail;
  const statusCfg = STATUS_COLOR[v.status];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="p-2 hover:bg-slate-100 rounded-lg transition-colors">
          <ArrowLeft className="w-4 h-4 text-slate-500" />
        </button>
        <div className="flex-1">
          <h2 className="text-base font-bold text-slate-800">{v.full_name}</h2>
          <p className="text-xs text-slate-400">{v.email}</p>
        </div>
        <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${statusCfg}`}>
          {v.status === 'approved' && <CheckCircle className="w-3.5 h-3.5" />}
          {v.status === 'rejected' && <XCircle className="w-3.5 h-3.5" />}
          {v.status === 'pending' && <Clock className="w-3.5 h-3.5" />}
          {v.status === 'in_review' && <ShieldCheck className="w-3.5 h-3.5" />}
          {v.status.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase())}
        </span>
      </div>

      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-xs text-red-700">
          <AlertCircle className="w-3.5 h-3.5 shrink-0" /> {error}
        </div>
      )}

      {/* Rejection reason banner */}
      {v.status === 'rejected' && v.rejection_reason && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4">
          <p className="text-xs font-bold text-red-600 uppercase mb-1">Rejection Reason</p>
          <p className="text-sm text-red-800">{v.rejection_reason}</p>
          {!isAdmin && (
            <button onClick={handleResubmit} disabled={actionLoading}
              className="mt-3 flex items-center gap-1.5 text-xs font-semibold text-red-700 hover:text-red-900">
              <RotateCcw className="w-3.5 h-3.5" /> Retry my verification
            </button>
          )}
        </div>
      )}

      {/* System info bar — version + locking */}
      <div className="bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 flex flex-wrap gap-6 text-xs">
        <div className="flex items-center gap-2">
          <GitBranch className="w-3.5 h-3.5 text-slate-400" />
          <span className="text-slate-500">Version</span>
          <span className="font-mono font-bold text-slate-700">v{v.version}</span>
          <span className="text-slate-400 text-[10px]">(optimistic lock)</span>
        </div>
        <div className="flex items-center gap-2">
          <Layers className="w-3.5 h-3.5 text-slate-400" />
          <span className="text-slate-500">Last updated</span>
          <span className="font-semibold text-slate-700">{new Date(v.updated_at).toLocaleString()}</span>
        </div>
        <div className="flex items-center gap-2">
          <ShieldCheck className="w-3.5 h-3.5 text-slate-400" />
          <span className="text-slate-500">Reviewed by</span>
          <span className="font-semibold text-slate-700">{v.reviewed_by ?? '—'}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-slate-500">Case ID</span>
          <span className="font-mono text-slate-500 text-[10px]">{v.id.slice(0, 8)}…</span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {/* Documents + Jobs panel */}
        <div className="col-span-2 space-y-3">
          <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-100 flex items-center gap-2">
              <FileText className="w-4 h-4 text-slate-400" />
              <h3 className="text-sm font-semibold text-slate-700">Documents</h3>
              <span className="ml-auto text-[10px] text-slate-400">{documents.length} file{documents.length !== 1 ? 's' : ''}</span>
            </div>
            {documents.length === 0 ? (
              <div className="p-6 text-center text-slate-400 text-xs">No documents uploaded yet.</div>
            ) : (
              <div className="divide-y divide-slate-50">
                {documents.map(doc => (
                  <div key={doc.id} className="px-4 py-3 flex items-center gap-3">
                    <div className="w-9 h-9 bg-blue-50 rounded-lg flex items-center justify-center shrink-0">
                      <FileText className="w-4 h-4 text-blue-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-slate-800 truncate">{doc.file_name}</p>
                      <p className="text-[10px] text-slate-400">
                        {doc.document_type.replace('_', ' ')} · {(doc.file_size_bytes / 1024).toFixed(0)} KB
                      </p>
                    </div>
                    <button
                      onClick={() => verificationApi.openDocument(v.id, doc.id).catch(() => null)}
                      className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold text-blue-600 hover:text-blue-800 hover:bg-blue-50 rounded-lg transition-colors shrink-0"
                    >
                      <ExternalLink className="w-3 h-3" /> View
                    </button>
                    <div className="text-right">
                      <div className="flex items-center gap-1.5 justify-end mb-1">
                        <span className="text-[10px] text-slate-400">AI Confidence</span>
                        <span className={`text-[10px] font-bold ${doc.ai_confidence > 0.7 ? 'text-emerald-600' : doc.ai_confidence > 0.4 ? 'text-amber-600' : 'text-red-500'}`}>
                          {doc.ai_confidence > 0 ? `${(doc.ai_confidence * 100).toFixed(0)}%` : '—'}
                        </span>
                      </div>
                      <div className="w-20 h-1 bg-slate-200 rounded-full overflow-hidden">
                        <div className={`h-full rounded-full ${doc.ai_confidence > 0.7 ? 'bg-emerald-500' : doc.ai_confidence > 0.4 ? 'bg-amber-400' : 'bg-slate-300'}`}
                          style={{ width: `${Math.max(doc.ai_confidence * 100, 3)}%` }} />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Job Tracking panel */}
          {detail.jobs.length > 0 && (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-100 flex items-center gap-2">
                <Server className="w-4 h-4 text-slate-400" />
                <h3 className="text-sm font-semibold text-slate-700">Background Jobs</h3>
                <span className="ml-auto text-[10px] text-slate-400">{detail.jobs.length} job{detail.jobs.length !== 1 ? 's' : ''}</span>
              </div>
              <div className="divide-y divide-slate-50">
                {detail.jobs.map(job => {
                  const jobColor =
                    job.status === 'completed' ? 'text-emerald-600 bg-emerald-50 border-emerald-200' :
                    job.status === 'processing' ? 'text-blue-600 bg-blue-50 border-blue-200' :
                    job.status === 'failed'     ? 'text-red-600 bg-red-50 border-red-200' :
                                                  'text-amber-600 bg-amber-50 border-amber-200';
                  return (
                    <div key={job.id} className="px-4 py-3 space-y-2">
                      <div className="flex items-center gap-2">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border ${jobColor}`}>
                          {job.status === 'completed' && <CheckCircle className="w-3 h-3" />}
                          {job.status === 'failed'    && <XCircle className="w-3 h-3" />}
                          {job.status === 'processing' && <RefreshCw className="w-3 h-3 animate-spin" />}
                          {job.status === 'pending'   && <Clock className="w-3 h-3" />}
                          {job.status.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase())}
                        </span>
                        <span className="text-[10px] text-slate-400 font-mono">{job.job_type.replace('_', ' ')}</span>
                        <span className="ml-auto text-[10px] text-slate-300 font-mono">{job.id.slice(0, 8)}…</span>
                      </div>
                      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[10px]">
                        <div className="flex items-center gap-1.5 text-slate-500">
                          <Cpu className="w-3 h-3 text-slate-300" />
                          <span className="text-slate-400">Worker</span>
                          <span className="font-mono font-semibold text-slate-600 truncate">{job.worker_id ?? '—'}</span>
                        </div>
                        <div className="flex items-center gap-1.5 text-slate-500">
                          <Activity className="w-3 h-3 text-slate-300" />
                          <span className="text-slate-400">Retries</span>
                          <span className={`font-semibold ${job.retry_count > 0 ? 'text-amber-600' : 'text-slate-600'}`}>
                            {job.retry_count} / {job.max_retries}
                          </span>
                        </div>
                        {job.started_at && (
                          <div className="text-slate-400">
                            Started: <span className="text-slate-600">{new Date(job.started_at).toLocaleTimeString()}</span>
                          </div>
                        )}
                        {job.completed_at && (
                          <div className="text-slate-400">
                            Finished: <span className="text-slate-600">{new Date(job.completed_at).toLocaleTimeString()}</span>
                          </div>
                        )}
                      </div>
                      {job.last_error && (
                        <div className="flex items-start gap-1.5 bg-red-50 border border-red-100 rounded-lg px-2.5 py-1.5">
                          <AlertCircle className="w-3 h-3 text-red-400 mt-0.5 shrink-0" />
                          <p className="text-[10px] text-red-700 font-mono">{job.last_error}</p>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* AI Validation panel */}
          {documents.some(d => d.ai_confidence > 0) && (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-100 flex items-center gap-2">
                <BrainCircuit className="w-4 h-4 text-slate-400" />
                <h3 className="text-sm font-semibold text-slate-700">AI Validation</h3>
                <span className="ml-auto text-[10px] text-slate-400">doc-classifier-v1 · threshold 70%</span>
              </div>
              <div className="divide-y divide-slate-50">
                {documents.filter(d => d.ai_confidence > 0).map(doc => {
                  const pct = Math.round(doc.ai_confidence * 100);
                  const passed = doc.ai_confidence >= 0.70;
                  return (
                    <div key={doc.id} className="px-4 py-3 space-y-2">
                      <div className="flex items-center gap-2">
                        <p className="text-xs font-medium text-slate-700 truncate flex-1">{doc.file_name}</p>
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${passed ? 'text-emerald-700 bg-emerald-50 border-emerald-200' : 'text-red-700 bg-red-50 border-red-200'}`}>
                          {passed ? '✓ Passed' : '✗ Below threshold'}
                        </span>
                      </div>
                      {/* Confidence bar with 70% threshold marker */}
                      <div className="relative">
                        <div className="w-full h-2 bg-slate-100 rounded-full overflow-visible">
                          <div
                            className={`h-full rounded-full transition-all ${passed ? 'bg-emerald-500' : 'bg-red-400'}`}
                            style={{ width: `${pct}%` }}
                          />
                          {/* 70% threshold line */}
                          <div className="absolute top-0 bottom-0 w-px bg-slate-400" style={{ left: '70%' }} />
                        </div>
                        <div className="absolute -top-4 text-[9px] text-slate-400 -translate-x-1/2" style={{ left: '70%' }}>70%</div>
                      </div>
                      <div className="flex items-center justify-between text-[10px]">
                        <span className="text-slate-500">Confidence score</span>
                        <span className={`font-bold text-sm ${passed ? 'text-emerald-600' : 'text-red-500'}`}>{pct}%</span>
                      </div>
                      <div className="flex items-center gap-1.5 text-[10px]">
                        <BrainCircuit className="w-3 h-3 text-slate-300" />
                        <span className="text-slate-400">AI suggestion:</span>
                        <span className={`font-semibold ${passed ? 'text-emerald-600' : 'text-amber-600'}`}>
                          {passed ? 'Approve' : 'Manual review required'}
                        </span>
                        {v.status === 'approved' && (
                          <span className="ml-auto text-slate-400">Human decision: <span className="font-semibold text-emerald-600">Approved</span></span>
                        )}
                        {v.status === 'rejected' && (
                          <span className="ml-auto text-slate-400">Human decision: <span className="font-semibold text-red-600">Rejected</span></span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Admin actions */}
          {isAdmin && (
            <div className="bg-white rounded-xl border border-slate-200 p-4 space-y-3">
              <h3 className="text-sm font-semibold text-slate-700">Review Decision</h3>
              <div className="flex gap-2">
                {v.status === 'pending' && (
                  <button onClick={() => adminAction('start_review')} disabled={actionLoading}
                    className="px-4 py-2 bg-blue-600 text-white text-xs font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-40 flex items-center gap-1.5">
                    <ShieldCheck className="w-3.5 h-3.5" /> Start Review
                  </button>
                )}
                {v.status === 'in_review' && (
                  <>
                    <button onClick={() => adminAction('approve')} disabled={actionLoading}
                      className="px-4 py-2 bg-emerald-600 text-white text-xs font-semibold rounded-lg hover:bg-emerald-700 disabled:opacity-40 flex items-center gap-1.5">
                      <CheckCircle className="w-3.5 h-3.5" /> Approve
                    </button>
                    <button onClick={() => setShowRejectForm(s => !s)} disabled={actionLoading}
                      className="px-4 py-2 bg-red-50 text-red-700 border border-red-200 text-xs font-semibold rounded-lg hover:bg-red-100 disabled:opacity-40 flex items-center gap-1.5">
                      <XCircle className="w-3.5 h-3.5" /> Reject
                    </button>
                  </>
                )}
              </div>
              {showRejectForm && (
                <div className="space-y-2">
                  <textarea value={rejectReason} onChange={e => setRejectReason(e.target.value)}
                    placeholder="Enter reason for rejection..."
                    rows={2}
                    className="w-full px-3 py-2 border border-red-200 rounded-lg text-sm focus:ring-2 focus:ring-red-400 outline-none resize-none" />
                  <button onClick={() => adminAction('reject')} disabled={!rejectReason.trim() || actionLoading}
                    className="px-4 py-2 bg-red-600 text-white text-xs font-semibold rounded-lg hover:bg-red-700 disabled:opacity-40">
                    Confirm Rejection
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Audit trail */}
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-100 flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-slate-400" />
            <h3 className="text-sm font-semibold text-slate-700">Audit Trail</h3>
          </div>
          <div className="p-3 space-y-1 max-h-96 overflow-y-auto">
            {audit.length === 0 ? (
              <p className="text-xs text-slate-400 text-center py-4">No events yet.</p>
            ) : (
              audit.map((e, i) => (
                <div key={e.id} className="relative pl-5">
                  {i < audit.length - 1 && (
                    <div className="absolute left-1.5 top-4 bottom-0 w-px bg-slate-100" />
                  )}
                  <div className="absolute left-0 top-1.5 w-3 h-3 rounded-full bg-blue-100 border-2 border-blue-400" />
                  <div className="pb-3">
                    <p className="text-[11px] font-semibold text-slate-700">
                      {e.action.replace('verification_', '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                    </p>
                    <p className="text-[10px] text-slate-400">{e.actor}</p>
                    <p className="text-[10px] text-slate-300">
                      {new Date(e.timestamp).toLocaleString()}
                    </p>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
