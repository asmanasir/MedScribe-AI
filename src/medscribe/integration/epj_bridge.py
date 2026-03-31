from __future__ import annotations

"""
EPJ Bridge — makes MedScribe a drop-in replacement for Vidd in WebMed/TNW.

This module implements the EXACT message protocol used between Vidd and
the WebMed EPJ system (TNW). Reverse-engineered from:
- SmartWebMessageHandler.cs
- SmartWebMessageResult.cs
- AiAssistantOrchestrator.cs

Message format (JSON):
{
    "messageId": "unique-id",
    "messageType": "scratchpad.update",   // See MESSAGE_TYPES below
    "messagingHandle": "Bearer <token>",  // Auth token
    "payload": {
        "resource": { FHIR DocumentReference JSON }
    }
}

Message types (from SmartWebMessageResult.cs):
    "scratchpad.update"     → TextTransfer (note text to EPJ)
    "status.recording"      → Recording started
    "status.paused"         → Recording paused
    "status.stopped"        → Recording stopped
    "status.transcribing"   → AI is processing
    "ui.done"               → Finished
    "document.started"      → Transcription started
    "document.confirmed"    → User confirmed/rejected note
    "patient.close"         → Patient session closed (discard data)
    "patient.pause"         → Pause recording

FHIR DocumentReference requirements (from SmartWebMessageHandler.cs):
- subject.reference = "Patient/{patientId}"
- context.encounter[0].reference = "Encounter/{consultationId}"
- author[0].reference = "Practitioner/{userId}"
- content[0].attachment.data = base64(noteText)
"""

import base64
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog

logger = structlog.get_logger()


# Exact message types from SmartWebMessageResult.cs
class EPJMessageType:
    TEXT_TRANSFER = "scratchpad.update"
    STATUS_RECORDING = "status.recording"
    STATUS_PAUSED = "status.paused"
    STATUS_STOPPED = "status.stopped"
    STATUS_TRANSCRIBING = "status.transcribing"
    UI_DONE = "ui.done"
    DOCUMENT_STARTED = "document.started"
    DOCUMENT_CONFIRMED = "document.confirmed"
    PATIENT_CLOSE = "patient.close"
    PATIENT_PAUSE = "patient.pause"


class EPJSmartWebMessage:
    """
    Builds SmartWebMessage JSON exactly as the EPJ expects it.

    This is the message format that WebMed's SmartWebMessageHandler.cs parses.
    Every field must match exactly or the message will be rejected.
    """

    @staticmethod
    def build(
        message_type: str,
        *,
        patient_id: str,
        consultation_id: str,
        user_id: str,
        note_text: str = "",
        token: str = "",
        message_id: str | None = None,
    ) -> dict:
        """
        Build a SmartWebMessage that the EPJ's AiAssistantOrchestrator can process.

        Args:
            message_type: One of EPJMessageType constants
            patient_id: EPJ patient GUID
            consultation_id: EPJ consultation GUID
            user_id: EPJ user/practitioner GUID
            note_text: Clinical note text (for TextTransfer)
            token: Bearer token for authentication
            message_id: Unique message ID (auto-generated if not provided)
        """
        mid = message_id or str(uuid4())

        # Build FHIR DocumentReference exactly as SmartWebMessageHandler expects
        doc_ref = {
            "resourceType": "DocumentReference",
            "status": "current",
            "subject": {
                "reference": f"Patient/{patient_id}",
            },
            "context": {
                "encounter": [{
                    "reference": f"Encounter/{consultation_id}",
                }],
            },
            "author": [{
                "reference": f"Practitioner/{user_id}",
                "identifier": {
                    "system": "WebMed:Practitioner",
                    "value": str(user_id),
                },
            }],
            "content": [{
                "attachment": {
                    "contentType": "text/plain",
                    "data": base64.b64encode(note_text.encode("utf-8")).decode("ascii") if note_text else "",
                },
            }],
            "type": {
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "code": "371530004",
                }],
                "text": "Clinical consultation report",
            },
            "category": [{
                "coding": [{
                    "system": "http://hl7.no/fhir/CodeSystem/no-helseapi-documentreference-category",
                    "code": "clinical-note",
                }],
                "text": "Clinical Note",
            }],
        }

        return {
            "messageId": mid,
            "messageType": message_type,
            "messagingHandle": f"Bearer {token}",
            "payload": {
                "resource": doc_ref,
            },
        }

    @staticmethod
    def build_text_transfer(
        *,
        patient_id: str,
        consultation_id: str,
        user_id: str,
        note_text: str,
        token: str = "",
    ) -> dict:
        """Build a text transfer message — sends the clinical note to EPJ."""
        return EPJSmartWebMessage.build(
            EPJMessageType.TEXT_TRANSFER,
            patient_id=patient_id,
            consultation_id=consultation_id,
            user_id=user_id,
            note_text=note_text,
            token=token,
        )

    @staticmethod
    def build_status(
        message_type: str,
        *,
        patient_id: str,
        consultation_id: str,
        user_id: str,
        token: str = "",
    ) -> dict:
        """Build a status message (recording, paused, transcribing, etc.)."""
        return EPJSmartWebMessage.build(
            message_type,
            patient_id=patient_id,
            consultation_id=consultation_id,
            user_id=user_id,
            token=token,
        )


class EPJBridge:
    """
    High-level bridge between MedScribe pipeline and the EPJ system.

    Manages the full lifecycle:
    1. Consultation starts → send DocumentStarted
    2. Recording starts → send StatusRecording
    3. Recording stops → send StatusStopped
    4. Transcribing → send StatusTranscribing
    5. Note ready → send TextTransfer with FHIR DocumentReference
    6. Done → send UiDone
    7. Patient closes → send PatientClose (EPJ discards data)

    Usage:
        bridge = EPJBridge(send_callback)
        bridge.on_recording_started(patient_id, consultation_id, user_id)
        bridge.on_transcribing(patient_id, consultation_id, user_id)
        bridge.on_note_ready(patient_id, consultation_id, user_id, note_text)
        bridge.on_done(patient_id, consultation_id, user_id)
    """

    def __init__(self, send_fn=None):
        """
        Args:
            send_fn: async function that sends the message to the EPJ.
                     Signature: async def send(message: dict) -> bool
                     In production: WebSocket or HTTP POST to EPJ.
                     In dev: logs the message.
        """
        self._send = send_fn or self._log_message
        self._token = ""

    def set_token(self, token: str):
        self._token = token

    def on_recording_started(self, patient_id: str, consultation_id: str, user_id: str) -> dict:
        msg = EPJSmartWebMessage.build_status(
            EPJMessageType.STATUS_RECORDING,
            patient_id=patient_id, consultation_id=consultation_id,
            user_id=user_id, token=self._token,
        )
        logger.info("epj_bridge.recording_started", consultation_id=consultation_id)
        return msg

    def on_recording_paused(self, patient_id: str, consultation_id: str, user_id: str) -> dict:
        msg = EPJSmartWebMessage.build_status(
            EPJMessageType.STATUS_PAUSED,
            patient_id=patient_id, consultation_id=consultation_id,
            user_id=user_id, token=self._token,
        )
        logger.info("epj_bridge.recording_paused", consultation_id=consultation_id)
        return msg

    def on_recording_stopped(self, patient_id: str, consultation_id: str, user_id: str) -> dict:
        msg = EPJSmartWebMessage.build_status(
            EPJMessageType.STATUS_STOPPED,
            patient_id=patient_id, consultation_id=consultation_id,
            user_id=user_id, token=self._token,
        )
        logger.info("epj_bridge.recording_stopped", consultation_id=consultation_id)
        return msg

    def on_transcribing(self, patient_id: str, consultation_id: str, user_id: str) -> dict:
        msg = EPJSmartWebMessage.build_status(
            EPJMessageType.STATUS_TRANSCRIBING,
            patient_id=patient_id, consultation_id=consultation_id,
            user_id=user_id, token=self._token,
        )
        logger.info("epj_bridge.transcribing", consultation_id=consultation_id)
        return msg

    def on_note_ready(self, patient_id: str, consultation_id: str, user_id: str, note_text: str) -> dict:
        msg = EPJSmartWebMessage.build_text_transfer(
            patient_id=patient_id, consultation_id=consultation_id,
            user_id=user_id, note_text=note_text, token=self._token,
        )
        logger.info("epj_bridge.note_transferred", consultation_id=consultation_id, text_length=len(note_text))
        return msg

    def on_done(self, patient_id: str, consultation_id: str, user_id: str) -> dict:
        msg = EPJSmartWebMessage.build_status(
            EPJMessageType.UI_DONE,
            patient_id=patient_id, consultation_id=consultation_id,
            user_id=user_id, token=self._token,
        )
        logger.info("epj_bridge.done", consultation_id=consultation_id)
        return msg

    def on_patient_close(self, patient_id: str, consultation_id: str, user_id: str) -> dict:
        msg = EPJSmartWebMessage.build_status(
            EPJMessageType.PATIENT_CLOSE,
            patient_id=patient_id, consultation_id=consultation_id,
            user_id=user_id, token=self._token,
        )
        logger.info("epj_bridge.patient_closed", consultation_id=consultation_id)
        return msg

    @staticmethod
    async def _log_message(message: dict) -> bool:
        logger.info("epj_bridge.message", message_type=message.get("messageType"), message_id=message.get("messageId"))
        return True
