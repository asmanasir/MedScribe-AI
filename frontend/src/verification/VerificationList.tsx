import { useEffect, useState } from 'react';
import { Clock, CheckCircle, XCircle, Search, RefreshCw, ChevronRight } from 'lucide-react';
import * as verificationApi from './api';
import type { VerificationRecord, VerificationStatus } from './types';

const STATUS_CONFIG: Record<VerificationStatus, { label: string; color: string; icon: typeof Clock }> = {
  pending:   { label: 'Pending',   color: 'bg-amber-100 text-amber-700',   icon: Clock },
  in_review: { label: 'In Review', color: 'bg-blue-100 text-blue-700',     icon: Search },
  approved:  { label: 'Approved',  color: 'bg-emerald-100 text-emerald-700', icon: CheckCircle },
  rejected:  { label: 'Rejected',  color: 'bg-red-100 text-red-700',       icon: XCircle },
};

interface Props {
  isAdmin?: boolean;
  onSelect: (id: string) => void;
  refreshKey?: number;
}

export default function VerificationList({ isAdmin = false, onSelect, refreshKey }: Props) {
  const [records, setRecords] = useState<VerificationRecord[]>([]);
  const [filter, setFilter] = useState<VerificationStatus | 'all'>('all');
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const data = isAdmin
        ? await verificationApi.adminListAll(filter === 'all' ? undefined : filter)
        : await verificationApi.listMyVerifications();
      setRecords(data);
    } catch {}
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [filter, refreshKey]);

  const counts = records.reduce((acc, r) => {
    acc[r.status] = (acc[r.status] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-3">
        {(['pending', 'in_review', 'approved', 'rejected'] as VerificationStatus[]).map(s => {
          const cfg = STATUS_CONFIG[s];
          const Icon = cfg.icon;
          return (
            <button key={s} onClick={() => setFilter(filter === s ? 'all' : s)}
              className={`bg-white rounded-xl border p-3 text-left transition-all hover:shadow-sm ${filter === s ? 'border-blue-400 shadow-sm' : 'border-slate-200'}`}>
              <div className="flex items-center justify-between mb-1">
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${cfg.color}`}>{cfg.label}</span>
                <Icon className="w-4 h-4 text-slate-400" />
              </div>
              <p className="text-2xl font-bold text-slate-800">{counts[s] ?? 0}</p>
            </button>
          );
        })}
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
          <h3 className="text-sm font-semibold text-slate-700">
            {isAdmin ? 'All Verifications' : 'My Verifications'}
            {filter !== 'all' && <span className="ml-2 text-xs text-blue-600">— {STATUS_CONFIG[filter].label}</span>}
          </h3>
          <button onClick={load} className="p-1.5 hover:bg-slate-100 rounded-lg transition-colors">
            <RefreshCw className={`w-3.5 h-3.5 text-slate-400 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12 text-slate-400 text-sm">Loading...</div>
        ) : records.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-400">
            <Search className="w-8 h-8 mb-2 opacity-30" />
            <p className="text-sm">No verifications found</p>
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50">
                {['Name', 'Email', 'Status', 'Submitted', isAdmin ? 'Reviewer' : ''].filter(Boolean).map(h => (
                  <th key={h} className="px-4 py-2.5 text-left text-[10px] font-bold text-slate-400 uppercase">{h}</th>
                ))}
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {records.map(r => {
                const cfg = STATUS_CONFIG[r.status];
                const Icon = cfg.icon;
                return (
                  <tr key={r.id} onClick={() => onSelect(r.id)}
                    className="border-b border-slate-50 last:border-0 hover:bg-slate-50 cursor-pointer transition-colors">
                    <td className="px-4 py-3 text-sm font-medium text-slate-800">{r.full_name}</td>
                    <td className="px-4 py-3 text-xs text-slate-500">{r.email}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ${cfg.color}`}>
                        <Icon className="w-3 h-3" /> {cfg.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-400">
                      {new Date(r.created_at).toLocaleDateString()}
                    </td>
                    {isAdmin && <td className="px-4 py-3 text-xs text-slate-400">{r.reviewed_by ?? '—'}</td>}
                    <td className="px-4 py-3">
                      <ChevronRight className="w-4 h-4 text-slate-300" />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
