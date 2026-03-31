# Software Lifecycle — MedScribe AI
## Per IEC 62304 (Medical Device Software Lifecycle)

## 1. Software Safety Classification
**Class A** — No injury possible from software failure, because all outputs
require human review before clinical use.

## 2. Architecture Overview

```
┌──────────────────────┐
│   External System    │
│ (EPJ / Aidn / UI)    │
└─────────┬────────────┘
          │ REST API / WebSocket
          ↓
┌──────────────────────┐
│   API Gateway        │  ← Authentication, validation, versioning
│   (FastAPI + JWT)    │
└─────────┬────────────┘
          ↓
┌────────────────────────────────────┐
│        AI Processing Layer         │
│  STT (Whisper) │ LLM (pluggable)  │  ← Stateless, model-agnostic
│  Structuring   │ Norwegian NLP     │
└────────────────────────────────────┘
          ↓
┌──────────────────────┐
│  Workflow Engine     │  ← State machine, enforced transitions
│  (FSM)              │
└─────────┬────────────┘
          ↓
┌──────────────────────┐
│  Safety Guardrails   │  ← Automated output validation
└─────────┬────────────┘
          ↓
┌──────────────────────┐
│  Storage + Audit     │  ← Append-only audit log
│  (PostgreSQL/SQLite) │
└──────────────────────┘
```

## 3. SOUP (Software of Unknown Provenance)

| Component | Version | Purpose | Risk Mitigation |
|-----------|---------|---------|-----------------|
| faster-whisper | ≥1.0 | Speech-to-text | Confidence scoring, human review |
| Ollama/Llama | varies | Text structuring | Safety guardrails, human review |
| OpenAI GPT | varies | Text structuring (cloud option) | Same guardrails apply |
| FastAPI | ≥0.115 | HTTP framework | Well-tested, type-safe |
| SQLAlchemy | ≥2.0 | Database access | Parameterized queries (SQL injection prevention) |
| Pydantic | ≥2.9 | Data validation | Prevents invalid data at boundaries |

## 4. Testing Strategy

| Level | Tool | Coverage |
|-------|------|----------|
| Unit tests | pytest | Domain models, workflow engine, safety guardrails, auth |
| Integration tests | pytest + httpx | API endpoints, database operations |
| Security tests | ruff (bandit) | Static analysis for OWASP vulnerabilities |
| Type checking | mypy (strict) | Full type safety |

## 5. Configuration Management
- Source control: Git
- Dependency pinning: `pyproject.toml` with minimum versions
- Environment configuration: `.env` files (secrets never in code)
- Model versioning: Every AI output logs model ID and version

## 6. Problem Resolution
- All issues tracked in version control (Git)
- Audit trail captures every system action for post-incident analysis
- Safety flags automatically raised for suspicious outputs
