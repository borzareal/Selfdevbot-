"""Synthèse vocale ElevenLabs : transforme les réponses du coach en messages vocaux Telegram."""

import re

import httpx

API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
MAX_CHARS = 2500  # au-delà, le vocal serait trop long (et coûteux) : on répond en texte

_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def clean_for_speech(text: str) -> str:
    """Retire ce qui se lit mal à voix haute : emojis, gras/italique Markdown, puces."""
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"[*_#`]", "", text)
    text = re.sub(r"^\s*[-•]\s*", "", text, flags=re.MULTILINE)
    return re.sub(r"[ \t]+", " ", text).strip()


class Voice:
    def __init__(self, api_key: str, voice_id: str, model: str):
        self.api_key = api_key
        self.voice_id = voice_id
        self.model = model

    async def synthesize(self, text: str) -> bytes:
        """Renvoie un MP3 (Telegram l'affiche comme un vocal)."""
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                API_URL.format(voice_id=self.voice_id),
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": self.api_key},
                json={"text": clean_for_speech(text), "model_id": self.model},
            )
            resp.raise_for_status()
            return resp.content
