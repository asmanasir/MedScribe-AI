"""
Live Demo — Record audio from microphone → Transcribe → Structure → Review

This script demonstrates the full MedScribe pipeline:
1. Records audio from your microphone (press Enter to stop)
2. Creates a visit via the API
3. Sends audio for transcription (local Whisper — nothing leaves your machine)
4. Structures the transcript into a clinical note (local Ollama)
5. Shows the result for review

Usage:
    python scripts/live_demo.py

Make sure the server is running: python -m medscribe
"""

import io
import json
import os
import sys
import time
import wave

import httpx
import numpy as np
import sounddevice as sd

# --- Config ---
API_URL = "http://localhost:8000"
API_SECRET = os.environ.get("MEDSCRIBE_SECRET_KEY", "dev-secret")
SAMPLE_RATE = 16000  # 16kHz — what Whisper expects
CHANNELS = 1         # Mono — clinical recordings don't need stereo


def get_token() -> str:
    """Get a JWT token from the API."""
    resp = httpx.post(
        f"{API_URL}/api/v1/auth/token",
        json={
            "client_id": "DR001",
            "client_secret": API_SECRET,
            "role": "clinician",
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def record_audio() -> bytes:
    """
    Record audio from the microphone.
    Press Enter to stop recording.
    """
    print("\n" + "=" * 60)
    print("  MICROPHONE RECORDING")
    print("=" * 60)
    print()
    print("  Speak now... (press Enter to stop)")
    print()
    print("  Tip: Simulate a clinical visit:")
    print('  "Patient reports headache for three days,')
    print('   no fever, took paracetamol with mild relief."')
    print()
    print("=" * 60)

    # Record in chunks so we can stop on Enter
    recorded_chunks = []
    recording = True

    def callback(indata, frames, time_info, status):
        if recording:
            recorded_chunks.append(indata.copy())

    # Start recording stream
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        callback=callback,
    )

    stream.start()
    input()  # Wait for Enter
    recording = False
    stream.stop()
    stream.close()

    if not recorded_chunks:
        print("No audio recorded!")
        sys.exit(1)

    # Combine chunks into single array
    audio_data = np.concatenate(recorded_chunks, axis=0)
    duration = len(audio_data) / SAMPLE_RATE
    print(f"\n  Recorded {duration:.1f} seconds of audio")

    # Convert to WAV bytes (what Whisper expects)
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)  # 16-bit = 2 bytes
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_data.tobytes())

    return wav_buffer.getvalue()


def create_visit(client: httpx.Client) -> dict:
    """Create a new visit."""
    resp = client.post(
        f"{API_URL}/api/v1/visits",
        json={
            "patient_id": "P-DEMO-001",
            "clinician_id": "DR001",
            "metadata": {"department": "general", "demo": True},
        },
    )
    resp.raise_for_status()
    return resp.json()


def transcribe(client: httpx.Client, visit_id: str, audio_bytes: bytes) -> dict:
    """Send audio for transcription."""
    resp = client.post(
        f"{API_URL}/api/v1/visits/{visit_id}/transcribe",
        files={"audio": ("recording.wav", audio_bytes, "audio/wav")},
    )
    resp.raise_for_status()
    return resp.json()


def structure(client: httpx.Client, visit_id: str) -> dict:
    """Structure transcript into clinical note."""
    resp = client.post(f"{API_URL}/api/v1/visits/{visit_id}/structure")
    resp.raise_for_status()
    return resp.json()


def get_audit(client: httpx.Client, visit_id: str) -> list:
    """Get audit trail."""
    resp = client.get(f"{API_URL}/api/v1/visits/{visit_id}/audit")
    resp.raise_for_status()
    return resp.json()


def print_section(title: str, content: str):
    """Pretty print a clinical note section."""
    label = title.replace("_", " ").title()
    print(f"  {label}:")
    if content and content != "Not documented.":
        for line in content.split("\n"):
            print(f"    {line}")
    else:
        print(f"    (Not documented)")
    print()


def main():
    print("\n" + "=" * 60)
    print("  MedScribe AI — Live Demo")
    print("  All processing happens locally. No data leaves your machine.")
    print("=" * 60)

    # Check server is running
    try:
        health = httpx.get(f"{API_URL}/health").json()
        print(f"\n  Server: {health['status']}")
        print(f"  LLM:    {'OK' if health['services']['llm'] else 'NOT AVAILABLE'}")
        print(f"  STT:    {'OK' if health['services']['stt'] else 'NOT AVAILABLE'}")
    except httpx.ConnectError:
        print(f"\n  ERROR: Cannot connect to {API_URL}")
        print("  Start the server first: python -m medscribe")
        sys.exit(1)

    if not all(health["services"].values()):
        print("\n  WARNING: Some services are not healthy. Results may be incomplete.")

    # Get token
    print("\n  Authenticating...")
    token = get_token()
    # Don't set Content-Type globally — httpx auto-sets it:
    #   json= requests → application/json
    #   files= requests → multipart/form-data
    # Setting it globally breaks file uploads.
    client = httpx.Client(
        headers={"Authorization": f"Bearer {token}"},
        timeout=300.0,  # LLM can be slow on CPU
    )

    # Step 1: Record audio
    audio_bytes = record_audio()

    # Step 2: Create visit
    print("\n  Creating visit...")
    visit = create_visit(client)
    visit_id = visit["id"]
    print(f"  Visit ID: {visit_id}")
    print(f"  Status:   {visit['status']}")

    # Step 3: Transcribe
    print("\n" + "-" * 60)
    print("  STEP 1: Transcribing audio (local Whisper)...")
    print("-" * 60)
    start = time.time()
    transcript = transcribe(client, visit_id, audio_bytes)
    elapsed = time.time() - start
    print(f"\n  Transcription completed in {elapsed:.1f}s")
    print(f"  Language: {transcript['language']}")
    print(f"  Confidence: {transcript['confidence']:.0%}")
    print(f"\n  Raw transcript:")
    print(f"  \"{transcript['raw_text']}\"")

    # Step 4: Structure
    print("\n" + "-" * 60)
    print("  STEP 2: Structuring into clinical note (local LLM)...")
    print("  (This may take 30-60s on CPU)")
    print("-" * 60)
    start = time.time()
    note = structure(client, visit_id)
    elapsed = time.time() - start
    print(f"\n  Structuring completed in {elapsed:.1f}s")
    print(f"  Model: {note['model_id']}")

    # Step 5: Display structured note
    print("\n" + "=" * 60)
    print("  STRUCTURED CLINICAL NOTE")
    print("=" * 60)
    print()
    for section, content in note["sections"].items():
        print_section(section, content)

    # Step 6: Show audit trail
    print("=" * 60)
    print("  AUDIT TRAIL")
    print("=" * 60)
    audit = get_audit(client, visit_id)
    for entry in audit:
        print(f"  [{entry['timestamp'][:19]}] {entry['action']} by {entry['actor']}")

    # Step 7: Ask for approval
    print("\n" + "=" * 60)
    print("  HUMAN-IN-THE-LOOP")
    print("=" * 60)
    print(f"\n  Visit status: {note['is_approved']}")
    print("  The note requires your approval before being finalized.")
    print()
    approve = input("  Approve this note? (y/n): ").strip().lower()

    if approve == "y":
        resp = client.post(
            f"{API_URL}/api/v1/visits/{visit_id}/approve",
            json={"approved_by": "DR001"},
        )
        if resp.status_code == 200:
            print("\n  NOTE APPROVED")
            print("  The note is now finalized and audit-logged.")
        else:
            print(f"\n  Approval failed: {resp.text}")
    else:
        print("\n  Note NOT approved. It remains in REVIEW state.")
        print("  You can edit it via PUT /api/v1/visits/{visit_id}/note")

    # Final status
    print("\n" + "=" * 60)
    print("  FINAL AUDIT TRAIL")
    print("=" * 60)
    audit = get_audit(client, visit_id)
    for entry in audit:
        print(f"  [{entry['timestamp'][:19]}] {entry['action']} by {entry['actor']}")

    print("\n  Demo complete. All data stayed on your machine.\n")


if __name__ == "__main__":
    main()
