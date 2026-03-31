# MedScribe AI

A healthcare AI platform I built to explore how clinical documentation systems work in Norwegian healthcare. It combines speech-to-text, structured note generation, and agentic workflows into a single deployable service, with a focus on privacy-first local processing.

The goal was to understand the full stack — from audio capture to EPJ integration — and build something that could realistically plug into Norwegian healthcare infrastructure.

## What it does

A doctor records a consultation. The system transcribes the audio locally (Whisper), structures it into a clinical note using a local LLM (Ollama/Llama), and presents it for review. Nothing leaves the machine.

After approval, the note can be exported as FHIR R4, HL7v2, or KITH XML — whatever the target EPJ system speaks. Patient data is purged automatically after transfer.

Beyond basic documentation, the system includes agentic workflows — AI agents that can draft referral letters, suggest diagnosis codes, create follow-up tasks, and update care plans. Each action requires clinician approval before execution.

## Architecture overview

```
External Systems (EPJ / EHR)
         │
         │ REST / WebSocket / FHIR
         ▼
┌─────────────────────────────────────┐
│  API Gateway (FastAPI + JWT + RBAC) │
├─────────────────────────────────────┤
│  STT        LLM       Structuring  │
│  (Whisper)  (Ollama)  (Templates)  │
│                                     │
│  Workflow Engine    Safety Layer    │
│  (8-state FSM)     (Guardrails)    │
│                                     │
│  Agents      Privacy    Metrics    │
│  (5 types)   (GDPR)    (Logging)  │
├─────────────────────────────────────┤
│  Integration: FHIR · HL7 · KITH   │
│  Reliability: Retry · Fallback     │
├─────────────────────────────────────┤
│  PostgreSQL / SQLite + Audit Log   │
└─────────────────────────────────────┘
```

## Key design decisions

**Why local-first?** Norwegian healthcare requires patient data to stay within the institution. All AI processing (STT + LLM) runs on the hospital's own infrastructure. No external API calls by default.

**Why stateless?** MedScribe is a processing service, not a data store. It receives audio, processes it, returns structured output, and purges everything. The EPJ system is the source of truth.

**Why agentic?** Clinical documentation is more than transcription. After a consultation, the doctor may need to write a referral, update a care plan, order follow-up tests. The agent system proposes these actions with previews — the doctor decides what to execute.

**Why multiple export formats?** Norwegian healthcare runs on a mix of modern (FHIR R4) and legacy (HL7v2, KITH XML) systems. The integration layer handles the translation so the AI pipeline doesn't need to care about the target system.

## What I built

**Clinical pipeline** — Speech-to-text (faster-whisper, chunked for long recordings), structured note generation with 5 specialty templates (GP, Psychiatry, Surgery, Emergency, Pediatrics), Norwegian medical terminology corrections, and WebSocket streaming for real-time transcription.

**Agentic AI** — Five clinical agents: diagnosis coding (ICD-10), referral letter drafting, follow-up task creation, care plan updates, and patient letter generation. Each agent generates a preview that the clinician reviews before execution. Risk-based approval (low/medium/high).

**RAG patient Q&A** — Ask questions about a patient's history. The system retrieves relevant visit notes and answers with source citations. Runs locally.

**Safety** — Hallucination detection (phone numbers, emails, [VERIFY] tags), confidence scoring, empty note detection. Human-in-the-loop is enforced programmatically — notes cannot be auto-finalized.

**Privacy** — GDPR data lifecycle with auto-purge after EPJ transfer. Audio is never written to disk. 24-hour safety net deletes any lingering data.

**Integration** — FHIR R4 (DocumentReference, Composition, Bundle), HL7 v2.x MDM messages, KITH XML, and an EPJ bridge compatible with standard Norwegian EPJ AI assistant protocols.

**Reliability** — Retry with exponential backoff, fallback providers, circuit breaker pattern.

**Evaluation** — AI quality scoring (completeness, source fidelity, consistency), drift detection, regression testing against golden datasets.

## Tech stack

- **Backend:** Python 3.10, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async)
- **AI:** faster-whisper (local STT), Ollama (local LLM). Optional cloud provider support, disabled by default in clinical deployments
- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS
- **Database:** PostgreSQL (production), SQLite (development)
- **Auth:** JWT with role-based access control
- **Observability:** structlog (structured JSON), OpenTelemetry-ready, Prometheus-compatible metrics
- **Deployment:** Docker, Kubernetes (Azure Norway East), on-premise support
- **CI/CD:** GitHub Actions (lint, type check, tests, Docker build, security scan)

## Running locally

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,local]"
cp .env.example .env

# Start Ollama
ollama pull llama3.2:3b

# Backend
python -m medscribe

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

Backend runs on `http://localhost:8000`, frontend on `http://localhost:3000`.

## Tests

```bash
pytest tests/ -v          # 38 tests
ruff check src/           # Lint + security scan
```

## API surface

35+ endpoints organized into: authentication, visit pipeline (transcribe/structure/approve), FHIR export, legacy export (HL7/XML/text), EPJ bridge, agentic workflows, RAG Q&A, privacy controls, templates, health checks, and WebSocket streaming.

Full endpoint list available at `http://localhost:8000/docs` (Swagger UI).

## Project structure

```
src/medscribe/
├── domain/        # Business objects (Visit, Note, Transcript, Templates)
├── services/      # AI processing (STT, LLM, structuring, Norwegian NLP)
├── agents/        # Agentic workflows + RAG
├── workflow/      # State machine + orchestration
├── safety/        # Guardrails, hallucination detection
├── privacy/       # GDPR lifecycle, auto-purge
├── storage/       # Repositories, audit logging
├── api/           # Routes, auth, WebSocket, EPJ bridge
├── integration/   # FHIR, HL7, KITH, events, webhooks
└── *.py           # Observability, reliability, evaluation, config
```

## Compliance

The `compliance/` directory contains CE/MDR documentation framework: device description, intended purpose, risk management (ISO 14971), and software lifecycle (IEC 62304).

## Performance

Designed for sub-2s structuring latency on GPU hardware (NVIDIA T4/A100). On CPU, structuring takes 15-30s depending on transcript length. Audio processing uses chunked transcription to handle recordings of any length without memory issues.

---

Built by Asma Hafeez
