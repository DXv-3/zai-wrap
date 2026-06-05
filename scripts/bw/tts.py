"""macOS text-to-speech via say(1), optional external clone backend."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
import threading
from typing import Any

from bw.cache import TTLCache
from bw.constants import DEFAULT_SETTINGS, MAX_TTS_INPUT
from bw.security import (
    is_siri_voice_ui_label,
    load_speech_prefs,
    resolve_tts_voice,
    sanitize_voice_name,
    spoken_content_rate,
    clamp_int,
)

_voice_list_cache = TTLCache(ttl_sec=300.0)
_voice_works: dict[str, bool] = {}
_voice_lock = threading.Lock()
_tts_lock = threading.Lock()
_tts_stop = threading.Event()
_tts_proc: subprocess.Popen[str] | None = None


def parse_say_voices() -> list[str]:
    try:
        r = subprocess.run(
            ["say", "-v", "?"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    voices: list[str] = []
    for line in (r.stdout or "").splitlines():
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        m = re.match(r"^(.+?)\s{2,}[a-z]{2}_[A-Z]{2}\b", line.strip())
        if m:
            voices.append(m.group(1).strip())
    return voices


def voice_works(voice: str) -> bool:
    if not sanitize_voice_name(voice):
        return False
    with _voice_lock:
        if voice in _voice_works:
            return _voice_works[voice]
    if voice in _voice_list_cache.get(parse_say_voices):
        ok = True
    else:
        ok = _probe_voice(voice)
    with _voice_lock:
        _voice_works[voice] = ok
        if len(_voice_works) > 64:
            _voice_works.clear()
    return ok


def _probe_voice(voice: str) -> bool:
    try:
        with tempfile.NamedTemporaryFile(suffix=".aiff", delete=True) as probe:
            return (
                subprocess.run(
                    ["say", "-v", voice, "-o", probe.name, "ok"],
                    capture_output=True,
                    timeout=12,
                ).returncode
                == 0
            )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def strip_for_tts(text: str) -> str:
    t = text or ""
    t = re.sub(r"```[\s\S]*?```", " ", t)
    t = re.sub(r"`[^`]+`", " ", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"[#*_>]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:20_000]


def tts_chunks(text: str, max_len: int = 400) -> list[str]:
    clean = strip_for_tts(text)
    if not clean:
        return []
    parts = re.split(r"\n\s*\n", clean)
    chunks: list[str] = []
    buf = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(part) > max_len:
            if buf:
                chunks.append(buf)
                buf = ""
            for i in range(0, len(part), max_len):
                chunks.append(part[i : i + max_len])
            continue
        if len(buf) + len(part) + 1 > max_len:
            if buf:
                chunks.append(buf)
            buf = part
        else:
            buf = f"{buf} {part}".strip() if buf else part
    if buf:
        chunks.append(buf)
    return chunks or [clean[:max_len]]


def tts_stop() -> None:
    global _tts_proc
    _tts_stop.set()
    with _tts_lock:
        proc = _tts_proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        _tts_proc = None


def tts_status() -> bool:
    with _tts_lock:
        return _tts_proc is not None and _tts_proc.poll() is None


def _tts_backend() -> str:
    return (os.environ.get("BUILD_WATCH_TTS_BACKEND") or "say").strip().lower()


def _tts_external(text: str, settings: dict[str, Any]) -> dict[str, Any]:
    """Run BUILD_WATCH_TTS_CMD with text on stdin (voice cloning hook)."""
    cmd = (os.environ.get("BUILD_WATCH_TTS_CMD") or "").strip()
    if not cmd:
        return {"ok": False, "error": "tts_cmd_unset"}
    chunks = tts_chunks(text)
    if not chunks:
        return {"ok": False, "error": "empty_text"}
    env = os.environ.copy()
    ref = (settings.get("voice_ref") or env.get("BUILD_WATCH_VOICE_REF") or "").strip()
    if ref:
        env["BUILD_WATCH_VOICE_REF"] = ref
    rate = settings.get("tts_rate")
    if rate is not None:
        env["BUILD_WATCH_TTS_RATE"] = str(rate)
    tts_stop()
    _tts_stop.clear()
    argv = shlex.split(cmd)

    def worker() -> None:
        for chunk in chunks:
            if _tts_stop.is_set():
                break
            try:
                subprocess.run(
                    argv,
                    input=chunk,
                    text=True,
                    env=env,
                    timeout=120,
                    check=False,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                return

    threading.Thread(target=worker, daemon=True).start()
    return {
        "ok": True,
        "backend": "external",
        "cmd": cmd,
        "voice_ref": ref or None,
        "chunks": len(chunks),
    }


def tts_speak(
    text: str,
    settings: dict[str, Any],
    *,
    voice: str | None = None,
    rate: int | None = None,
) -> dict[str, Any]:
    text = (text or "")[:MAX_TTS_INPUT]
    if _tts_backend() == "external" or os.environ.get("BUILD_WATCH_TTS_CMD"):
        return _tts_external(text, settings)
    raw_voice = voice or str(settings.get("tts_voice") or "Siri Voice 2")
    prefs = load_speech_prefs()
    vmeta = resolve_tts_voice(raw_voice, prefs)
    say_voice = sanitize_voice_name(str(vmeta.get("resolved") or "")) or "Siri Voice 2"
    default_rate = settings.get("tts_rate")
    if rate is None and is_siri_voice_ui_label(raw_voice):
        sys_rate = spoken_content_rate(prefs)
        if sys_rate is not None and default_rate == DEFAULT_SETTINGS["tts_rate"]:
            rate = sys_rate
    rate = clamp_int(rate if rate is not None else default_rate, 190, 80, 400)
    if not voice_works(say_voice):
        return {
            "ok": False,
            "error": "voice_not_installed",
            "voice": say_voice,
            "requested_voice": vmeta.get("requested"),
            "spoken_content_voice": vmeta.get("spoken_content"),
            "hint": "Set Siri voice in System Settings → Accessibility → Spoken Content.",
            "available_voices": [v for v in parse_say_voices() if "siri" in v.lower()][:12],
        }
    chunks = tts_chunks(text)
    if not chunks:
        return {"ok": False, "error": "empty_text"}

    tts_stop()
    _tts_stop.clear()

    def worker() -> None:
        global _tts_proc
        for chunk in chunks:
            if _tts_stop.is_set():
                break
            with _tts_lock:
                if _tts_stop.is_set():
                    break
                try:
                    _tts_proc = subprocess.Popen(
                        ["say", "-v", say_voice, "-r", str(rate), chunk],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except FileNotFoundError:
                    return
            if _tts_proc:
                _tts_proc.wait()

    threading.Thread(target=worker, daemon=True).start()
    out: dict[str, Any] = {
        "ok": True,
        "voice": say_voice,
        "requested_voice": vmeta.get("requested"),
        "rate": rate,
        "chunks": len(chunks),
    }
    if vmeta.get("source") != "requested":
        out["tts_label"] = vmeta.get("label") or "Siri Voice 2"
        out["voice_source"] = vmeta.get("source")
    return out


def siri_available() -> bool:
    resolved = resolve_tts_voice("Siri Voice 2")
    return voice_works(str(resolved.get("resolved") or ""))