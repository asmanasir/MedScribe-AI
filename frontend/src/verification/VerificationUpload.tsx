import { useRef, useState } from 'react';
import { Upload, FileText, X, CheckCircle, AlertCircle } from 'lucide-react';
import * as verificationApi from './api';
import type { DocumentType, VerificationRecord } from './types';

const DOCUMENT_TYPES: { value: DocumentType; label: string }[] = [
  { value: 'national_id', label: 'National ID' },
  { value: 'passport', label: 'Passport' },
  { value: 'drivers_license', label: "Driver's License" },
  { value: 'certificate', label: 'Certificate' },
  { value: 'employment_doc', label: 'Employment Document' },
  { value: 'other', label: 'Other' },
];

interface Props {
  onSubmitted: (v: VerificationRecord) => void;
  authReady?: boolean;
}

export default function VerificationUpload({ onSubmitted, authReady = false }: Props) {
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [docType, setDocType] = useState<DocumentType>('national_id');
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFile = (f: File) => {
    const allowed = ['image/jpeg', 'image/png', 'image/webp', 'application/pdf'];
    if (!allowed.includes(f.type)) {
      setError('Only PDF, JPEG, PNG, or WEBP files are accepted.');
      return;
    }
    if (f.size > 10 * 1024 * 1024) {
      setError('File must be under 10 MB.');
      return;
    }
    setFile(f);
    setError(null);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) handleFile(dropped);
  };

  const handleSubmit = async () => {
    if (!fullName || !email || !file) {
      setError('Please fill in all fields and select a file.');
      return;
    }
    if (!authReady) {
      setError('Still connecting to server — wait a moment and try again.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const v = await verificationApi.submitVerification(fullName, email);
      await verificationApi.uploadDocument(v.id, docType, file);
      onSubmitted(v);
    } catch (e: any) {
      setError(e.message || 'Submission failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-lg mx-auto space-y-4">
      <div className="bg-white rounded-xl border border-slate-200 p-6 space-y-4">
        <div>
          <h2 className="text-base font-bold text-slate-800">Submit Verification</h2>
          <p className="text-xs text-slate-400 mt-0.5">Upload your identity document to verify your account.</p>
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-xs text-red-700">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" /> {error}
            <button onClick={() => setError(null)} className="ml-auto"><X className="w-3.5 h-3.5" /></button>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-[10px] font-bold text-slate-400 uppercase mb-1">Full Name</label>
            <input value={fullName} onChange={e => setFullName(e.target.value)}
              placeholder="John Doe"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 outline-none" />
          </div>
          <div>
            <label className="block text-[10px] font-bold text-slate-400 uppercase mb-1">Email</label>
            <input value={email} onChange={e => setEmail(e.target.value)}
              type="email" placeholder="you@example.com"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 outline-none" />
          </div>
        </div>

        <div>
          <label className="block text-[10px] font-bold text-slate-400 uppercase mb-1">Document Type</label>
          <select value={docType} onChange={e => setDocType(e.target.value as DocumentType)}
            className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 outline-none">
            {DOCUMENT_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>

        {/* Drop zone */}
        <div
          onDragOver={e => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => fileRef.current?.click()}
          className={`border-2 border-dashed rounded-xl p-8 flex flex-col items-center cursor-pointer transition-colors ${
            dragging ? 'border-blue-400 bg-blue-50' : file ? 'border-emerald-300 bg-emerald-50' : 'border-slate-200 hover:border-blue-300 hover:bg-slate-50'
          }`}
        >
          <input ref={fileRef} type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" className="hidden"
            onChange={e => e.target.files?.[0] && handleFile(e.target.files[0])} />

          {file ? (
            <>
              <CheckCircle className="w-10 h-10 text-emerald-500 mb-2" />
              <p className="text-sm font-semibold text-emerald-700">{file.name}</p>
              <p className="text-xs text-slate-400 mt-1">{(file.size / 1024).toFixed(0)} KB</p>
              <button onClick={e => { e.stopPropagation(); setFile(null); }}
                className="mt-2 text-xs text-slate-400 hover:text-red-500 flex items-center gap-1">
                <X className="w-3 h-3" /> Remove
              </button>
            </>
          ) : (
            <>
              <Upload className="w-10 h-10 text-slate-300 mb-2" />
              <p className="text-sm font-medium text-slate-600">Click to upload or drag and drop</p>
              <p className="text-xs text-slate-400 mt-1">PDF, JPEG, PNG, WEBP — max 10 MB</p>
            </>
          )}
        </div>

        <button onClick={handleSubmit} disabled={loading || !file || !fullName || !email || !authReady}
          className="w-full py-2.5 bg-blue-600 text-white text-sm font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-40 flex items-center justify-center gap-2">
          {!authReady
            ? <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Connecting...</>
            : loading
            ? <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Submitting...</>
            : <><FileText className="w-4 h-4" /> Submit for Verification</>}
        </button>
      </div>
    </div>
  );
}
