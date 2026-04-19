# Verification Module — Technical Documentation

Identity and document verification system built as a **fully isolated domain module** inside MedScribe AI. Designed to KYC/KYP (Know Your Patient / Know Your Provider) standards for healthcare onboarding workflows.

---

## Overview

The verification module lets a user submit identity documents (passport, national ID, driver's license, certificates, employment docs) for review. An AI pipeline scores the document automatically. A human admin then makes the final approval or rejection decision.

```
User submits docs → AI scores confidence → Admin reviews → Approved / Rejected
                         (88% confidence)    (View file, decide)
```

---

## Screenshots

| Screen | Description |
|--------|-------------|
| `screenshots/submit.png` | Submit Verification form — drag & drop, document type selection |
| `screenshots/detail_pending.png` | Detail view — Version v1, Background Jobs panel, AI Validation panel |
| `screenshots/detail_rejected.png` | Rejected case — rejection reason banner, audit trail, Human decision: Rejected |
| `screenshots/list_admin.png` | All Verifications list — status summary cards (Pending/In Review/Approved/Rejected), reviewer column |

---

## What the AI Does

When a document is uploaded, a background job runs automatically:

1. **File validation** — MIME type check (PDF, JPEG, PNG, WEBP only), 10 MB size limit, SHA-256 hash computed for integrity
2. **Document classification** (`doc-classifier-v1`) — simulates OCR + ML confidence scoring
3. **Confidence score** — a value between 0.0–1.0 is assigned to each document
4. **Threshold check** — documents scoring ≥ 0.70 are marked **Passed**; below 0.70 flagged for **Manual review required**
5. **AI suggestion** — either `Approve` or `Manual review required`, shown to the admin alongside the confidence bar

> In production, step 2–4 would call a real OCR engine (Azure Document Intelligence / AWS Textract) and an ML classifier trained on document types.

The AI **never makes the final decision**. It only provides a confidence signal to assist the human reviewer.

---

## What the Human Admin Does

After the AI scores the document, the admin:

1. **Views the document** — clicks "View" to open the file in a new tab (PDF/image rendered inline)
2. **Reads the AI suggestion** — confidence score, threshold result, AI recommendation
3. **Checks the audit trail** — sees who submitted, when, and all prior actions
4. **Starts Review** — transitions case from `Pending → In Review` (locks it for review)
5. **Approves or Rejects**:
   - **Approve** → status becomes `Approved`, `reviewed_by` and `reviewed_at` stamped
   - **Reject** → must provide a written rejection reason; user is notified and can resubmit

The AI suggestion may say "Approve" but the human can still reject (visible in the UI as "AI suggestion: Approve / Human decision: Rejected"). This override is always audited.

---

## State Machine

```
PENDING ──► IN_REVIEW ──► APPROVED  (terminal)
                    └───► REJECTED ──► PENDING  (user resubmits)
```

Invalid transitions are blocked at the service layer with HTTP 409 Conflict. No route or repository ever bypasses this.

---

## Optimistic Locking (Concurrency)

Every verification record has a `version` integer. On each state change:

- `version` increments by 1
- If two admins try to update the same case simultaneously, the second write detects a version mismatch and returns `409 Conflict: "Record was modified by another request. Please refresh and retry."`

This prevents silent data corruption under concurrent admin reviews without requiring `SELECT FOR UPDATE` (compatible with both SQLite dev and PostgreSQL prod).

---

## Tech Stack

### Backend

| Layer | Technology | Why |
|-------|-----------|-----|
| API framework | **FastAPI** (Python 3.11+) | Async, OpenAPI-first, native Pydantic validation |
| ORM | **SQLAlchemy 2.0 async** | Async sessions, repository pattern, vendor-agnostic |
| Database (dev) | **SQLite** via `aiosqlite` | Zero-config local dev, same schema as prod |
| Database (prod) | **PostgreSQL** | ACID, concurrent writes, partitioning for audit log |
| Auth | **JWT (HS256)** via `python-jose` | Stateless, RBAC via `role` claim, `require_role(["admin"])` dependency |
| File storage | **Local filesystem** (swappable) | `storage.py` abstraction — replace with Azure Blob / S3 via config |
| Background jobs | **In-process simulation** | `asyncio.sleep(0)` yield point; production: Celery + Redis |
| Settings | **pydantic-settings** | Type-safe env vars, `.env` file, fail-fast validation |
| Logging | **structlog** | Structured JSON logs, machine-parseable in prod |

### Frontend

| Layer | Technology | Why |
|-------|-----------|-----|
| Framework | **React 18** + TypeScript | Typed components, Vite dev server |
| Styling | **Tailwind CSS v4** | Utility-first, consistent design tokens |
| Icons | **Lucide React** | Consistent icon set |
| Build tool | **Vite** | HMR, ESM proxy to FastAPI backend |
| API client | Typed `fetch` wrappers in `verification/api.ts` | No dependency on axios/react-query, matches backend schemas exactly |

---

## Module Structure

```
src/medscribe/verification/
├── enums.py          # VerificationStatus, DocumentType, VerificationAction, JobStatus, JobType
├── models.py         # Domain models (Pydantic) — Verification, VerificationDocument, VerificationJob, AuditEntry
├── repository.py     # Data access layer — 4 repository classes, pure DB I/O, no business logic
├── service.py        # All business logic — state machine, optimistic locking, AI job simulation
├── security.py       # File validation — MIME type allowlist, 10 MB limit, extension check
├── storage.py        # File I/O abstraction — local filesystem, interface for cloud swap
└── __init__.py

src/medscribe/api/
└── verification_routes.py   # 10 REST endpoints, Pydantic request/response schemas

frontend/src/verification/
├── types.ts              # TypeScript interfaces matching backend schemas exactly
├── api.ts                # Typed fetch wrappers for all endpoints
├── VerificationUpload.tsx # Submit form — drag & drop, file validation, auth guard
├── VerificationList.tsx  # Admin/user list — status summary cards, filterable table
└── VerificationDetail.tsx # Detail view — all panels below
```

---

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/verification/` | Any | Submit new verification case |
| `POST` | `/api/v1/verification/{id}/documents` | Owner | Upload identity document |
| `GET` | `/api/v1/verification/` | Any | List own verifications |
| `GET` | `/api/v1/verification/{id}` | Any | Get detail (verification + docs + jobs) |
| `GET` | `/api/v1/verification/{id}/documents/{doc_id}/download` | Any | Download/view uploaded file |
| `GET` | `/api/v1/verification/{id}/audit` | Any | Full audit trail |
| `POST` | `/api/v1/verification/{id}/resubmit` | Owner | Resubmit after rejection |
| `GET` | `/api/v1/verification/admin/all` | `admin` | List all cases (optional status filter) |
| `PUT` | `/api/v1/verification/admin/{id}/review` | `admin` | Start review / approve / reject |

---

## Detail View Panels

### System Info Bar
Shows `version` (optimistic lock counter), last updated timestamp, `reviewed_by`, and truncated case ID.

### Documents Panel
File name, type, size. **View** button — fetches file with Authorization header, creates a blob URL, opens in a new browser tab. AI confidence mini-bar per document.

### Background Jobs Panel
Only shown when jobs exist. Displays: job status badge (Completed/Processing/Failed/Pending), `worker_id` (e.g. `worker-asmakhan`), retry count (`0 / 3`), started/finished timestamps, last error if failed.

### AI Validation Panel
Per-document confidence bar with a **70% threshold marker line**. Shows: confidence %, Passed/Below threshold badge, AI suggestion, and Human decision (once admin has acted). Demonstrates where AI and human diverge.

### Review Decision Panel (Admin only)
- **Pending** state: "Start Review" button
- **In Review** state: "Approve" and "Reject" buttons; reject requires a written reason
- Hidden for non-admin users

### Audit Trail
Append-only timeline: Submitted → Document Uploaded → Review Started → Approved/Rejected. Each entry shows actor (user ID) and timestamp. Immutable — stored via `session.add()` not `session.merge()`.

---

## Security

| Concern | Implementation |
|---------|---------------|
| File type validation | MIME type allowlist (`image/jpeg`, `image/png`, `image/webp`, `application/pdf`) + extension check |
| File size | 10 MB hard limit, returns HTTP 413 |
| File integrity | SHA-256 hash stored on upload, verifiable on re-download |
| Access control | JWT Bearer token required on all endpoints; admin endpoints use `require_role(["admin"])` |
| Audit trail | Append-only table, no updates/deletes allowed by the repository |
| GDPR purge | `delete_verification_files(verification_id)` + DB cascade for full data removal |

---

## Running Locally

```bash
# Backend
cd MedScribe-AI
.venv\Scripts\activate
$env:PYTHONPATH="src"
uvicorn medscribe.api.app:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm run dev
```

Open `http://localhost:3000` → click **Verification** tab.

**Auth is handled automatically** — the app authenticates as `DR001` with role `admin` on startup. The button shows "Connecting..." until auth completes, then "Submit for Verification".

---

## Architecture Design — Patterns and Reasoning

### Domain Isolation (Bounded Context)

The verification module is built as a **completely separate domain** from the clinical module. It has its own enums, domain models, repositories, service, routes, and database tables. No file inside `verification/` imports anything from the clinical domain.

This was a deliberate architectural decision based on **Domain-Driven Design (DDD)**. The reasoning:

- Clinical workflows (visits, transcripts, clinical notes) evolve on a different cycle than identity verification
- A bug in verification logic cannot crash the clinical pipeline
- The module can be extracted into its own microservice later with zero code changes — you only change the transport layer (HTTP calls instead of function calls)
- Teams can own each domain independently without merge conflicts

The cost of this decision is some duplication. For example, `VerificationAuditEntry` and the clinical `AuditEntry` are structurally similar but deliberately kept separate. The alternative — a shared audit model — creates hidden coupling that causes breaking changes when one domain needs to evolve the structure.

---

### Repository Pattern (Separation of DB from Business Logic)

Every database table has a dedicated repository class (`VerificationRepository`, `VerificationDocumentRepository`, etc.). The service layer never touches SQLAlchemy directly — it only calls repository methods.

**Why this matters:**
- `service.py` contains zero SQLAlchemy imports. It is testable without a database.
- Switching from SQLite to PostgreSQL, or from SQLAlchemy to a different ORM, only changes the repository files — the business logic is untouched.
- The domain models (in `models.py`) are plain Python dataclasses. The database rows (in `database.py`) are SQLAlchemy mapped classes. These are two different things that happen to represent the same data. This is sometimes called the **Anti-Corruption Layer**.

The tradeoff: more files, more mapping code. A simpler CRUD app would just use SQLAlchemy models directly in routes. But in a healthcare system where compliance audits may require you to swap storage backends, this separation is worth it.

---

### State Machine (Explicit Transitions)

Instead of letting any code set `verification.status = anything`, all transitions go through a single dictionary:

```python
_TRANSITIONS = {
    PENDING:   {IN_REVIEW},
    IN_REVIEW: {APPROVED, REJECTED},
    REJECTED:  {PENDING},
    APPROVED:  set(),  # terminal
}
```

If code tries an invalid transition (e.g. PENDING → APPROVED, skipping review), it raises HTTP 409 immediately. The system is structurally incapable of reaching an invalid state, not just documented to avoid it.

**Why explicit over implicit:** In many systems, state is just a string field and business rules are comments ("don't call approve() on a pending case"). Comments rot. Code enforces. When a new developer joins and adds a shortcut endpoint, the state machine blocks it automatically.

The tradeoff: it requires discipline to never set `v.status` directly outside the service. This is enforced by convention — no linter rule prevents it. In V2, making `status` a private field with a `transition_to()` method would enforce this at the language level.

---

### Optimistic Locking (Version Field)

Rather than using database-level `SELECT FOR UPDATE` (pessimistic locking), we use a `version` integer that increments on every write. Two concurrent writes to the same record produce a version mismatch, and the second one fails with 409.

**Why optimistic over pessimistic:**
- `SELECT FOR UPDATE` is PostgreSQL-specific syntax. SQLite doesn't support it. Our dev/prod parity would break.
- Pessimistic locks hold a database connection open for the duration of a user action (potentially seconds), which doesn't scale.
- In practice, two admins reviewing the same case simultaneously is rare. Optimistic locking costs nothing in the happy path and only adds a version check on writes.

The tradeoff: optimistic locking requires the client to retry on conflict. Currently the frontend just shows an error message. A better UX would auto-refresh the detail view and let the admin try again.

---

### AI as Signal, Not Decision-Maker

The AI confidence score is advisory only. The system is designed so that:

1. AI can be wrong and the human can override
2. The override is always recorded (audit trail shows "AI: Approve / Human: Rejected")
3. No approval can happen without a human explicitly clicking Approve

This is a **human-in-the-loop** design. In healthcare, this is not just good practice — it is often a regulatory requirement (EU AI Act Article 14 requires human oversight for high-risk AI systems, which document verification in healthcare qualifies as).

**Why not fully automate:** A 88% confidence AI means 12% of decisions would be wrong without human review. At scale, that is thousands of incorrect approvals or rejections. The human adds a final sanity check that is cheap relative to the cost of a wrong decision.

---

## GDPR and Patient Data Security

### What Personal Data Is Collected

The verification module collects and stores:

- Full name and email address (identity claim)
- Identity documents — passports, national IDs, driver's licenses (sensitive personal data under GDPR Article 9)
- Extracted document data (from OCR processing)
- Audit trail entries linking actions to user IDs

This data falls under **GDPR Article 9** (special category data) because identity documents frequently reveal nationality, date of birth, and in some cases health information. This means stricter rules apply than for ordinary personal data.

---

### How We Handle It

**Data minimisation (GDPR Article 5(1)(c)):**
We only collect what is necessary for verification. We do not store audio, video, or biometric data. The `extracted_data` JSON from the AI pipeline stores only confidence scores and model metadata — not raw OCR text.

**Storage limitation (GDPR Article 5(1)(e)):**
The `delete_verification_files()` function in `storage.py` permanently deletes all uploaded files for a verification case. The `auto_purge_hours` setting in config controls automatic deletion after N hours of inactivity. In production this would be triggered by a scheduled job.

**Integrity and confidentiality (GDPR Article 5(1)(f)):**
- Files are stored with SHA-256 hashes. Any tampering with stored files is detectable.
- All API endpoints require a JWT Bearer token. Unauthenticated requests are rejected before any data is accessed.
- In production, all traffic must use TLS 1.3. Files in cloud storage must use server-side encryption (AES-256).

**Audit trail (accountability, GDPR Article 5(2)):**
Every action on a verification case is logged in `verification_audit_log` — who did what, when, and with what parameters. This table is append-only by design: the repository uses `session.add()` not `session.merge()`, making overwrites structurally impossible. This log is the evidence trail for GDPR compliance audits.

**Right to erasure (GDPR Article 17):**
When a user exercises their right to be forgotten, the complete deletion path is:
1. `delete_verification_files(verification_id)` — removes all uploaded documents from disk
2. Database cascade delete — removes all related documents, jobs, and audit entries
3. The verification record itself is deleted

Currently this is a manual admin operation. In V2 it should be a self-service endpoint with an approval workflow.

**Data residency:**
The `allow_cloud_processing` config flag defaults to `False`. This means no data leaves the local machine unless explicitly enabled. In a Norwegian healthcare context, this is important because patient data must remain within EEA borders (Schrems II ruling). Azure Norway East or on-premise deployment are the appropriate production targets.

---

### Access Control Design

**Why JWT over session cookies:**
JWTs are stateless — the backend does not need a session store. This is important for horizontal scaling (multiple API instances) because any instance can validate any token without a shared cache. The token carries the user's identity and role as signed claims.

**Why role-based (RBAC) over attribute-based (ABAC):**
RBAC (`clinician` vs `admin`) is simple, auditable, and sufficient for this module. ABAC (e.g., "admin can only review cases in their department") would be more granular but requires a policy engine (e.g., OPA) and significantly more infrastructure. RBAC is the right starting point — you can layer ABAC on top later.

**Current limitation:** The `admin` role is granted at token creation time (the `role` field in the token request). In production, roles must come from a trusted identity provider (HelseID, Azure AD) — not from the client request body. Currently any caller can request `role: admin` if they know the API secret. This is acceptable for a development demo but must be fixed before production.

---

## Scalability

### Current Architecture (Single Instance)

```
Browser → Vite proxy → FastAPI (single process) → SQLite file
                                    ↓
                          verification_uploads/ (local disk)
```

This works for development and small-scale demos. It will not scale beyond a single machine.

### Path to Scale

**Step 1 — Stateless API (already done)**
The API is already stateless. JWT tokens carry all session state. Multiple FastAPI instances behind a load balancer will work without any code changes.

**Step 2 — Replace SQLite with PostgreSQL**
SQLite has a single-writer limitation. PostgreSQL supports concurrent writes from multiple API instances. The ORM abstraction means this is a connection string change plus Alembic migration.

**Step 3 — Extract background jobs to a real queue**
Currently `_run_document_job()` runs inline in the request thread. Under load, this blocks API responses and can cause timeouts. The fix is to write the job record to the database, return the HTTP response immediately, and have a separate Celery worker process pick up and execute the job. The `VerificationJob` table already has all the fields needed (`worker_id`, `retry_count`, `last_error`, `started_at`, `completed_at`) — the infrastructure just needs to be wired up.

```
API request → save job record → return 202 Accepted
                    ↓
            Celery worker picks up job
                    ↓
            Runs OCR + AI scoring
                    ↓
            Updates job + document records
```

**Step 4 — Move file storage to blob storage**
`storage.py` is already an abstraction layer. Replacing the local filesystem implementation with Azure Blob Storage or S3 is a single-file change. Files in blob storage are:
- Replicated across availability zones
- Accessible from any API instance (no shared filesystem needed)
- Encrypted at rest by default
- Auditable via storage access logs

**Step 5 — Read replicas for audit queries**
The `verification_audit_log` table grows without bound (append-only by design). At scale, audit queries should hit a read replica, not the primary write database. PostgreSQL streaming replication makes this straightforward.

---

## What Was Difficult to Build

### 1. Token Race Condition on Page Load

The biggest frontend challenge was a timing issue: `authenticate()` is an async function called in a React `useEffect`. If the user clicks "Submit for Verification" before the async call resolves, the request goes out with no `Authorization` header and the backend returns 401.

Three different approaches were tried before landing on the current solution:
- **Attempt 1:** `sessionStorage` fallback — solved the immediate problem but introduced stale tokens when the backend restarted
- **Attempt 2:** Module-level variable — correct in theory but Vite HMR reloads reset the variable while React preserved the `authReady=true` state, creating a false "authenticated" state
- **Final solution:** `window.__msToken` — a property on the global `window` object that survives Vite HMR module reloads but is cleared on full page reload (which also clears the token from the previous backend session). Combined with React `authReady` state tracked via `.then(() => setAuthReady(true))`, the button is disabled until the token is genuinely set.

**What this teaches:** Frontend authentication state is harder than it looks in development environments with hot reload. Production builds do not have this problem (no HMR), but dev environments introduce subtle timing bugs that are difficult to reproduce.

### 2. SQLite Schema Migrations

SQLAlchemy's `create_all()` only creates tables that do not yet exist. It does not add columns to existing tables. When new columns were added (`version` to `VerificationRow`, new tables for `VerificationJobRow` etc.), the existing database file had the old schema and the app failed silently or with cryptic errors.

The solution for development was to delete and recreate the database file. In production, this is not acceptable — you need Alembic for proper migrations. This is a known gap in the current implementation.

### 3. Admin Route Ordering in FastAPI

FastAPI matches routes in the order they are registered. The admin endpoint `/admin/all` (a literal path) was being matched by `/{verification_id}` (a path parameter) before reaching the admin route. This caused 422 Unprocessable Entity errors when calling the admin list endpoint.

The fix was to register the `/admin/all` route before the `/{verification_id}` route. FastAPI evaluates literal path segments before parameterised ones when registered first. This is a non-obvious FastAPI behaviour that is not clearly documented.

### 4. File Download with Authorization Header

Browsers cannot set custom headers on `<a href>` tag navigations. A simple link to the download endpoint would send no `Authorization` header and get a 401.

The solution was to use `fetch()` with the auth header, receive the response as a `Blob`, create a temporary object URL with `URL.createObjectURL()`, and open that URL in a new tab. The object URL lives in browser memory for the session and is not exposed to the server. This is the standard pattern for authenticated file downloads in single-page applications.

---

## What to Improve in Version 2

### High Priority

**1. Real OCR and Document Classification**
Replace the simulated `random.uniform(0.72, 0.97)` confidence score with a real pipeline:
- Azure Document Intelligence for field extraction (name, date of birth, document number)
- A custom ML classifier to verify the document is the claimed type (passport vs ID card)
- Cross-reference extracted name against the submitted `full_name` field
- Flag documents where the photo does not match previous submissions

**2. Alembic Database Migrations**
Replace `create_all()` with proper Alembic migrations. Every schema change should be a versioned, reversible migration script. This is non-negotiable for production.

**3. Real Task Queue**
Replace `_run_document_job()` inline execution with Celery + Redis. Benefits: jobs survive API restarts, failed jobs retry automatically, job processing can scale independently from the API, and long-running OCR does not block HTTP responses.

**4. Self-Service GDPR Erasure**
Add a `DELETE /api/v1/verification/{id}` endpoint that:
- Requires the user to be the owner or an admin
- Deletes all uploaded files from storage
- Cascades to documents, jobs, and audit entries
- Creates a final audit entry recording the deletion (meta-audit)

**5. Role Assignment via Identity Provider**
The current implementation allows any caller to request `role: admin` in the token request. In production, roles must be assigned by a trusted identity provider and embedded in the token by that provider — not requested by the client. Integrate with HelseID (Norwegian national healthcare identity) or Azure AD.

### Medium Priority

**6. Pagination on List Endpoints**
`GET /admin/all` returns all records. At scale this will be slow and memory-intensive. Add cursor-based or offset pagination with a `limit` parameter.

**7. Conflict Retry UX**
When optimistic locking fires a 409, the frontend currently shows an error and the admin must manually refresh. A better UX: catch the 409, auto-reload the detail view, show a toast notification ("Another admin updated this case — showing latest version"), and let the admin retry.

**8. Notification System**
When a case is approved or rejected, the submitter should receive an email or in-app notification. Currently they must poll the list view. Add a notification service with event hooks on state transitions.

**9. Document Expiry Detection**
ID documents have expiry dates. The OCR pipeline should extract the expiry date and automatically flag or reject documents that are expired. This should be a non-blocking warning (admin can still approve) rather than a hard block.

### Low Priority (Nice to Have)

**10. Multi-Document Verification**
Currently one document per submission. A complete KYC flow typically requires two documents — a photo ID plus a proof of address. Add support for multiple document slots per verification case, each with its own AI scoring and required/optional flag.

**11. Reviewer Assignment**
Currently any admin can review any case. Add case assignment so a specific admin is responsible for each case, with workload balancing and SLA tracking (cases not reviewed within N hours trigger an alert).

**12. Audit Trail Export**
Compliance teams need to export audit trails as PDF or CSV for regulatory filings. Add a `GET /admin/{id}/audit/export` endpoint that generates a formatted report.

**13. Duplicate Detection**
Use the SHA-256 document hash to detect when the same file is submitted multiple times across different verification cases. Flag duplicates for admin attention — it may indicate fraud or a re-submission error.

---

## Production Readiness Checklist

- [ ] Replace inline `_run_document_job()` with Celery + Redis task queue
- [ ] Replace `storage.py` local filesystem with Azure Blob Storage or S3
- [ ] Add HelseID / Azure AD integration to `auth_routes.py`
- [ ] Add PostgreSQL with Alembic migrations (replace SQLite `create_all`)
- [ ] Enable `allow_cloud_processing=True` only in dedicated cloud regions
- [ ] Rotate `MEDSCRIBE_SECRET_KEY` — current `dev-secret` is for local dev only
- [ ] Add rate limiting on upload endpoint (prevent abuse)
- [ ] Partition `verification_audit_log` table by month for large scale
