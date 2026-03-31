# Aidn Integration Guide — MedScribe AI

## Overview

MedScribe AI is an AI microservice that adds speech-to-text and
clinical note structuring to Aidn's journal system. Aidn stays
the source of truth for patient data — MedScribe is a processing
engine that Aidn calls when a doctor needs to create a note.

## Integration Architecture

```
┌─────────────────────────────────────────────┐
│  Aidn EPJ System                             │
│                                               │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
│  │ Aidn     │  │ Aidn     │  │ Aidn       │ │
│  │ Frontend │  │ Backend  │  │ Database   │ │
│  │ (React)  │──│ (API)    │──│ (Journal)  │ │
│  └────┬─────┘  └────┬─────┘  └────────────┘ │
│       │              │                        │
└───────┼──────────────┼────────────────────────┘
        │              │
        │              │  REST API / FHIR
        │              ▼
        │     ┌──────────────────┐
        │     │  MedScribe AI    │
        │     │  (microservice)  │
        │     │                  │
        │     │  POST /transcribe│
        │     │  POST /structure │
        │     │  GET /fhir/bundle│
        │     └──────────────────┘
        │
        │  WebSocket (optional — real-time transcription)
        └──▶ ws://medscribe/api/v1/ws/transcribe
```

## Step-by-Step Integration

### Step 1: Authentication

Aidn's backend gets a JWT token from MedScribe:

```bash
POST /api/v1/auth/token
Content-Type: application/json

{
  "client_id": "aidn-backend",
  "client_secret": "<shared-secret>",
  "role": "system"
}

# Response:
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

### Step 2: Create a Visit

When a doctor starts a consultation in Aidn:

```bash
POST /api/v1/visits
Authorization: Bearer <token>
Content-Type: application/json

{
  "patient_id": "aidn-patient-12345",
  "clinician_id": "aidn-doctor-67890",
  "metadata": {
    "aidn_encounter_id": "enc-abc-123",
    "department": "general_practice",
    "template": "general_practice"
  }
}

# Response:
{
  "id": "visit-uuid-here",
  "status": "created",
  "allowed_transitions": ["recording", "failed"]
}
```

### Step 3: Send Audio for Transcription

Doctor finishes recording in Aidn, Aidn sends audio to MedScribe:

```bash
POST /api/v1/visits/{visit_id}/transcribe
Authorization: Bearer <token>
Content-Type: multipart/form-data

audio: <binary audio data (WAV/WebM)>

# Response:
{
  "raw_text": "Pasienten har hodepine i tre dager...",
  "language": "no",
  "model_id": "local/whisper-medium",
  "confidence": 0.87,
  "duration_seconds": 45.2
}
```

### Step 4: Structure into Clinical Note

```bash
POST /api/v1/visits/{visit_id}/structure
Authorization: Bearer <token>

# Response:
{
  "sections": {
    "chief_complaint": "Hodepine i tre dager",
    "history": "Ingen feber. Paracetamol gir noe lindring.",
    "examination": "BT 120/80, P 72, T 36.8",
    "assessment": "Tensjonshodepine",
    "plan": "Fortsett paracetamol ved behov. Kontroll om 2 uker.",
    "medications": "Paracetamol 500mg x 4",
    "follow_up": "Kontroll om 2 uker"
  },
  "model_id": "ollama/llama3.2:1b",
  "is_approved": false
}
```

### Step 5: Doctor Reviews in Aidn

Aidn shows the structured note in its journal editor.
Doctor can edit sections directly in Aidn's UI.

If edits are made, Aidn sends them back:

```bash
PUT /api/v1/visits/{visit_id}/note
Authorization: Bearer <token>
Content-Type: application/json

{
  "sections": {
    "chief_complaint": "Hodepine i tre dager, bilateral",
    ...corrected sections...
  }
}
```

### Step 6: Approve

Doctor approves the note in Aidn:

```bash
POST /api/v1/visits/{visit_id}/approve
Authorization: Bearer <token>
Content-Type: application/json

{
  "approved_by": "aidn-doctor-67890"
}
```

### Step 7: Get FHIR Bundle and Save to Journal

Aidn gets the FHIR-formatted note and saves it to the patient journal:

```bash
GET /api/v1/visits/{visit_id}/fhir/bundle
Authorization: Bearer <token>

# Response: FHIR R4 Bundle with Composition + DocumentReference
# Aidn saves this to its own journal database
```

### Step 8: GDPR Purge

After Aidn confirms the note is saved in the journal:

```bash
POST /api/v1/visits/{visit_id}/purge
Authorization: Bearer <token>

# All patient data deleted from MedScribe
# Only anonymized audit entries remain
```

## Real-Time Streaming (Optional)

For live transcription (text appears as doctor speaks):

```javascript
// In Aidn's frontend
const ws = new WebSocket("wss://medscribe.hospital.no/api/v1/ws/transcribe?language=no");

// Send audio chunks from microphone
mediaRecorder.ondataavailable = (e) => ws.send(e.data);

// Receive live text
ws.onmessage = (e) => {
  const data = JSON.parse(e.data);
  updateTranscriptUI(data.text);  // Shows text in real-time
};
```

## Full Pipeline (Single Call)

For simplest integration, use the one-shot endpoint:

```bash
POST /api/v1/visits/{visit_id}/process
Authorization: Bearer <token>
Content-Type: multipart/form-data

audio: <binary audio data>

# Returns: transcript + structured note + safety flags in one response
```

## Security Requirements

| Requirement | Implementation |
|---|---|
| Authentication | JWT Bearer tokens |
| Network | Private VNet / Norsk Helsenett (no public internet) |
| Encryption in transit | TLS 1.3 |
| Encryption at rest | Azure PostgreSQL encryption + Key Vault |
| Data retention | Auto-purge after 24h (configurable) |
| Audit | Every action logged with actor + timestamp |
| GDPR | Purge endpoint + auto-purge |

## Deployment Options

| Option | For | How |
|---|---|---|
| **Same Azure subscription** | Aidn runs on Azure | Deploy MedScribe to same VNet |
| **Norsk Helsenett** | Hospital network | Expose via Norsk Helsenett endpoint |
| **On-premise** | Hospital datacenter | Docker/K8s on hospital servers |
