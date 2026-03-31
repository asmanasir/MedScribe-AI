from __future__ import annotations

"""
WebSocket endpoint for real-time streaming transcription.

Protocol:
  Client → Server: binary audio chunks (PCM 16-bit, 16kHz, mono)
  Server → Client: JSON messages:
    {"type": "partial", "text": "cumulative text so far", "segment": "latest chunk"}
    {"type": "final", "text": "complete transcript", "is_final": true}
    {"type": "error", "message": "..."}

Usage from browser:
  const ws = new WebSocket("ws://localhost:8000/api/v1/ws/transcribe?language=no");
  ws.onmessage = (e) => { const data = JSON.parse(e.data); updateUI(data.text); };
  // Send audio chunks from MediaRecorder/AudioWorklet
  ws.send(audioChunkArrayBuffer);
  // When done:
  ws.send(JSON.stringify({type: "stop"}));
"""

import asyncio
import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from medscribe.config import get_settings
from medscribe.services.stt_streaming import StreamingTranscriber

logger = structlog.get_logger()
router = APIRouter()

# Shared transcriber instance (model loaded once)
_transcriber: StreamingTranscriber | None = None


def get_transcriber() -> StreamingTranscriber:
    global _transcriber
    if _transcriber is None:
        _transcriber = StreamingTranscriber(get_settings())
    return _transcriber


@router.websocket("/api/v1/ws/transcribe")
async def websocket_transcribe(ws: WebSocket):
    """
    Real-time streaming transcription via WebSocket.

    Query params:
      ?language=no  (default: Norwegian)

    Send binary audio data (PCM 16-bit 16kHz mono).
    Send JSON {"type": "stop"} to end the stream.
    """
    await ws.accept()
    language = ws.query_params.get("language", "no")

    logger.info("ws.transcribe.connected", language=language)

    transcriber = get_transcriber()
    audio_queue: asyncio.Queue = asyncio.Queue()

    async def receive_audio():
        """Receive audio chunks from client and put into queue."""
        try:
            while True:
                data = await ws.receive()

                if data.get("type") == "websocket.disconnect":
                    await audio_queue.put(None)
                    break

                if "bytes" in data:
                    await audio_queue.put(data["bytes"])
                elif "text" in data:
                    msg = json.loads(data["text"])
                    if msg.get("type") == "stop":
                        await audio_queue.put(None)
                        break
        except WebSocketDisconnect:
            await audio_queue.put(None)
        except Exception as e:
            logger.error("ws.transcribe.receive_error", error=str(e))
            await audio_queue.put(None)

    async def send_transcriptions():
        """Transcribe audio from queue and send results to client."""
        try:
            async for result in transcriber.transcribe_stream(audio_queue, language=language):
                await ws.send_json(result)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error("ws.transcribe.send_error", error=str(e))
            try:
                await ws.send_json({"type": "error", "message": str(e)})
            except Exception:
                pass

    # Run receiver and transcriber concurrently
    receive_task = asyncio.create_task(receive_audio())
    send_task = asyncio.create_task(send_transcriptions())

    await asyncio.gather(receive_task, send_task)

    logger.info("ws.transcribe.disconnected")
