# Device Description — MedScribe AI

## 1. Device Name
MedScribe AI — Clinical Documentation Assistant

## 2. Device Classification
- **MDR Class:** Class I (non-measuring, non-sterile)
- **Rule:** Rule 11 (software intended to provide information used for diagnostic or therapeutic decisions — Class I when providing decision *support* that is reviewed by a qualified professional)
- **GMDN Code:** Clinical documentation software
- **Comparable Device:** Vidd Medical (Class I medical device)

## 3. Description
MedScribe AI is a software-as-a-medical-device (SaMD) that assists healthcare
professionals in creating clinical documentation through:

### 3.1 Speech-to-Text Module
- Converts spoken clinical consultations into draft text
- Uses AI-based automatic speech recognition (Whisper model)
- Supports Norwegian (Bokmål, Nynorsk) and English
- Audio processing can be performed entirely on-premises (local mode)

### 3.2 Text Structuring Module
- Converts unstructured clinical text into structured clinical notes
- Uses Large Language Model (LLM) technology
- Supports multiple clinical note templates (General Practice, Psychiatry, Surgery, Emergency, Pediatrics)
- Output follows standard Norwegian clinical documentation conventions

### 3.3 Workflow Management
- Enforced state machine: Created → Recording → Transcribed → Structured → Review → Approved
- All state transitions are logged in an immutable audit trail
- Notes require explicit human approval before finalization

## 4. Operating Environment
- **Local deployment:** All processing on healthcare facility infrastructure
- **Cloud deployment:** Certified data-processing infrastructure within EU/EEA
- **Integration:** REST API for EPJ/EHR system integration

## 5. Critical Safety Feature
**All outputs are draft documents.** The system explicitly requires human review
and approval by a qualified healthcare professional before any output is used
in clinical practice. This is enforced programmatically — the system cannot
auto-finalize any clinical document.
