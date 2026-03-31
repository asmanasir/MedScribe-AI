from __future__ import annotations

"""
EPJ Bridge API — endpoints that connect MedScribe to the EPJ.

These endpoints let the EPJ system drive MedScribe's AI pipeline
and receive results in the exact format the EPJ expects.

Flow:
  EPJ opens AI window → POST /epj/session/start
  EPJ sends audio     → POST /epj/session/{id}/audio
  MedScribe processes  → sends status messages back
  Note ready           → POST /epj/session/{id}/transfer (returns SmartWebMessage)
  EPJ closes patient   → POST /epj/session/{id}/close
"""

from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from medscribe.api.auth import AuthenticatedUser, get_current_user
from medscribe.integration.epj_bridge import EPJBridge, EPJMessageType, EPJSmartWebMessage

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/epj", tags=["EPJ Integration"])

# In-memory session store (production: use Redis)
_sessions: dict[str, dict] = {}


class EPJSessionRequest(BaseModel):
    patient_id: str = Field(description="EPJ Patient GUID")
    consultation_id: str = Field(description="EPJ Consultation/Encounter GUID")
    user_id: str = Field(description="EPJ Practitioner GUID")


class EPJNoteTransferRequest(BaseModel):
    note_text: str = Field(description="Clinical note text to transfer to EPJ")


@router.post("/session/start")
async def start_epj_session(
    request: EPJSessionRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Start an AI assistant session for a consultation.

    Called when the doctor activates the AI assistant in the EPJ.
    Returns a session ID and the initial status message.
    """
    session_id = str(uuid4())
    _sessions[session_id] = {
        "patient_id": request.patient_id,
        "consultation_id": request.consultation_id,
        "user_id": request.user_id,
        "status": "ready",
    }

    bridge = EPJBridge()
    msg = bridge.on_recording_started(
        request.patient_id, request.consultation_id, request.user_id,
    )

    return {
        "session_id": session_id,
        "status": "ready",
        "epj_message": msg,
    }


@router.post("/session/{session_id}/status/{status}")
async def update_session_status(
    session_id: str,
    status: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Send a status update to the EPJ.

    Valid statuses: recording, paused, stopped, transcribing, done
    Returns the SmartWebMessage that the EPJ expects.
    """
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    status_map = {
        "recording": EPJMessageType.STATUS_RECORDING,
        "paused": EPJMessageType.STATUS_PAUSED,
        "stopped": EPJMessageType.STATUS_STOPPED,
        "transcribing": EPJMessageType.STATUS_TRANSCRIBING,
        "done": EPJMessageType.UI_DONE,
    }

    msg_type = status_map.get(status)
    if not msg_type:
        raise HTTPException(status_code=400, detail=f"Unknown status: {status}")

    session["status"] = status
    msg = EPJSmartWebMessage.build_status(
        msg_type,
        patient_id=session["patient_id"],
        consultation_id=session["consultation_id"],
        user_id=session["user_id"],
    )

    return {"status": status, "epj_message": msg}


@router.post("/session/{session_id}/transfer")
async def transfer_note_to_epj(
    session_id: str,
    request: EPJNoteTransferRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Transfer a clinical note to the EPJ system.

    Returns the EXACT SmartWebMessage format that the EPJ's
    SmartWebMessageHandler.cs parses. The EPJ will:
    1. Validate the FHIR DocumentReference
    2. Extract the note text from base64 content
    3. Append it to the consultation note via TextAppendedToNoteEvent
    4. Show a toast: "Notat mottatt"
    """
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    msg = EPJSmartWebMessage.build_text_transfer(
        patient_id=session["patient_id"],
        consultation_id=session["consultation_id"],
        user_id=session["user_id"],
        note_text=request.note_text,
    )

    session["status"] = "transferred"

    logger.info(
        "epj.note_transferred",
        session_id=session_id,
        consultation_id=session["consultation_id"],
        text_length=len(request.note_text),
    )

    return {
        "status": "transferred",
        "epj_message": msg,
        "note_length": len(request.note_text),
    }


@router.post("/session/{session_id}/close")
async def close_epj_session(
    session_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Close the AI session and signal EPJ to discard data.

    Called when the patient is closed in the EPJ.
    Sends PatientClose message so EPJ discards any cached data.
    """
    session = _sessions.pop(session_id, None)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    msg = EPJSmartWebMessage.build_status(
        EPJMessageType.PATIENT_CLOSE,
        patient_id=session["patient_id"],
        consultation_id=session["consultation_id"],
        user_id=session["user_id"],
    )

    return {"status": "closed", "epj_message": msg}


@router.get("/message-types")
async def list_message_types():
    """List all supported EPJ message types and their descriptions."""
    return {
        "from_medscribe_to_epj": {
            EPJMessageType.TEXT_TRANSFER: "Note text transferred to EPJ (scratchpad.update)",
            EPJMessageType.STATUS_RECORDING: "Recording started",
            EPJMessageType.STATUS_PAUSED: "Recording paused",
            EPJMessageType.STATUS_STOPPED: "Recording stopped",
            EPJMessageType.STATUS_TRANSCRIBING: "AI is processing audio",
            EPJMessageType.UI_DONE: "Processing complete",
            EPJMessageType.DOCUMENT_STARTED: "Document transcription started",
            EPJMessageType.DOCUMENT_CONFIRMED: "Document confirmed by user",
        },
        "from_epj_to_medscribe": {
            EPJMessageType.PATIENT_CLOSE: "Patient closed — discard all data",
            EPJMessageType.PATIENT_PAUSE: "Pause recording",
        },
    }
