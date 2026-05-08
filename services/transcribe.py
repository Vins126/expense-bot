import httpx
from groq import Groq
from config import GROQ_API_KEY

_client = Groq(api_key=GROQ_API_KEY)


async def transcribe_audio(audio_bytes: bytes, filename: str = "audio.ogg") -> str:
    """Transcribes audio bytes using Groq Whisper. Returns Italian text."""
    transcription = _client.audio.transcriptions.create(
        file=(filename, audio_bytes),
        model="whisper-large-v3",
        language="it",
        response_format="text",
    )
    return transcription.strip()


async def download_telegram_file(file_url: str) -> bytes:
    """Downloads a file from Telegram's servers."""
    async with httpx.AsyncClient() as client:
        response = await client.get(file_url, timeout=30)
        response.raise_for_status()
        return response.content
