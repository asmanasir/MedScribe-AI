# System Architecture — MedScribe AI & Verification Module

**Author:** Asma Hafeez  
**Stack:** FastAPI · SQLAlchemy · PostgreSQL · React · TypeScript · Tailwind CSS · JWT · Docker

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture Style — Why Modular Monolith](#2-architecture-style--why-modular-monolith)
3. [Database Design — Why Relational](#3-database-design--why-relational)
4. [Scalability — Built In From Day One](#4-scalability--built-in-from-day-one)
5. [Read Scalability — Handling Unlimited Reads](#5-read-scalability--handling-unlimited-reads)
6. [Security Architecture](#6-security-architecture)
7. [The Verification Module in Detail](#7-the-verification-module-in-detail)
8. [Difficulties We Faced](#8-difficulties-we-faced)
9. [What We Would Do Differently — Future Improvements](#9-what-we-would-do-differently--future-improvements)

---

## 1. System Overview

MedScribe AI is a clinical documentation platform for Norwegian healthcare. It transcribes doctor-patient consultations, generates structured clinical notes using a local LLM, and exports them to EPJ (Electronic Patient Journal) systems in FHIR R4, HL7v2, or KITH XML format.

The **Verification Module** is a separate bounded domain inside the same deployment. It handles identity and document verification for healthcare providers — a KYC/KYP (Know Your Provider) workflow where users upload identity documents, an AI pipeline scores them, and a human admin makes the final decision.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        MedScribe AI Platform                        │
│                                                                     │
│  ┌──────────────────────────┐   ┌─────────────────────────────┐    │
│  │   Clinical Domain        │   │   Verification Domain        │    │
│  │                          │   │                              │    │
│  │  STT → LLM → Structure   │   │  Submit → AI Score → Review  │    │
│  │  Agents → FHIR Export    │   │  Approve / Reject / Resubmit │    │
│  │  Audit → Privacy         │   │  Audit → GDPR Purge          │    │
│  └──────────────────────────┘   └─────────────────────────────┘    │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              FastAPI Gateway (JWT + RBAC)                    │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │  PostgreSQL  │  │  File Store  │  │  Background Jobs (Queue) │  │
│  │  (Primary DB)│  │  (Blob/Local)│  │  (Celery + Redis)        │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### Screenshots of the Working System

**Document Submission Form** — drag and drop, file validation, auth guard  
![Submit Verification](screenshots/submit.png)

**Verification Detail — Pending** — System info bar (version, optimistic lock), Background Jobs panel, AI Validation panel with 70% threshold  
![Detail Pending](screenshots/detail_pending.png)

**Verification Detail — Rejected** — Rejection reason banner, AI suggestion vs human decision comparison, full audit trail  
![Detail Rejected](screenshots/detail_rejected.png)

**Admin Dashboard** — Status summary cards (Pending / In Review / Approved / Rejected), all cases list with reviewer column  
![Admin List](screenshots/list_admin.png)

---

## 2. Architecture Style — Why Modular Monolith

### What We Chose

We built a **modular monolith** — a single deployable application where each business domain (clinical, verification) is a self-contained module with hard boundaries. No module imports from another module's internals.

```
src/medscribe/
├── verification/     ← isolated domain (zero imports from clinical/)
│   ├── enums.py
│   ├── models.py
│   ├── repository.py
│   ├── service.py
│   ├── security.py
│   └── storage.py
├── api/              ← thin HTTP layer, routes delegate to services
├── services/         ← clinical AI pipeline
└── storage/          ← shared DB infrastructure only
```

### Why Not Microservices

Microservices are the right answer at a certain scale. They are the wrong answer at the start. Here is why we did not begin with microservices:

| Concern | Microservices problem | Modular monolith solution |
|---------|----------------------|--------------------------|
| Operational complexity | Each service needs its own CI/CD, logging, health checks, network config | One deployment, one log stream, one config |
| Distributed transactions | Approving a verification and writing an audit entry become a distributed transaction (2PC or saga) | Both happen in one database transaction |
| Network latency | Service-to-service calls add latency for every operation | In-process function calls, zero network overhead |
| Developer velocity | Changing a domain model requires coordinating across service boundaries | Change the model, run the tests, ship |
| Debugging | Tracing a request across 4 services requires distributed tracing infrastructure | One stack trace |

The modular monolith gives us the **code organization benefits of microservices** (hard module boundaries, independent domain models, no shared state) without the operational cost.

### The Critical Rule: When To Split

The verification module is already structured so that converting it to a standalone microservice requires only:

1. Move `src/medscribe/verification/` to a new repository
2. Replace in-process service calls with HTTP client calls
3. Add its own database connection

The **domain boundary is already there in the code**. We get the option to split later without paying the cost upfront. This is the key insight — we designed for the split without doing it.

### Why Layered Architecture Within Each Module

Every module follows the same 4-layer pattern:

```
HTTP Routes (verification_routes.py)
     ↓  delegates to
Service Layer (service.py)  ← all business logic here
     ↓  reads/writes via
Repository Layer (repository.py)  ← all DB I/O here
     ↓  maps to/from
Database Rows (database.py)  ← SQLAlchemy models
```

**Routes** know nothing about the database. They validate HTTP input and return HTTP output.  
**Service** knows nothing about HTTP or SQLAlchemy. It enforces state machine rules and business invariants.  
**Repository** knows nothing about business rules. It translates between domain objects and database rows.  
**Database rows** know nothing about the domain. They are plain SQLAlchemy table definitions.

This separation means:
- You can test the service layer without a database (inject a mock repository)
- You can change the database schema without touching business logic
- You can add a new transport (gRPC, WebSocket) without duplicating business rules

---

## 3. Database Design — Why Relational

### The Choice: PostgreSQL (Relational)

We chose a **relational database (PostgreSQL)** over a document store (MongoDB) or key-value store (Redis). This was not a default choice — it was a deliberate decision based on the requirements of the system.

### Why Relational Wins Here

**1. ACID transactions are non-negotiable in healthcare**

When a doctor approves a verification, three things must happen atomically:
- The verification record status changes to APPROVED
- The `reviewed_by` and `reviewed_at` fields are stamped
- An audit entry is written

If any of these fail, all must roll back. In a relational database, this is a single transaction. In MongoDB, multi-document transactions exist but are more expensive and less battle-tested. In a key-value store, you would implement this yourself.

Healthcare data where partial writes exist (status = APPROVED but no audit entry written) is a compliance failure. ACID is the requirement, not a nice-to-have.

**2. The data has clear relational structure**

```
verifications (1) ──── (many) verification_documents
verifications (1) ──── (many) verification_jobs
verifications (1) ──── (many) verification_audit_log
```

This is textbook relational data. Document stores work well for unstructured or highly variable data. Our data has a fixed, well-defined schema that does not change at runtime. Using a document store here would add flexibility we do not need at the cost of losing referential integrity.

**3. SQL queries for admin reporting**

The admin dashboard needs queries like:
- Count of cases by status
- All cases reviewed by a specific admin in the last 30 days
- Cases where AI said approve but human rejected

These are trivial SQL GROUP BY / WHERE queries. Building the same in MongoDB requires aggregation pipelines that are harder to read, harder to test, and harder to optimise.

**4. Optimistic locking is native**

Our concurrency control uses a `version` integer column. PostgreSQL's MVCC (Multi-Version Concurrency Control) means read and write locks do not block each other. Two admins can read the same case simultaneously without contention. The version check on write is a simple WHERE clause.

### Schema Design Decisions

**Separate tables per concern, not a single JSON blob**

Some developers store everything in a single JSON column (`data JSONB`). This is tempting but wrong for several reasons:
- You cannot index into JSON fields efficiently for high-cardinality queries
- You cannot enforce NOT NULL constraints on JSON subfields
- You cannot write join queries between JSON subfields and other tables
- Schema changes (adding a required field) require application-level migrations with fallback logic

We use separate columns for every field we query, filter, or join on. JSONB is used only for `extracted_data` (the raw OCR output) and `detail_json` (audit entry metadata) — fields we store but never filter on.

**Append-only audit table**

```sql
-- verification_audit_log: no UPDATE, no DELETE ever
-- Repository uses session.add() not session.merge()
id, verification_id, action, actor, detail_json, timestamp
```

The audit table uses `session.add()` (INSERT only) instead of `session.merge()` (INSERT or UPDATE). This is enforced in the repository code. Making it structurally impossible to update audit entries is more reliable than a policy that says "don't update audit entries."

**Dev/Prod parity via abstraction**

SQLite in development, PostgreSQL in production. The connection string is the only difference:

```bash
# Dev
MEDSCRIBE_DATABASE_URL=sqlite+aiosqlite:///./medscribe.db

# Prod
MEDSCRIBE_DATABASE_URL=postgresql+asyncpg://user:pass@host/db
```

The async SQLAlchemy ORM abstracts all vendor differences. This means bugs found in development have a high chance of being real bugs, not SQLite-specific behaviour.

---

## 4. Scalability — Built In From Day One

We did not leave scalability for a future version. Every architectural decision was made with scale in mind, even though the current deployment is a single instance. Here is the evidence:

### Stateless API (Already Done)

The FastAPI application holds zero state in memory. Every request is self-contained:
- Authentication state lives in the JWT token (no server-side sessions)
- Request context lives in the database
- File content is streamed through, not buffered in application memory

This means you can run 10 instances of the API behind a load balancer today. No code changes required. The only shared state is the database — which is designed for concurrent access.

```
Load Balancer
     │
     ├── API Instance 1 (stateless)
     ├── API Instance 2 (stateless)  →  PostgreSQL (shared state)
     └── API Instance 3 (stateless)
```

### Async I/O (Already Done)

Every database call, file read, and HTTP request in the backend uses Python's `async/await`. This means a single API process can handle thousands of concurrent connections without spawning thousands of threads.

```python
# All database calls are non-blocking
v, docs = await svc.get_with_documents(verification_id)
jobs = await svc.get_jobs(verification_id)
```

A synchronous (blocking) equivalent would hold a thread for each active request. With async I/O, the same thread handles thousands of requests while waiting for database responses. This is why FastAPI with `asyncpg` (the async PostgreSQL driver) handles significantly higher throughput than Flask with `psycopg2`.

### File Storage Abstraction (Ready to Scale)

The `storage.py` module hides all file I/O behind three functions:

```python
save_document(verification_id, document_id, content, file_name)
load_document(path)
delete_verification_files(verification_id)
```

Currently these write to local disk. When the system grows beyond a single server, you replace the implementation with Azure Blob Storage or AWS S3. The routes and service layer are completely unaware of this change. This is the **adapter pattern** applied to storage.

### Background Jobs (Designed for Queue, Running Inline)

The document processing job currently runs inline in the same request thread:

```
HTTP request → validate file → save file → save job record → run AI scoring → return response
```

This is a development convenience. The job tracking infrastructure (`VerificationJob` table with `worker_id`, `retry_count`, `started_at`, `completed_at`) is already production-ready. Moving to a real queue means:

1. After saving the job record, return HTTP 202 Accepted immediately
2. A Celery worker process picks up the job from Redis
3. Worker updates the job record with progress and results
4. Frontend polls or receives a WebSocket push when complete

The database schema does not change. The service interface does not change. Only the job execution mechanism changes.

### Connection Pooling (Ready)

SQLAlchemy's async engine uses connection pooling by default. The pool size is configurable via the connection string parameters. For high-traffic deployments, PgBouncer sits between the API and PostgreSQL to multiplex thousands of application connections onto a smaller pool of actual database connections.

### Horizontal Scaling Path

```
Current (1 server):
Browser → FastAPI (port 8000) → SQLite

Step 1 (multiple API instances):
Browser → Nginx/Traefik → [FastAPI × N] → PostgreSQL

Step 2 (separate job processing):
Browser → Nginx/Traefik → [FastAPI × N] → PostgreSQL
                                        → Redis → [Celery Worker × M]

Step 3 (cloud-native):
Browser → Azure Front Door → [Azure Container Apps × N]
                           → Azure Database for PostgreSQL (flexible server)
                           → Azure Blob Storage
                           → Azure Cache for Redis
```

Each step is an infrastructure change, not a code change. The application is already written for Step 3.

---

## 5. Read Scalability — Handling Unlimited Reads

Writes are naturally limited (you can only submit, approve, or reject so many cases). Reads are the real challenge — audit queries, admin dashboards, reporting. Here is how we designed for read scale.

### Database Indexing Strategy

Every column used in WHERE or ORDER BY clauses has an index:

```python
# verification_documents
verification_id: Mapped[str] = mapped_column(String(36), index=True)

# verification_jobs
verification_id: Mapped[str] = mapped_column(String(36), index=True)
status: Mapped[str] = mapped_column(String(50), index=True)

# verification_audit_log
verification_id: Mapped[str] = mapped_column(String(36), index=True)
action: Mapped[str] = mapped_column(String(100), index=True)
timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
```

Without these indexes, every query that filters by `verification_id` would do a full table scan. With 1 million audit entries, an unindexed query takes seconds. With an index on `verification_id`, it takes milliseconds.

### Read Replicas for Audit Queries

The audit log is append-only and grows indefinitely. In production:

- **Primary database** handles all writes (submit, upload, approve, reject)
- **Read replica** handles all read queries (audit trail, list views, reporting)

PostgreSQL streaming replication keeps the replica in sync with sub-second lag. The application routes queries:

```python
# Write path (primary)
await svc.approve(verification_id, reviewer)

# Read path (replica)
await svc.get_audit_trail(verification_id)
```

This doubles read throughput without adding any application-level complexity.

### Audit Log Partitioning

The `verification_audit_log` table will become very large in production. PostgreSQL table partitioning by month keeps query performance consistent:

```sql
-- Each month becomes its own partition
CREATE TABLE verification_audit_log_2026_04
    PARTITION OF verification_audit_log
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
```

Queries that filter by timestamp (e.g. "show me all activity this month") only scan the relevant partition. Old partitions can be moved to cheaper storage or archived to object storage (Azure Blob / S3).

### Caching Layer (Future, But Designed For)

The admin summary cards (Pending: 0, In Review: 1, Approved: 0, Rejected: 1) are aggregate COUNT queries that run on every page load. Under load, these become expensive.

The solution is a Redis cache with a short TTL (30 seconds):

```
Request → cache hit? → return cached count
        → cache miss? → query DB → store in cache → return count
```

The cache is automatically invalidated when a status changes (on any write to the verifications table). The application is already structured so this cache can be added in one place (the service layer) without touching routes or repositories.

### Frontend Pagination (Required for Scale)

The current `GET /admin/all` endpoint returns all verification records. With 100,000 cases, this response would be:
- Too large to transfer (slow)
- Too large to render (browser freeze)
- Too expensive to query (full table scan despite indexes)

The fix is cursor-based pagination:

```
GET /admin/all?cursor=<last_seen_id>&limit=50
```

Each page returns 50 records and a cursor pointing to the next page. The database only reads 50 rows regardless of total table size. This is a V2 priority.

---

## 6. Security Architecture

Security was not an afterthought. Every layer has explicit security decisions.

### Authentication: JWT Bearer Tokens

Every API endpoint (except `POST /auth/token`) requires a valid JWT Bearer token. The token is:
- Signed with HMAC-SHA256 using a server secret
- Contains the user ID (`sub`) and role (`role`) as claims
- Has a configurable expiry (default 60 minutes)
- Stateless — no server-side session storage required

```
Client                          Server
  │                               │
  │  POST /auth/token             │
  │  { client_id, secret, role }  │
  ├──────────────────────────────►│
  │                               │  verify secret
  │  { access_token: "eyJ..." }   │  create JWT
  │◄──────────────────────────────┤
  │                               │
  │  GET /verification/{id}       │
  │  Authorization: Bearer eyJ... │
  ├──────────────────────────────►│
  │                               │  verify JWT signature
  │  { verification data }        │  extract user_id, role
  │◄──────────────────────────────┤
```

**Why stateless JWT over sessions:** Multiple API instances can verify any token without a shared session store. This is required for horizontal scaling.

**Current limitation:** The role is requested by the client (`role: 'admin'`). In production, roles must come from a trusted identity provider (HelseID, Azure Active Directory). The current flow is acceptable for development but must be replaced before production.

### Authorisation: Role-Based Access Control (RBAC)

Every route declares its required role using FastAPI's dependency injection:

```python
# Any authenticated user
user: AuthenticatedUser = Depends(get_current_user)

# Admin only
admin: AuthenticatedUser = Depends(require_role(["admin"]))
```

The `require_role` dependency is composable — you can require multiple roles or create new role hierarchies without changing route code.

### File Upload Security

Three layers of validation on every uploaded document:

**Layer 1 — MIME type allowlist** (`security.py`):
```python
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
```
Files with unexpected MIME types are rejected immediately, before any content is read.

**Layer 2 — File size limit:**
Files larger than 10 MB return HTTP 413. This prevents memory exhaustion attacks where an attacker sends a multi-gigabyte file.

**Layer 3 — SHA-256 integrity hash:**
```python
file_hash = hashlib.sha256(content).hexdigest()
```
The hash is stored with the document. Any tampering with the stored file is detectable by re-hashing and comparing.

**Why not virus scanning?** A production system would also run uploaded files through a virus scanner (ClamAV or Azure Defender for Storage) before storing them. This is a V2 item.

### Data Encryption

**In transit:** TLS 1.3 for all production traffic. The development setup uses plain HTTP (acceptable on localhost only).

**At rest:** Azure Blob Storage and Azure Database for PostgreSQL both encrypt data at rest with AES-256 by default. No application-level encryption is needed when the storage layer handles it.

**Sensitive fields:** Rejection reasons and document metadata are stored as plaintext in the database. In a higher-sensitivity deployment, these could be encrypted at the application level using column-level encryption before storage.

### GDPR Compliance

**Right to erasure (Article 17):** The `delete_verification_files()` function removes all uploaded files. A cascade delete on the verification record removes all related documents, jobs, and audit entries. The system is capable of full data deletion.

**Data minimisation (Article 5(1)(c)):** We store only what is necessary. No audio. No biometric data. The OCR extraction stores only confidence scores, not raw extracted text.

**Audit trail (accountability, Article 5(2)):** Every state change is logged in an append-only table. The repository uses `session.add()` not `session.merge()` — overwrites are structurally impossible.

**Data residency:** The `allow_cloud_processing` config flag defaults to `False`. No data leaves the local machine unless explicitly enabled. Norwegian healthcare requires data to remain within EEA (Schrems II ruling). Azure Norway East is the appropriate production target.

---

## 7. The Verification Module in Detail

### Why a Separate Module (Not Merged with Clinical)

The clinical domain handles visit workflows (recording → transcription → structuring → approval → export). The verification domain handles identity workflows (submission → AI scoring → human review → approval/rejection).

These are **different bounded contexts** with different:
- State machines (8 states vs 4 states)
- User roles (clinician/admin vs submitter/reviewer)
- Data models (visit/transcript/note vs verification/document/job)
- Business rules (note approval vs identity verification)
- Audit requirements (clinical audit vs KYC audit)

Merging them would create a "god module" where a change to clinical approval logic risks breaking identity verification. Keeping them separate means each domain can evolve independently.

### State Machine Design

```
         submit()
PENDING ──────────────► IN_REVIEW
   ▲                         │
   │                    ┌────┴────┐
   │            approve()│        │reject(reason)
   │                     ▼        ▼
   │                 APPROVED  REJECTED
   │                              │
   └──────────────────────────────┘
              resubmit()
```

The state machine is enforced by a single dictionary in `service.py`. Every attempt to make an invalid transition raises HTTP 409 immediately. There is no way to reach APPROVED from PENDING without going through IN_REVIEW. This is enforced by the code, not by documentation.

### AI Pipeline Design

The AI pipeline runs as a background job triggered on document upload:

```
Document upload
      │
      ▼
validate_upload()          # MIME type, size limit
read_and_validate_content()  # read bytes, check not empty
      │
      ▼
save_document()            # write to storage, compute SHA-256
      │
      ▼
VerificationJob created    # job record in DB (status: PENDING)
      │
      ▼
_run_document_job()        # status: PROCESSING, worker_id set
      │
      ├── OCR extraction   # (simulated; production: Azure Document Intelligence)
      ├── confidence score # (simulated; production: ML classifier)
      └── extracted_data   # model name, score, threshold, suggestion
      │
      ▼
Job: COMPLETED             # doc.ai_confidence updated
```

The AI **never approves automatically**. Even a 99% confidence score requires a human to click Approve. This is a deliberate design choice aligned with EU AI Act Article 14 (human oversight for high-risk AI).

### Optimistic Locking in Practice

Two admins open the same case simultaneously. Both see version 2.

Admin A clicks Approve:
```
UPDATE verifications SET status='approved', version=3 WHERE id=X AND version=2
→ 1 row affected → success
```

Admin B (who had the same case open) clicks Reject 100ms later:
```
UPDATE verifications SET status='rejected', version=3 WHERE id=X AND version=2
→ 0 rows affected (version is now 3, not 2)
→ HTTP 409 Conflict: "Record was modified by another request. Please refresh and retry."
```

Admin B sees an error and refreshes, now seeing the already-approved case. The approved state is preserved. No silent data corruption.

---

## 8. Difficulties We Faced

### 1. Frontend Authentication Race Condition

**Problem:** `authenticate()` is called in a React `useEffect` on page load. If the user clicked Submit before the async call resolved, the request went out with no Authorization header. The backend returned 401.

**Three attempts before the right solution:**

- **Attempt 1 (sessionStorage):** Stored the token in `sessionStorage` as a fallback. Broke immediately — stale tokens from a previous backend session survived page loads, causing silent 401s on every backend restart.

- **Attempt 2 (module-level variable):** Removed sessionStorage, used only the module-level `let token`. Broke with Vite HMR — when `api.ts` was edited during development, Vite reloaded the module, resetting `token = null`. But React preserved the `authReady = true` state from before the reload. The button appeared enabled but the token was gone.

- **Solution (window variable):** `window.__msToken = token` after authentication. The `window` object persists across Vite HMR module reloads but is cleared on full page refresh. Combined with `authReady` React state tracked via `.then(() => setAuthReady(true))`, the button is disabled until the token is genuinely available.

**What this teaches:** Frontend authentication in development environments with hot reload has subtleties that do not exist in production. The solution that works in production (module variable) fails in development (HMR). The solution must work in both.

### 2. SQLite Schema Migrations

**Problem:** `Base.metadata.create_all()` only creates tables that do not yet exist. It does not add new columns to existing tables. When we added `version` to `VerificationRow` and the new `VerificationJobRow` table, the existing database file had the old schema. The app started without error but failed silently on any write that touched the new columns.

**Symptom:** Backend started successfully, tables appeared to initialise, but `POST /api/v1/verification/` returned 500 with a column-not-found error.

**Solution (development):** Delete `medscribe.db` and let it recreate on next startup.

**Real solution (production):** Alembic migrations. Every schema change must be a versioned migration script with an `upgrade()` and `downgrade()` function. This is the most important V2 item.

### 3. FastAPI Route Ordering

**Problem:** The admin endpoint `GET /admin/all` was being matched by `GET /{verification_id}` because FastAPI evaluated the parameterised route first. Calling `/admin/all` would try to look up a verification with ID "admin", fail with 404, and never reach the admin list endpoint.

**Symptom:** `GET /api/v1/verification/admin/all` returned 404 "Verification 'admin' not found."

**Solution:** Register literal path routes before parameterised routes. FastAPI evaluates routes in registration order, so `/admin/all` must be registered before `/{verification_id}`.

**What this teaches:** FastAPI's route matching is order-dependent. When you mix literal path segments and path parameters at the same depth, the order of `router.get()` calls matters. This is not obvious from the documentation.

### 4. Authenticated File Download

**Problem:** Browsers cannot set custom `Authorization` headers on `<a href>` tag navigations or `window.open()` calls. A direct link to the download endpoint would send no auth header and return 401.

**Failed approach:** Pass the token as a URL query parameter (`?token=eyJ...`). Rejected because tokens in URLs appear in:
- Browser history
- Server access logs
- Referrer headers when clicking external links
- Shared URLs accidentally

**Solution:** Use `fetch()` with the Authorization header, receive the response as a `Blob`, create a temporary object URL with `URL.createObjectURL()`, and open that URL in a new tab. The object URL is a `blob://` URL that lives in browser memory for the session, never touches the server, and is never in the URL bar.

### 5. Ruff Import Ordering (CI Failures)

**Problem:** Ruff's isort integration (`I001`) required imports to be in a specific order: standard library first, then third-party, then local. Our inline imports inside functions (`from medscribe.verification.repository import X` inside a route handler) violated this rule because they were not at the top of the file.

**Problem 2:** Ruff's `S311` rule flags `random.uniform()` as insecure — it uses a pseudo-random number generator not suitable for cryptographic purposes.

**Solutions:**
- Move all imports to the top of each file
- Replace `random.uniform(0.72, 0.97)` with `0.72 + secrets.randbelow(26) / 100` using Python's `secrets` module (cryptographically secure random)

---

## 9. What We Would Do Differently — Future Improvements

### V2 — High Priority

**1. Alembic Database Migrations**
The single most important change before any production deployment. Replace `create_all()` with versioned migration scripts. Every column addition, table creation, or schema change becomes a traceable, reversible migration.

**2. Real Background Job Queue (Celery + Redis)**
Replace `_run_document_job()` inline execution with a proper task queue. The `VerificationJob` table already has all the fields — `worker_id`, `retry_count`, `max_retries`, `last_error`, `started_at`, `completed_at`. Only the execution mechanism needs to change.

Benefits:
- Long-running OCR does not block HTTP responses
- Failed jobs retry automatically up to `max_retries`
- Jobs survive API process restarts
- Job processing scales independently from the API

**3. Real OCR and Document Classification**
Replace `secrets.randbelow(26) / 100 + 0.72` with a real pipeline:
- **Azure Document Intelligence** — extracts name, date of birth, document number, expiry date
- **Custom ML classifier** — verifies the document is the claimed type
- **Cross-reference** — compares extracted name against `full_name` submitted in the form
- **Expiry detection** — automatically flags expired documents

**4. HelseID / Azure AD Integration**
Replace the current `role: 'admin'` in the token request body with role assignment from a trusted identity provider. The client must not be able to self-assign roles.

**5. Pagination**
Add cursor-based pagination to all list endpoints. The current implementation returns all records — this will not work at scale.

### V2 — Medium Priority

**6. Self-Service GDPR Erasure**
A `DELETE /api/v1/verification/{id}` endpoint that removes all files, cascades to all related records, and writes a final audit entry recording the deletion.

**7. Conflict Retry UX**
When optimistic locking fires a 409, auto-reload the detail view instead of showing a raw error. Show a toast: "Another admin updated this case — showing latest version."

**8. Email / Push Notifications**
When a case is approved or rejected, notify the submitter. Currently they must poll the list view.

**9. Duplicate Document Detection**
Use the SHA-256 hash to detect when the same file is submitted across different verification cases. Flag duplicates for admin attention — may indicate fraud or error.

**10. Virus Scanning**
Run uploaded files through ClamAV or Azure Defender before storing. This is standard practice for any system that accepts user-uploaded files.

### V3 — Strategic

**11. Microservice Extraction**
When the verification module handles enough load to justify its own deployment lifecycle, extract it to a standalone service. The module boundary already exists in the code — this is purely an infrastructure change.

**12. Event-Driven Architecture**
Replace synchronous state transitions with domain events published to a message bus (Azure Service Bus, Kafka). Other systems (notification service, compliance reporting, CRM) subscribe to events without coupling to the verification domain.

**13. Multi-Factor Verification**
Require two documents per submission (photo ID + proof of address). Add liveness detection (selfie matching the ID photo) using Azure Face API. This brings the system to full KYC compliance for regulated industries.

**14. SLA Monitoring and Alerts**
Track time-in-state for each verification case. Alert when cases have been pending review for more than N hours. Provide admin workload dashboards showing cases per reviewer, average review time, and rejection rate by document type.

---

*Built by Asma Hafeez — MedScribe AI*
