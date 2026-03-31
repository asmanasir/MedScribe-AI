from __future__ import annotations

"""
Audio format conversion — handles browser WebM → WAV conversion.

Problem: Browsers record audio as WebM (Opus codec).
         Whisper needs WAV (PCM 16-bit, 16kHz, mono).

Solution: Use ffmpeg to convert any audio format to Whisper-compatible WAV.
           If ffmpeg is not available, fall back to raw bytes (may fail for WebM).
"""

import os
import subprocess
import tempfile

import structlog

logger = structlog.get_logger()


def convert_to_wav(audio_data: bytes, source_format: str = "webm") -> bytes:
    """
    Convert any audio format to WAV (16kHz, mono, 16-bit PCM).

    This is critical because browsers send WebM/Opus from MediaRecorder,
    but Whisper expects WAV format.
    """
    input_path = None
    output_path = None

    try:
        # Write input to temp file
        with tempfile.NamedTemporaryFile(suffix=f".{source_format}", delete=False) as tmp:
            tmp.write(audio_data)
            input_path = tmp.name

        # Output WAV path
        output_path = input_path.rsplit(".", 1)[0] + ".wav"

        # Convert with ffmpeg
        cmd = [
            "ffmpeg", "-y",       # Overwrite output
            "-i", input_path,     # Input file
            "-ar", "16000",       # 16kHz sample rate (what Whisper expects)
            "-ac", "1",           # Mono
            "-sample_fmt", "s16", # 16-bit PCM
            output_path,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.warning(
                "audio.convert_failed",
                stderr=result.stderr.decode()[:200],
                source_format=source_format,
            )
            # Fall back to raw bytes
            return audio_data

        with open(output_path, "rb") as f:
            wav_data = f.read()

        logger.info(
            "audio.converted",
            source_format=source_format,
            input_size=len(audio_data),
            output_size=len(wav_data),
        )

        return wav_data

    except FileNotFoundError:
        logger.warning("audio.ffmpeg_not_found")
        return audio_data

    except Exception as e:
        logger.error("audio.convert_error", error=str(e))
        return audio_data

    finally:
        if input_path and os.path.exists(input_path):
            os.unlink(input_path)
        if output_path and os.path.exists(output_path):
            os.unlink(output_path)


def detect_format(filename: str) -> str:
    """Detect audio format from filename."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "webm"
    return ext
