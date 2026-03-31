# CE/MDR Compliance Documentation — MedScribe AI

## Regulatory Classification

MedScribe AI is classified as a **Class I medical device** under EU MDR 2017/745,
following the same classification as Vidd Medical.

**Justification:** The software provides clinical documentation assistance (speech-to-text
and text structuring) but does NOT:
- Make diagnostic decisions
- Recommend treatments
- Control medical devices
- Process physiological signals for diagnosis

All outputs are **draft documents** requiring human review and approval.

## Required Documentation (MDR Annex I-III)

### Technical Documentation (Annex II)

| Document | Status | Description |
|----------|--------|-------------|
| Device Description | ✅ Done | See `device_description.md` |
| Intended Purpose | ✅ Done | See `intended_purpose.md` |
| Risk Management | ✅ Done | See `risk_management.md` |
| Software Lifecycle | ✅ Done | See `software_lifecycle.md` |
| Clinical Evaluation | ⬜ Todo | Literature review + usability study |
| Labeling | ⬜ Todo | Instructions for Use (IFU) |
| Post-Market Surveillance | ⬜ Todo | Incident reporting plan |

### Quality Management System (Annex IX)
- ISO 13485 alignment recommended
- Design control procedures documented in `software_lifecycle.md`
