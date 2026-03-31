# Risk Management — MedScribe AI
## Per ISO 14971 / MDR Annex I Chapter I

## 1. Risk Analysis

| ID | Hazard | Cause | Severity | Probability | Risk Level | Mitigation |
|----|--------|-------|----------|-------------|------------|------------|
| R01 | Incorrect transcription | Poor audio quality, accents, background noise | Medium | High | Medium | STT confidence scoring, human review required |
| R02 | Hallucinated content in structured note | LLM generates content not in transcript | High | Medium | High | [VERIFY] tagging, confidence thresholds, safety guardrails, mandatory human review |
| R03 | Omitted clinical information | LLM fails to extract important details | High | Medium | High | Section completeness checks, low-confidence warnings, human review |
| R04 | Wrong patient association | Incorrect visit/patient mapping | High | Low | Medium | Visit-level isolation, patient ID verification in UI |
| R05 | Unauthorized access to clinical data | Insufficient authentication/authorization | High | Low | Medium | JWT authentication, role-based access control, audit logging |
| R06 | Data breach / PHI exposure | Data transmitted to unauthorized cloud services | Critical | Low | High | Local processing mode (default), no external API calls in local mode, encryption in transit |
| R07 | System unavailability | Server crash, model loading failure | Low | Medium | Low | Health checks, graceful degradation, error handling |
| R08 | Approved note with errors | Clinician approves without adequate review | High | Low | Medium | UI design emphasizes review, cannot auto-approve, audit trail |

## 2. Risk Mitigations Implemented

### M01: Human-in-the-Loop (addresses R01, R02, R03, R08)
- **Implementation:** Workflow engine enforces REVIEW → APPROVED transition
- **Enforcement:** Programmatic — no API endpoint allows bypassing review
- **Verification:** Test `test_workflow.py::test_invalid_transition` proves CREATED→APPROVED is blocked

### M02: Safety Guardrails (addresses R02, R03)
- **Implementation:** `safety/guardrails.py` — automated checks on every output
- **Checks performed:**
  - Empty/incomplete note detection
  - Confidence threshold enforcement
  - [VERIFY] tag detection (LLM self-reported uncertainty)
  - Hallucination pattern detection (phone numbers, emails in clinical notes)
- **Verification:** 13 tests in `test_safety.py`

### M03: Audit Trail (addresses R04, R05, R08)
- **Implementation:** `storage/repositories.py` — AuditRepository (append-only)
- **Logged data:** Who, what, when, which AI model, input/output
- **Verification:** Every workflow transition produces an AuditEntry

### M04: Local Processing (addresses R06)
- **Implementation:** Default STT backend = local (faster-whisper), default LLM = local (Ollama)
- **Verification:** Health check confirms `data_sent_to_cloud=False` in logs
- **Configuration:** `.env` file explicitly sets LOCAL mode

### M05: Authentication & Authorization (addresses R05)
- **Implementation:** JWT tokens, role-based access control
- **Verification:** Tests in `test_auth.py`

## 3. Residual Risk Assessment
After mitigations, the highest residual risk is **R02 (hallucinated content)**
because LLM behavior cannot be fully controlled. This is mitigated to an
acceptable level by mandatory human review (M01) combined with automated
detection (M02). The user is informed of this risk in the Intended Purpose
and Instructions for Use.

## 4. Risk Acceptability
All identified risks are reduced to acceptable levels through the combination
of technical controls (guardrails, workflow enforcement) and organizational
controls (human review requirement, user training).
