# Personvern og datahåndtering — MedScribe AI
## GDPR Compliance / Privacy & Data Handling

## 1. Lokal prosessering / Local Processing

All håndtering av pasientdata foregår bak kundens egen brannmur,
uten avhengighet til skytjenester eller eksterne tredjeparter.

### Implementering:
- **STT (tale-til-tekst):** faster-whisper kjører lokalt på kundens server (standard)
- **LLM (tekststrukturering):** Ollama/Llama kjører lokalt på kundens server (standard)
- **Database:** SQLite eller PostgreSQL på kundens infrastruktur
- **Konfigurasjon:** `MEDSCRIBE_ALLOW_CLOUD_PROCESSING=false` (standard)

### Kodebevis:
- `config.py`: `allow_cloud_processing: bool = False` — blokkerer sky-APIer som standard
- `config.py`: `stt_backend: STTBackend = STTBackend.LOCAL` — lokal Whisper som standard
- `stt_local.py`: Logger `data_sent_to_cloud=False` for hver transkripsjon

## 2. Ingen vedvarende lagring / No Persistent Storage

Midlertidige data for transkripsjon kastes automatisk etter at
journalutkast er overført til EPJ. Pasientdata lagres kun i
det godkjente journalsystemet.

### Implementering:
- **Lyddata:** Lagres ALDRI på disk. Eksisterer kun i minne under transkripsjon.
  Midlertidig fil (faster-whisper) slettes umiddelbart etter bruk.
- **Automatisk sletting:** `DataLifecycleManager.purge_visit_data()` sletter ALT
  etter EPJ-overføring
- **Tidsbegrenset lagring:** `auto_purge_hours=24` — automatisk sletting etter 24 timer
  uansett EPJ-status (sikkerhetsnett)

### Data som slettes:
| Data | Slettetidspunkt |
|------|-----------------|
| Lydopptak | Umiddelbart (aldri lagret) |
| Transkripsjon | Etter EPJ-overføring |
| Klinisk notat | Etter EPJ-overføring |
| Sikkerhetsflagg | Etter EPJ-overføring |
| Besøksmetadata | Etter EPJ-overføring |

### Data som beholdes (anonymisert):
| Data | Formål |
|------|--------|
| Revisjonslogg (uten klinisk innhold) | Sporbarhet og etterlevelse |
| Systemmetrikk | Kvalitetssikring |

### API-endepunkter:
- `POST /api/v1/visits/{id}/purge` — Slett all pasientdata etter EPJ-overføring
- `POST /api/v1/privacy/purge-expired` — Auto-slett utløpte data
- `GET /api/v1/privacy/audit-check` — Verifiser at ingen lydfiler finnes på disk

### Kodebevis:
- `privacy/data_lifecycle.py`: `DataLifecycleManager` med full slettelogikk
- `stt_local.py`: `os.unlink(tmp_path)` i `finally`-blokk (alltid slettet)
- `config.py`: `store_audio_on_disk: bool = False`

## 3. Streng tilgangskontroll / Strict Access Control

Rollebasert autentisering (RBAC) sikrer at bare autorisert
personell får tilgang.

### Implementering:
- **JWT-autentisering:** Alle API-kall krever gyldig token
- **RBAC:** `require_role(["clinician", "admin"])` på rutenivå
- **Revisjonslogg:** Alle handlinger logges med bruker-ID og tidspunkt
- **SSO-klar:** JWT-basert — kompatibel med Azure AD / HelseID

### Kodebevis:
- `api/auth.py`: `get_current_user()` — tvungen autentisering
- `api/auth.py`: `require_role()` — rollebasert tilgangskontroll
- `workflow/engine.py`: Hver tilstandsovergang logger `actor`

## 4. GDPR-prinsipper / GDPR Principles

| Prinsipp | Implementering |
|----------|---------------|
| **Dataminimering** | Kun nødvendige data behandles. Lyd slettes umiddelbart. |
| **Formålsbegrensning** | Data brukes kun til journalgenerering |
| **Lagringsbegrensning** | Auto-sletting etter 24 timer |
| **Integritet og konfidensialitet** | JWT-autentisering, RBAC, lokal prosessering |
| **Rettigheter** | Slette-API tilgjengelig for å fjerne all pasientdata |

## 5. Standarder vi følger / Standards

| Standard | Status | Beskrivelse |
|----------|--------|-------------|
| **GDPR** | Implementert | Dataminimering, formålsbegrensning, sletting |
| **MDR (CE klasse I)** | Rammeverk klart | Teknisk dokumentasjon, risikovurdering |
| **ISO 13485** | Prosess definert | Sporbar utvikling, risikostyring |
| **ISO 27001** | Prinsipper fulgt | Informasjonssikkerhet i arkitektur |
| **EU AI Act** | Forberedt | Dokumentasjon, transparens, overvåking |
