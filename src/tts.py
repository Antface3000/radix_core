"""Text-to-speech - ported from unblocker/tts.js (Google tier dropped).

Two local engines:
  - AllTalk  : POST {url}/api/tts-generate, then download the produced wav
  - Piper    : piper.exe --model voice.onnx --output_file out.wav (stdin text)

Returns base64 wav bytes and can play them locally (winsound on Windows, with a
sounddevice/soundfile fallback on other platforms).
"""

import base64
import os
import subprocess
import tempfile
import uuid

import requests

import config

DEFAULT_ALLTALK_TIMEOUT = 600
DEFAULT_AUDIO_FETCH_TIMEOUT = 60


class TTSError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class TTSClient:
    def __init__(self, settings=None):
        self.settings = settings

    def _get(self, dotted, fallback):
        if self.settings is not None:
            return self.settings.get(dotted, fallback)
        return fallback

    def speak(self, text, play=True):
        """Generate speech for `text`. Returns {data, type, engine} or None."""
        text = str(text or "").strip()
        if not text:
            return None
        engine = self._get("services.tts_engine", config.TTS_ENGINE)
        if engine == "off":
            return None
        if engine == "piper":
            result = self._speak_piper(text)
        elif engine == "alltalk":
            result = self._speak_alltalk(text)
        else:  # auto: alltalk then piper
            try:
                result = self._speak_alltalk(text)
            except Exception:
                result = self._speak_piper(text)
        if play and result:
            self.play(result["data"])
        return result

    def _speak_alltalk(self, text):
        base = str(self._get("services.alltalk_url", config.ALLTALK_URL)).rstrip("/")
        voice = self._get("services.tts_voice", config.TTS_VOICE) or "female_01.wav"
        params = {
            "text_input": text,
            "text_filtering": "standard",
            "character_voice_gen": voice,
            "narrator_enabled": "false",
            "narrator_voice_gen": voice,
            "text_not_inside": "character",
            "language": "en",
            "output_file_name": "radix_tts",
            "output_file_timestamp": "true",
            "autoplay": "false",
            "autoplay_volume": "0.8",
        }
        try:
            r = requests.post(f"{base}/api/tts-generate", data=params,
                              timeout=DEFAULT_ALLTALK_TIMEOUT)
        except requests.RequestException as exc:
            raise TTSError("TTS_NETWORK", f"AllTalk unreachable at {base}: {exc}")
        if not r.ok:
            raise TTSError("TTS_BAD_RESPONSE", f"AllTalk {r.status_code}: {r.text[:300]}")
        data = r.json()
        if data.get("status") != "generate-success":
            raise TTSError("TTS_FAILED", "AllTalk generation failed: " + str(data.get("status")))
        raw_url = data.get("output_file_url") or data.get("output_file_path") or ""
        if not raw_url:
            raise TTSError("TTS_NO_AUDIO", "AllTalk returned no audio URL.")
        if raw_url.lower().startswith(("http://", "https://")):
            audio_url = raw_url
        else:
            audio_url = base + (raw_url if raw_url.startswith("/") else "/" + raw_url)
        ar = requests.get(audio_url, timeout=DEFAULT_AUDIO_FETCH_TIMEOUT)
        ar.raise_for_status()
        return {"data": base64.b64encode(ar.content).decode("ascii"),
                "type": "audio/wav", "engine": "alltalk"}

    def _speak_piper(self, text):
        piper = os.path.abspath(self._get("services.piper_exe", config.PIPER_EXE))
        voice = os.path.abspath(self._get("services.piper_voice", config.PIPER_VOICE))
        if not os.path.exists(piper):
            raise TTSError("TTS_NO_PIPER", "Piper binary not found. See README setup.")
        if not os.path.exists(voice):
            raise TTSError("TTS_NO_VOICE", "Piper voice model not found. See README setup.")
        tmp = os.path.join(tempfile.gettempdir(), f"radix_tts_{uuid.uuid4().hex[:8]}.wav")
        proc = subprocess.run([piper, "--model", voice, "--output_file", tmp],
                              input=text.encode("utf-8"),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0 or not os.path.exists(tmp):
            raise TTSError("TTS_PIPER_FAILED",
                           f"Piper failed: {proc.stderr.decode('utf-8', 'ignore')[:300]}")
        with open(tmp, "rb") as f:
            audio = f.read()
        try:
            os.remove(tmp)
        except OSError:
            pass
        return {"data": base64.b64encode(audio).decode("ascii"),
                "type": "audio/wav", "engine": "piper"}

    @staticmethod
    def play(b64_wav):
        """Play a base64-encoded wav. Non-blocking on Windows (SND_ASYNC)."""
        try:
            raw = base64.b64decode(b64_wav)
        except (ValueError, TypeError):
            return False
        tmp = os.path.join(tempfile.gettempdir(), f"radix_play_{uuid.uuid4().hex[:8]}.wav")
        with open(tmp, "wb") as f:
            f.write(raw)
        try:
            import winsound  # Windows
            winsound.PlaySound(tmp, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return True
        except Exception:
            pass
        try:
            import soundfile as sf
            import sounddevice as sd
            data, samplerate = sf.read(tmp)
            sd.play(data, samplerate)
            return True
        except Exception:
            return False
