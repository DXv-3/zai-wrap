"""Input validation and path security."""
from __future__ import annotations

import json
import plistlib
import re
from pathlib import Path
from typing import Any

VOICE_NAME_RE = re.compile(r"^[\w\s().-]{1,64}$", re.UNICODE)
SIRI_VOICE_UI_ALIASES = frozenset(
    {"siri voice 2", "siri voice2", "siri 2", "siri voice ii", "siri voice two"}
)
SIRI_VOICE_UI_RE = re.compile(r"^siri\s*(voice\s*)?2\b", re.IGNORECASE)
SESSION_ID_RE = re.compile(r"^[a-f0-9-]{8,64}$", re.IGNORECASE)
EVENT_KIND_RE = re.compile(r"^[\w.-]{1,32}$")
STT_LANG_RE = re.compile(r"^[a-z]{2}(-[A-Za-z]{2,8})?$")
SPEECH_PREFS_PATH = Path.home() / "Library/Preferences/com.apple.speech.voice.prefs.plist"


def clamp_int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def sanitize_voice_name(voice: str) -> str | None:
    v = (voice or "").strip()
    if not v or not VOICE_NAME_RE.match(v):
        return None
    return v


def sanitize_session_id(session_id: str | None) -> str | None:
    s = (session_id or "").strip()
    return s if s and SESSION_ID_RE.match(s) else None


def sanitize_event_kind(kind: str) -> str:
    k = (kind or "note").strip()[:32]
    return k if EVENT_KIND_RE.match(k) else "note"


def sanitize_snapshot_name(name: str) -> str:
    base = Path(name).name or "dropped-terminal.txt"
    base = re.sub(r"[^\w.\-]", "_", base)[:120]
    return base or "dropped-terminal.txt"


def parse_json_object(raw: bytes) -> dict[str, Any] | None:
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def is_path_under(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def load_speech_prefs() -> dict[str, Any]:
    if not SPEECH_PREFS_PATH.is_file():
        return {}
    try:
        with SPEECH_PREFS_PATH.open("rb") as f:
            data = plistlib.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, plistlib.InvalidFileException, ValueError):
        return {}


def is_siri_voice_ui_label(voice: str) -> bool:
    q = (voice or "").strip().lower()
    return q in SIRI_VOICE_UI_ALIASES or bool(SIRI_VOICE_UI_RE.match(q))


def spoken_content_selected_voice(prefs: dict[str, Any] | None = None) -> str | None:
    prefs = prefs if prefs is not None else load_speech_prefs()
    name = prefs.get("SelectedVoiceName")
    if isinstance(name, str):
        return sanitize_voice_name(name)
    return None


def spoken_content_rate(prefs: dict[str, Any] | None = None) -> int | None:
    prefs = prefs if prefs is not None else load_speech_prefs()
    creator = prefs.get("SelectedVoiceCreator")
    voice_id = prefs.get("SelectedVoiceID")
    rows = prefs.get("VoiceRateDataArray")
    if creator is None or voice_id is None or not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) >= 3:
            if row[0] == creator and row[1] == voice_id:
                return clamp_int(row[2], 190, 80, 400)
    return None


def resolve_tts_voice(requested: str, prefs: dict[str, Any] | None = None) -> dict[str, Any]:
    prefs = prefs if prefs is not None else load_speech_prefs()
    requested = sanitize_voice_name(requested) or "Siri Voice 2"
    meta: dict[str, Any] = {
        "requested": requested,
        "resolved": requested,
        "source": "requested",
        "spoken_content": spoken_content_selected_voice(prefs),
    }
    if not is_siri_voice_ui_label(requested):
        return meta
    selected = meta["spoken_content"]
    if selected:
        meta["resolved"] = selected
        meta["source"] = "spoken_content"
        meta["label"] = "Siri Voice 2"
        return meta
    log = prefs.get("SpeechDataInstallationLog")
    if isinstance(log, dict):
        for voice_key, info in log.items():
            if not isinstance(info, dict) or not info.get("SuccessfulDate"):
                continue
            bundle = str(info.get("BundleIdentifier") or voice_key)
            if "custom.siri" not in bundle.lower() or "premium" not in bundle.lower():
                continue
            slug = bundle.rsplit(".", 1)[-1].replace(".premium", "")
            for candidate in (f"{slug} (Enhanced)", slug.capitalize(), slug):
                c = sanitize_voice_name(candidate)
                if c:
                    meta["resolved"] = c
                    meta["source"] = "siri_premium_bundle"
                    meta["label"] = "Siri Voice 2"
                    return meta
    return meta