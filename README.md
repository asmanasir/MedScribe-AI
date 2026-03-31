# MedScribe AI

> Modular, production-oriented healthcare AI platform combining speech-to-text, RAG-based LLM processing, and agentic workflows, with 35+ API endpoints and privacy-first local deployment support.

Inspired by systems like [Aidn](https://aidn.no) and [Vidd Medical](https://viddmedical.com), this project explores combining clinical documentation, multi-step workflows, and agent-based automation in a single architecture.

---

## Architecture

```
                    ┌──────────────────────────┐
                    │   External Systems       │
                    │   (Aidn / EPJ / WebMed)  │
                    └────────────┬─────────────┘
                                 │ REST / WebSocket / FHIR
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                        API Gateway                               │
│   JWT Auth  ·  RBAC  ·  Rate Limiting  ·  TLS 1.3               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│   │   STT    │  │   LLM    │  │ Structur │  │   Agentic    │   │
│   │ Service  │  │ Service  │  │  -ing    │  │   Workflow   │   │
│   │          │  │          │  │          │  │   Engine     │   │
│   │ Whisper  │  │ Ollama   │  │ Templates│  │              │   │
│   │ (local)  │  │ (local)  │  │ 5 specs  │  │ 5 agents     │   │
│   └──────────┘  └──────────┘  └──────────┘  │ RAG Q&A      │   │
│                                              └──────────────┘   │
│                                                                  │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│   │ Workflow  │  │ Safety   │  │ Privacy  │  │ Observability│   │
│   │ Engine   │  │ Guard-   │  │ GDPR     │  │              │   │
│   │          │  │ rails    │  │ Lifecycle│  │ Metrics      │   │
│   │ FSM      │  │          │  │          │  │ Tracing      │   │
│   │ 8 states │  │ Halluci- │  │ Auto-    │  │ Logging      │   │
│   │ Audit    │  │ nation   │  │ purge    │  │              │   │
│   └──────────┘  └──────────┘  └──────────┘  └──────────────┘   │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │                  Integration Layer                        │  │
│   │  FHIR R4  ·  HL7v2  ·  KITH XML  ·  EPJ Bridge  ·  Events │
│   └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │                  Reliability Layer                        │  │
│   │  Retry + Backoff  ·  Fallback  ·  Circuit Breaker        │  │
│   └──────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│   Storage: PostgreSQL (prod) / SQLite (dev)                      │
│   Audit: Append-only log  ·  Model traceability                  │
└─────────────────────────────────────────────────────────────────┘
```

## Key Capabilities

### Clinical Documentation
- **Speech-to-text** — local Whisper (faster-whisper), chunked processing for long recordings
- **Real-time streaming** — WebSocket endpoint, text appears as doctor speaks
- **Structured notes** — AI converts transcript into clinical sections (SOAP-based)
- **5 specialty templates** — General Practice, Psychiatry, Surgery, Emergency, Pediatrics
- **Norwegian medical language** — domain-specific system prompts, ICD-10 hints, STT corrections

### Agentic Workflows
- **5 clinical agents** — Diagnosis coding, Follow-up tasks, Referral drafting, Care plan updates, Letter drafting
- **Preview before execution** — every agent action shown to clinician before running
- **Risk-based approval** — LOW (auto), MEDIUM (preview), HIGH (require explicit approval)
- **RAG patient Q&A** — ask questions about patient history with source citations

### Privacy & Compliance
- **Local-first** — STT and LLM run on-device by default, no cloud dependency
- **GDPR data lifecycle** — auto-purge patient data after EPJ transfer (24h safety net)
- **Audio never stored** — processed in memory only, temp files deleted immediately
- **Audit trail** — every action logged with actor, timestamp, model ID
- **CE/MDR framework** — device description, risk management, software lifecycle documentation

### Integration
- **FHIR R4** — DocumentReference, Composition, Bundle export
- **HL7 v2.x** — MDM messages for legacy hospital systems
- **KITH XML** — Norwegian standard for older EPJ systems
- **EPJ Bridge** — drop-in compatible with WebMed/TNW AI assistant protocol (same format as Vidd)
- **Event bus** — pub/sub for async integrations, Kafka-ready
- **Webhooks** — HMAC-signed notifications

### Production Readiness
- **Reliability** — retry with exponential backoff, fallback providers, circuit breaker
- **Observability** — structured JSON logging, metrics collection, correlation IDs
- **AI quality evaluation** — completeness, source fidelity, consistency scoring, drift detection
- **CI/CD** — GitHub Actions (lint, type check, test, Docker build, security scan)
- **Deployment** — Docker, Kubernetes (Azure AKS), on-premise, hybrid via Norsk Helsenett

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | Python 3.10+, FastAPI, Pydantic v2 |
| AI / ML | Python (faster-whisper, Ollama, OpenAI SDK) |
| Database | PostgreSQL (prod) / SQLite (dev), SQLAlchemy 2.0 async |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4 |
| Auth | JWT (HS256), RBAC |
| Cloud | Azure Norway East (AKS, Key Vault, PostgreSQL) |
| CI/CD | GitHub Actions, Docker |
| Observability | structlog (JSON), metrics collector |

## API Endpoints (35+)

| Category | Endpoints |
|----------|-----------|
| Auth | `POST /auth/token` |
| Visits | `POST /visits`, `GET /visits/{id}`, `GET /visits/{id}/status` |
| Pipeline | `POST /visits/{id}/transcribe`, `POST /visits/{id}/structure`, `POST /visits/{id}/process` |
| Review | `PUT /visits/{id}/note`, `POST /visits/{id}/approve` |
| Audit | `GET /visits/{id}/audit`, `GET /visits/{id}/safety-flags` |
| FHIR | `GET /visits/{id}/fhir/bundle`, `GET /visits/{id}/fhir/composition`, `GET /visits/{id}/fhir/document-reference` |
| Legacy | `GET /visits/{id}/export/hl7`, `GET /visits/{id}/export/xml`, `GET /visits/{id}/export/text` |
| EPJ Transfer | `POST /visits/{id}/transfer-to-epj` |
| Privacy | `POST /visits/{id}/purge`, `POST /privacy/purge-expired`, `GET /privacy/audit-check` |
| Agents | `POST /agent/plan`, `GET /agent/plan/{id}`, approve/skip/execute actions |
| RAG | `POST /agent/ask` |
| EPJ Bridge | `POST /epj/session/start`, status updates, note transfer, close |
| Templates | `GET /templates`, `GET /templates/{id}` |
| Streaming | `WebSocket /ws/transcribe` |
| Health | `GET /health` |

## Quick Start

```bash
# Clone and install
git clone <repo>
cd MedScribe-AI
python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[dev,local]"

# Configure
cp .env.example .env  # Edit with your settings

# Start Ollama (local LLM)
ollama pull llama3.2:1b

# Run
python -m medscribe            # Backend: http://localhost:8000
cd frontend && npm install && npm run dev  # Frontend: http://localhost:3000
```

## Testing

```bash
pytest tests/ -v               # 38 unit tests
pytest tests/ --cov=medscribe  # With coverage
ruff check src/                # Lint + security
```

## Project Structure

```
src/medscribe/
├── domain/          # Pure business objects (Visit, Note, Transcript)
├── services/        # AI processing (STT, LLM, structuring, Norwegian NLP)
├── agents/          # Agentic workflows (5 clinical agents + RAG)
├── workflow/        # State machine + orchestration
├── safety/          # Guardrails, hallucination detection
├── privacy/         # GDPR data lifecycle, auto-purge
├── storage/         # Database repositories, audit logging
├── api/             # FastAPI routes, auth, WebSocket, EPJ bridge
├── integration/     # FHIR, HL7, KITH XML, events, webhooks, EPJ bridge
├── observability.py # Metrics, tracing, structured logging
├── reliability.py   # Retry, fallback, circuit breaker
├── evaluation.py    # AI quality scoring, drift detection
└── config.py        # Centralized settings
```

## License

Proprietary. All rights reserved.
