import { useEffect, useRef, useState } from 'react';
import {
  Mic, MicOff, Square, Play, RotateCcw, Check, X, Pencil, ShieldCheck, Clock,
  Activity, LockKeyhole, FileText, AlertTriangle, SendHorizontal, MessagesSquare,
  Wifi, UserRound, ClipboardList, ChevronRight, Eye, SkipForward, CircleDot,
  Search, ListChecks,
} from 'lucide-react';
import { useRecorder } from './useRecorder';
import * as api from './api';

type View = 'journal' | 'agents' | 'chat';
type PipelineStep = 'idle' | 'recording' | 'transcribing' | 'structuring' | 'review' | 'approved';

export default function App() {
  // --- Core state ---
  const [health, setHealth] = useState<{ status: string; services: { llm: boolean; stt: boolean } } | null>(null);
  const [step, setStep] = useState<PipelineStep>('idle');
  const [view, setView] = useState<View>('journal');
  const [visitId, setVisitId] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<api.Transcript | null>(null);
  const [note, setNote] = useState<api.ClinicalNote | null>(null);
  const [audit, setAudit] = useState<api.AuditEntry[]>([]);
  const [editing, setEditing] = useState(false);
  const [sections, setSections] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [liveText, setLiveText] = useState('');

  // Visit info
  const [patientId, setPatientId] = useState('P-001');
  const [clinicianId, setClinicianId] = useState('DR001');

  // Templates
  const [templates, setTemplates] = useState<api.Template[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState('general_practice');
  const [templateSections, setTemplateSections] = useState<{ key: string; label: string; label_no: string }[]>([]);

  // Agent state
  const [agentPlan, setAgentPlan] = useState<api.AgentPlan | null>(null);
  const [agentLoading, setAgentLoading] = useState(false);

  // RAG chat
  const [chatMessages, setChatMessages] = useState<{ role: string; content: string; sources?: any[] }[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);

  // Ambient mode
  const [ambientMode, setAmbientMode] = useState(false);

  const recorder = useRecorder();
  const wsRef = useRef<WebSocket | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // --- Init ---
  useEffect(() => {
    api.getHealth().then(setHealth).catch(() => null);
    api.authenticate('DR001', import.meta.env.VITE_API_SECRET || 'dev-secret');
    api.getTemplates().then(setTemplates).catch(() => {});
  }, []);

  useEffect(() => {
    api.getTemplate(selectedTemplate).then((t) => {
      setTemplateSections(t.sections.map(s => ({ key: s.key, label: s.label_en, label_no: s.label })));
    }).catch(() => {});
  }, [selectedTemplate]);

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [chatMessages]);

  // --- Helpers ---
  const fmt = (s: number) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  const loadAudit = async (vid: string) => { setAudit(await api.getAudit(vid)); };

  // --- Recording ---
  const toggleRecord = async () => {
    if (!recorder.isRecording) {
      setError(null); setLiveText('');
      await recorder.start();
      setStep('recording');
      if (ambientMode) {
        try {
          const ws = api.createStreamingSocket('no');
          wsRef.current = ws;
          ws.onmessage = (e) => { const d = JSON.parse(e.data); if (d.text) setLiveText(d.text); };
        } catch {}
      }
    } else {
      recorder.stop();
      if (wsRef.current) { try { wsRef.current.send(JSON.stringify({ type: 'stop' })); } catch {} wsRef.current = null; }
    }
  };

  // --- Process Visit ---
  const processVisit = async () => {
    if (!recorder.audioBlob) return;
    setLoading(true); setError(null);
    try {
      const visit = await api.createVisit(patientId, clinicianId, { department: 'general', template: selectedTemplate });
      setVisitId(visit.id);
      setStep('transcribing');
      const t = await api.transcribeAudio(visit.id, recorder.audioBlob);
      setTranscript(t);
      setStep('structuring');
      const n = await api.structureVisit(visit.id);
      setNote(n); setSections(n.sections);
      setStep('review');
      await loadAudit(visit.id);
    } catch (e: any) {
      setError(e.message || 'Processing failed'); setStep('idle');
    } finally { setLoading(false); }
  };

  // --- Note Actions ---
  const handleApprove = async () => {
    if (!visitId) return;
    try {
      const n = await api.approveNote(visitId, clinicianId);
      setNote(n); setStep('approved'); setEditing(false); await loadAudit(visitId);
    } catch (e: any) { setError(e.message); }
  };
  const handleSaveEdits = async () => {
    if (!visitId) return;
    const n = await api.editNote(visitId, sections);
    setNote(n); setEditing(false); await loadAudit(visitId);
  };

  // --- Agent ---
  const runAgentPlan = async () => {
    if (!visitId) return;
    setAgentLoading(true); setView('agents');
    try {
      const plan = await api.createAgentPlan(visitId, { include_referral: true });
      setAgentPlan(plan);
    } catch (e: any) { setError(e.message); }
    finally { setAgentLoading(false); }
  };
  const handleActionApprove = async (actionId: string) => {
    if (!agentPlan) return;
    await api.approveAgentAction(agentPlan.id, actionId);
    const result = await api.executeAgentAction(agentPlan.id, actionId);
    setAgentPlan(await api.getAgentPlan(agentPlan.id));
  };
  const handleActionSkip = async (actionId: string) => {
    if (!agentPlan) return;
    await api.skipAgentAction(agentPlan.id, actionId);
    setAgentPlan(await api.getAgentPlan(agentPlan.id));
  };

  // --- Chat ---
  const sendChat = async () => {
    if (!chatInput.trim()) return;
    const q = chatInput; setChatInput('');
    setChatMessages(prev => [...prev, { role: 'user', content: q }]);
    setChatLoading(true);
    try {
      const ans = await api.askPatient(patientId, q);
      setChatMessages(prev => [...prev, { role: 'ai', content: ans.answer, sources: ans.sources }]);
    } catch { setChatMessages(prev => [...prev, { role: 'ai', content: 'Beklager, kunne ikke finne svar.' }]); }
    finally { setChatLoading(false); }
  };

  // --- Reset ---
  const resetAll = () => {
    setStep('idle'); setVisitId(null); setTranscript(null); setNote(null); setAudit([]);
    setEditing(false); setSections({}); setError(null); setLiveText('');
    setAgentPlan(null); setChatMessages([]); recorder.reset();
  };

  const stepOrder = ['idle','recording','transcribing','structuring','review','approved'];
  const currentIdx = stepOrder.indexOf(step);

  return (
    <div className="h-screen flex flex-col bg-slate-50 overflow-hidden">

      {/* ===== TOP BAR ===== */}
      <header className="bg-white border-b border-slate-200 px-4 py-2 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
            <span className="text-white font-black text-sm">M</span>
          </div>
          <div>
            <h1 className="text-sm font-bold text-slate-900 leading-none tracking-tight">MedScribe</h1>
            <p className="text-[10px] text-slate-400 font-medium">Clinical Documentation</p>
          </div>
        </div>

        {/* Pipeline steps */}
        <div className="flex items-center gap-1">
          {['Record','Transcribe','Structure','Review','Approved'].map((label, i) => {
            const done = currentIdx > i + 1;
            const active = currentIdx === i + 1;
            return (
              <div key={label} className="flex items-center">
                <div className={`px-2.5 py-1 rounded text-[10px] font-semibold transition-all ${
                  done ? 'bg-emerald-100 text-emerald-700' : active ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-400'
                }`}>
                  {done && '✓ '}{label}
                </div>
                {i < 4 && <ChevronRight className="w-3 h-3 text-slate-300 mx-0.5" />}
              </div>
            );
          })}
        </div>

        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-medium bg-emerald-50 text-emerald-700">
            <LockKeyhole className="w-3 h-3" /> Lokal
          </span>
          {health && (
            <span className={`flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-medium ${health.status === 'healthy' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${health.status === 'healthy' ? 'bg-emerald-500' : 'bg-amber-500'}`} />
              LLM {health.services.llm ? '✓' : '✗'} · STT {health.services.stt ? '✓' : '✗'}
            </span>
          )}
        </div>
      </header>

      {/* ===== MAIN LAYOUT ===== */}
      <div className="flex flex-1 overflow-hidden">

        {/* --- LEFT SIDEBAR: Recording + Visit --- */}
        <div className="w-80 bg-white border-r border-slate-200 flex flex-col shrink-0 overflow-y-auto">

          {/* Visit info */}
          <div className="p-3 border-b border-slate-100">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-[10px] font-bold text-slate-400 uppercase">Pasient</label>
                <input value={patientId} onChange={e => setPatientId(e.target.value)} disabled={step !== 'idle'}
                  className="w-full px-2 py-1.5 border border-slate-200 rounded text-xs" />
              </div>
              <div>
                <label className="block text-[10px] font-bold text-slate-400 uppercase">Behandler</label>
                <input value={clinicianId} onChange={e => setClinicianId(e.target.value)} disabled={step !== 'idle'}
                  className="w-full px-2 py-1.5 border border-slate-200 rounded text-xs" />
                <span className="text-[9px] text-slate-400 mt-0.5 block">Rolle: Lege</span>
              </div>
            </div>
            <div className="mt-2">
              <label className="block text-[10px] font-bold text-slate-400 uppercase">Mal</label>
              <select value={selectedTemplate} onChange={e => setSelectedTemplate(e.target.value)} disabled={step !== 'idle'}
                className="w-full px-2 py-1.5 border border-slate-200 rounded text-xs">
                {templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </div>
          </div>

          {/* Recording panel */}
          <div className="p-4 border-b border-slate-100 flex flex-col items-center">
            {/* Ambient toggle */}
            <label className="flex items-center gap-2 mb-3 cursor-pointer">
              <input type="checkbox" checked={ambientMode} onChange={e => setAmbientMode(e.target.checked)}
                disabled={step !== 'idle'} className="w-3.5 h-3.5 text-blue-600 rounded" />
              <Wifi className="w-3.5 h-3.5 text-slate-400" />
              <span className="text-xs text-slate-600">Ambient modus</span>
            </label>

            <button onClick={toggleRecord} disabled={loading || step === 'approved'}
              className={`w-16 h-16 rounded-full border-2 flex items-center justify-center transition-all ${
                recorder.isRecording
                  ? 'border-red-400 bg-red-50 shadow-lg shadow-red-200 animate-pulse'
                  : 'border-slate-200 bg-white hover:border-blue-400 hover:shadow-md'
              } disabled:opacity-40`}>
              {recorder.isRecording ? <Square className="w-6 h-6 text-red-500" /> : <Mic className="w-6 h-6 text-slate-600" />}
            </button>

            {recorder.isRecording && <div className="mt-2 text-xl font-bold text-red-500 tabular-nums">{fmt(recorder.seconds)}</div>}
            <p className="mt-1 text-[11px] text-slate-400">
              {recorder.isRecording ? 'Lytter...' : recorder.audioBlob ? `${fmt(recorder.seconds)} opptak klart` : 'Trykk for å starte'}
            </p>

            <div className="flex gap-2 mt-3 w-full">
              <button onClick={processVisit} disabled={!recorder.audioBlob || loading || (step !== 'idle' && step !== 'recording')}
                className="flex-1 px-3 py-2 bg-blue-600 text-white text-xs font-semibold rounded-lg hover:bg-blue-700 disabled:opacity-40 flex items-center justify-center gap-1.5">
                {loading ? <><div className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  {step === 'transcribing' ? 'Transkriberer...' : step === 'structuring' ? 'Strukturerer...' : 'Behandler...'}</>
                : <><Play className="w-3.5 h-3.5" /> Behandle</>}
              </button>
              <button onClick={resetAll} className="px-3 py-2 border border-slate-200 text-xs rounded-lg hover:bg-slate-50">
                <RotateCcw className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Live transcript (ambient) */}
          {(liveText || transcript) && (
            <div className="p-3 border-b border-slate-100 flex-1 overflow-y-auto">
              <div className="flex items-center gap-2 mb-2">
                <h3 className="text-[10px] font-bold text-slate-400 uppercase">Transkripsjon</h3>
                {transcript && <span className="text-[9px] text-slate-300">{transcript.model_id}</span>}
              </div>
              {liveText && !transcript && (
                <div className="bg-blue-50 rounded p-2 text-xs text-blue-900 leading-relaxed mb-2">
                  <div className="flex items-center gap-1 mb-1">
                    <div className="w-1.5 h-1.5 bg-red-500 rounded-full animate-pulse" />
                    <span className="text-[9px] font-bold text-blue-600 uppercase">Direkte</span>
                  </div>
                  {liveText}
                </div>
              )}
              {transcript && (
                <div className="bg-slate-50 rounded p-2 text-xs text-slate-700 leading-relaxed">
                  {transcript.raw_text || '(Ingen tale oppdaget)'}
                  <div className="flex gap-3 mt-2 text-[9px] text-slate-400">
                    <span>{transcript.language}</span>
                    <span>{transcript.duration_seconds.toFixed(0)}s</span>
                    <span>{(transcript.confidence * 100).toFixed(0)}%</span>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Audit trail */}
          {audit.length > 0 && (
            <div className="p-3 overflow-y-auto">
              <h3 className="text-[10px] font-bold text-slate-400 uppercase mb-2 flex items-center gap-1">
                <ShieldCheck className="w-3 h-3" /> Sporingslogg
              </h3>
              {audit.map(e => (
                <div key={e.id} className="flex justify-between py-1 border-b border-slate-50 last:border-0">
                  <span className="text-[10px] text-slate-600">{e.action}</span>
                  <span className="text-[9px] text-slate-400">{new Date(e.timestamp).toLocaleTimeString('no-NO', { hour: '2-digit', minute: '2-digit' })}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* --- CENTER: Main content area --- */}
        <div className="flex-1 flex flex-col overflow-hidden">

          {/* Tab bar */}
          <div className="bg-white border-b border-slate-200 px-4 flex items-center gap-1 shrink-0">
            {([
              { id: 'journal' as View, icon: FileText, label: 'Journal' },
              { id: 'agents' as View, icon: ClipboardList, label: 'AI-assistent' },
              { id: 'chat' as View, icon: MessagesSquare, label: 'Spør journal' },
            ]).map(tab => (
              <button key={tab.id} onClick={() => setView(tab.id)}
                className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium border-b-2 transition-colors ${
                  view === tab.id ? 'border-blue-600 text-blue-600' : 'border-transparent text-slate-500 hover:text-slate-700'
                }`}>
                <tab.icon className="w-3.5 h-3.5" /> {tab.label}
                {tab.id === 'agents' && agentPlan && (
                  <span className="ml-1 px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded-full text-[9px] font-bold">
                    {agentPlan.progress.completed}/{agentPlan.progress.total}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Error banner */}
          {error && (
            <div className="mx-4 mt-3 bg-red-50 border border-red-200 rounded-lg p-3 flex items-center gap-2 text-red-800 text-xs">
              <AlertTriangle className="w-4 h-4 shrink-0" /> {error}
              <button onClick={() => setError(null)} className="ml-auto text-red-400 hover:text-red-600"><X className="w-3.5 h-3.5" /></button>
            </div>
          )}

          {/* === JOURNAL VIEW === */}
          {view === 'journal' && (
            <div className="flex-1 overflow-y-auto p-4">
              {step === 'approved' && (
                <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-3 flex items-center gap-2 text-emerald-700 font-semibold text-sm mb-4">
                  <Check className="w-5 h-5" /> Notat godkjent og ferdigstilt
                </div>
              )}

              {note ? (
                <div className="space-y-3">
                  {/* Note header with metadata */}
                  <div className="bg-white rounded-lg border border-slate-200 p-4">
                    <div className="flex items-center justify-between mb-3">
                      <h2 className="text-sm font-bold text-slate-800">Konsultasjonsnotat</h2>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                        step === 'approved' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'
                      }`}>{step === 'approved' ? 'Godkjent' : 'Utkast — krever godkjenning'}</span>
                    </div>
                    <div className="grid grid-cols-4 gap-3 text-[10px]">
                      <div>
                        <span className="text-slate-400 block">Behandler</span>
                        <span className="font-semibold text-slate-700">{clinicianId}</span>
                        <span className="text-slate-400 ml-1">Lege</span>
                      </div>
                      <div>
                        <span className="text-slate-400 block">Pasient</span>
                        <span className="font-semibold text-slate-700">{patientId}</span>
                      </div>
                      <div>
                        <span className="text-slate-400 block">AI-modell</span>
                        <span className="font-mono text-slate-600">{note.model_id}</span>
                      </div>
                      <div>
                        <span className="text-slate-400 block">Generert</span>
                        <span className="text-slate-600">{new Date(note.created_at).toLocaleTimeString('no-NO', {hour:'2-digit',minute:'2-digit',second:'2-digit'})}</span>
                      </div>
                    </div>
                    {/* Confidence indicator */}
                    {transcript && (
                      <div className="mt-3 pt-3 border-t border-slate-100 flex items-center gap-4 text-[10px]">
                        <div className="flex items-center gap-1.5">
                          <span className="text-slate-400">STT-konfidens:</span>
                          <div className="w-16 h-1.5 bg-slate-200 rounded-full overflow-hidden">
                            <div className={`h-full rounded-full ${transcript.confidence > 0.7 ? 'bg-emerald-500' : transcript.confidence > 0.4 ? 'bg-amber-500' : 'bg-red-500'}`}
                              style={{width: `${Math.max(transcript.confidence * 100, 5)}%`}} />
                          </div>
                          <span className="font-semibold">{(transcript.confidence * 100).toFixed(0)}%</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-slate-400">Varighet:</span>
                          <span className="font-semibold">{transcript.duration_seconds.toFixed(0)}s</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-slate-400">Språk:</span>
                          <span className="font-semibold">{transcript.language === 'no' ? 'Norsk' : transcript.language}</span>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Note sections */}
                  {templateSections.map(({ key, label, label_no }) => {
                    const content = sections[key] || '';
                    const isEmpty = !content || content === 'Not documented.';
                    const hasUncertainty = content.includes('[VERIFY]') || content.includes('[VERIFISER]');
                    return (
                      <div key={key} className={`bg-white rounded-lg border overflow-hidden ${
                        hasUncertainty ? 'border-amber-300' : isEmpty ? 'border-slate-100' : 'border-slate-200'
                      }`}>
                        <div className="px-3 py-1.5 bg-slate-50 border-b border-slate-100 flex items-center justify-between">
                          <div>
                            <span className="text-[10px] font-bold text-blue-600 uppercase">{label_no}</span>
                            <span className="text-[10px] text-slate-400 ml-2">/ {label}</span>
                          </div>
                          {hasUncertainty && (
                            <span className="px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded text-[9px] font-medium">Usikker — verifiser</span>
                          )}
                        </div>
                        <textarea
                          value={content}
                          onChange={e => setSections(prev => ({ ...prev, [key]: e.target.value }))}
                          disabled={!editing || step === 'approved'}
                          rows={isEmpty ? 1 : 2}
                          className={`w-full px-3 py-2 text-sm leading-relaxed resize-y border-0 focus:ring-0 outline-none disabled:bg-white ${
                            isEmpty ? 'disabled:text-slate-300 italic' : 'disabled:text-slate-700'
                          }`}
                        />
                      </div>
                    );
                  })}

                  {/* Action buttons */}
                  <div className="flex gap-2 pt-2">
                    {step === 'review' && !editing && (
                      <>
                        <button onClick={handleApprove} className="px-4 py-2 bg-emerald-600 text-white text-xs font-semibold rounded-lg hover:bg-emerald-700 flex items-center gap-1.5">
                          <Check className="w-3.5 h-3.5" /> Godkjenn
                        </button>
                        <button onClick={() => setEditing(true)} className="px-4 py-2 border border-slate-200 text-xs font-medium rounded-lg hover:bg-slate-50 flex items-center gap-1.5">
                          <Pencil className="w-3.5 h-3.5" /> Rediger
                        </button>
                        <button onClick={runAgentPlan} disabled={agentLoading} className="px-4 py-2 bg-violet-600 text-white text-xs font-semibold rounded-lg hover:bg-violet-700 flex items-center gap-1.5">
                          <ListChecks className="w-3.5 h-3.5" /> AI-assistent
                        </button>
                      </>
                    )}
                    {editing && (
                      <>
                        <button onClick={handleSaveEdits} className="px-4 py-2 bg-blue-600 text-white text-xs font-semibold rounded-lg hover:bg-blue-700 flex items-center gap-1.5">
                          <Check className="w-3.5 h-3.5" /> Lagre
                        </button>
                        <button onClick={() => { setEditing(false); if (note) setSections(note.sections); }}
                          className="px-4 py-2 border border-slate-200 text-xs rounded-lg hover:bg-slate-50">Avbryt</button>
                      </>
                    )}
                  </div>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center h-full text-slate-400">
                  <FileText className="w-12 h-12 mb-3 opacity-30" />
                  <p className="text-sm">Ta opp en konsultasjon for å starte</p>
                  <p className="text-xs mt-1">Klinisk notat genereres automatisk</p>
                </div>
              )}
            </div>
          )}

          {/* === AGENTS VIEW === */}
          {view === 'agents' && (
            <div className="flex-1 overflow-y-auto p-4">
              {agentPlan ? (
                <div className="space-y-3">
                  <div className="flex items-center justify-between mb-2">
                    <h2 className="text-sm font-bold text-slate-800 flex items-center gap-2">
                      <ListChecks className="w-4 h-4 text-violet-600" /> {agentPlan.name}
                    </h2>
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-1.5 bg-slate-200 rounded-full overflow-hidden">
                        <div className="h-full bg-violet-600 rounded-full transition-all" style={{ width: `${agentPlan.progress.percent}%` }} />
                      </div>
                      <span className="text-[10px] text-slate-400">{agentPlan.progress.completed}/{agentPlan.progress.total}</span>
                    </div>
                  </div>

                  {agentPlan.actions.map(action => (
                    <div key={action.id} className={`bg-white rounded-lg border overflow-hidden ${
                      action.status === 'completed' ? 'border-emerald-200' :
                      action.status === 'skipped' ? 'border-slate-200 opacity-50' :
                      action.status === 'preview' ? 'border-violet-200' :
                      'border-slate-200'
                    }`}>
                      <div className="px-4 py-3 flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          {action.status === 'completed' ? <Check className="w-4 h-4 text-emerald-500" /> :
                           action.status === 'skipped' ? <SkipForward className="w-4 h-4 text-slate-400" /> :
                           action.status === 'preview' ? <Eye className="w-4 h-4 text-violet-500" /> :
                           <CircleDot className="w-4 h-4 text-amber-500" />}
                          <div>
                            <p className="text-xs font-semibold text-slate-800">{action.name}</p>
                            <p className="text-[10px] text-slate-400">{action.description}</p>
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <span className={`px-2 py-0.5 rounded text-[9px] font-medium ${
                            action.risk === 'low' ? 'bg-emerald-50 text-emerald-700' :
                            action.risk === 'medium' ? 'bg-amber-50 text-amber-700' :
                            'bg-red-50 text-red-700'
                          }`}>{action.risk}</span>
                          <span className={`px-2 py-0.5 rounded text-[9px] font-medium ${
                            action.status === 'completed' ? 'bg-emerald-50 text-emerald-700' :
                            action.status === 'preview' ? 'bg-violet-50 text-violet-700' :
                            'bg-slate-100 text-slate-500'
                          }`}>{action.status}</span>
                        </div>
                      </div>

                      {/* Preview content */}
                      {action.status === 'preview' && action.preview && (
                        <div className="px-4 py-3 bg-violet-50 border-t border-violet-100">
                          <p className="text-[10px] font-bold text-violet-600 uppercase mb-2">Forhåndsvisning</p>
                          <pre className="text-xs text-slate-700 whitespace-pre-wrap max-h-40 overflow-y-auto bg-white rounded p-2 border border-violet-100">
                            {typeof action.preview === 'object'
                              ? Object.entries(action.preview)
                                  .filter(([k]) => !['model_id','action'].includes(k))
                                  .map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v, null, 2)}`)
                                  .join('\n\n')
                              : String(action.preview)}
                          </pre>
                          <div className="flex gap-2 mt-3">
                            <button onClick={() => handleActionApprove(action.id)}
                              className="px-3 py-1.5 bg-emerald-600 text-white text-[11px] font-semibold rounded hover:bg-emerald-700 flex items-center gap-1">
                              <Check className="w-3 h-3" /> Godkjenn og utfør
                            </button>
                            <button onClick={() => handleActionSkip(action.id)}
                              className="px-3 py-1.5 border border-slate-200 text-[11px] rounded hover:bg-slate-50 flex items-center gap-1">
                              <SkipForward className="w-3 h-3" /> Hopp over
                            </button>
                          </div>
                        </div>
                      )}

                      {/* Output */}
                      {action.status === 'completed' && action.output && (
                        <div className="px-4 py-3 bg-emerald-50 border-t border-emerald-100">
                          <pre className="text-xs text-slate-700 whitespace-pre-wrap max-h-32 overflow-y-auto">
                            {JSON.stringify(action.output, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center h-full text-slate-400">
                  <ListChecks className="w-12 h-12 mb-3 opacity-30" />
                  <p className="text-sm">AI-assistent</p>
                  <p className="text-xs mt-1">Godkjenn notatet først, deretter klikk "AI-assistent"</p>
                  <p className="text-xs">for å få forslag til henvisning, oppfølging, diagnosekoder m.m.</p>
                </div>
              )}
            </div>
          )}

          {/* === CHAT VIEW (RAG) === */}
          {view === 'chat' && (
            <div className="flex-1 flex flex-col overflow-hidden">
              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {chatMessages.length === 0 && (
                  <div className="flex flex-col items-center justify-center h-full text-slate-400">
                    <Search className="w-12 h-12 mb-3 opacity-30" />
                    <p className="text-sm font-medium">Spør pasientjournalen</p>
                    <p className="text-xs mt-1">Still spørsmål om pasientens historikk</p>
                    <div className="mt-4 space-y-1.5">
                      {['Hvilke medisiner bruker pasienten?', 'Oppsummer siste konsultasjoner', 'Har pasienten noen allergier?'].map(q => (
                        <button key={q} onClick={() => { setChatInput(q); }} className="block w-full text-left px-3 py-2 bg-white border border-slate-200 rounded-lg text-xs text-slate-600 hover:border-blue-300 hover:bg-blue-50 transition-colors">
                          {q}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {chatMessages.map((msg, i) => (
                  <div key={i} className={`flex gap-2 ${msg.role === 'user' ? 'justify-end' : ''}`}>
                    {msg.role === 'ai' && (
                      <div className="w-7 h-7 bg-violet-100 rounded-full flex items-center justify-center shrink-0">
                        <span className="text-[10px] font-bold text-violet-600">AI</span>
                      </div>
                    )}
                    <div className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                      msg.role === 'user' ? 'bg-blue-600 text-white' : 'bg-white border border-slate-200 text-slate-700'
                    }`}>
                      <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                      {msg.sources && msg.sources.length > 0 && (
                        <div className="mt-2 pt-2 border-t border-slate-100">
                          <p className="text-[9px] font-bold text-slate-400 uppercase mb-1">Kilder</p>
                          {msg.sources.map((s: any, j: number) => (
                            <span key={j} className="inline-block mr-1 mb-1 px-1.5 py-0.5 bg-slate-50 rounded text-[9px] text-slate-500">
                              {new Date(s.date).toLocaleDateString('no-NO')} ({s.visit_id.slice(0, 6)})
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    {msg.role === 'user' && (
                      <div className="w-7 h-7 bg-blue-100 rounded-full flex items-center justify-center shrink-0">
                        <UserRound className="w-4 h-4 text-blue-600" />
                      </div>
                    )}
                  </div>
                ))}
                {chatLoading && (
                  <div className="flex gap-2">
                    <div className="w-7 h-7 bg-violet-100 rounded-full flex items-center justify-center">
                      <span className="text-[10px] font-bold text-violet-600">AI</span>
                    </div>
                    <div className="bg-white border border-slate-200 rounded-lg px-3 py-2">
                      <div className="flex gap-1"><div className="w-2 h-2 bg-slate-300 rounded-full animate-bounce" style={{animationDelay:'0ms'}} />
                        <div className="w-2 h-2 bg-slate-300 rounded-full animate-bounce" style={{animationDelay:'150ms'}} />
                        <div className="w-2 h-2 bg-slate-300 rounded-full animate-bounce" style={{animationDelay:'300ms'}} /></div>
                    </div>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>

              {/* Chat input */}
              <div className="p-3 border-t border-slate-200 bg-white">
                <div className="flex gap-2">
                  <input value={chatInput} onChange={e => setChatInput(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && sendChat()}
                    placeholder="Spør om pasientens historikk..."
                    className="flex-1 px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 outline-none" />
                  <button onClick={sendChat} disabled={!chatInput.trim() || chatLoading}
                    className="px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">
                    <SendHorizontal className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
