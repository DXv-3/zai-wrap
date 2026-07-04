"""circuit_breaker.py  —  SAFETY-04

Per-backend circuit breaker for model_dispatch.py.

States:
  CLOSED    — normal operation
  OPEN      — tripped; API calls blocked until recovery_timeout elapses
  HALF_OPEN — probing; next call is allowed through to test recovery

Configuration via environment variables (all optional):
  BRAIN_CB_FAILURE_THRESHOLD   int   default 3   consecutive failures to trip
  BRAIN_CB_RECOVERY_TIMEOUT    float default 60  seconds before probing
  BRAIN_CB_SUCCESS_THRESHOLD   int   default 1   successes to close from HALF_OPEN

Usage — import once at startup (side-effect import patches model_dispatch):
    import circuit_breaker  # noqa: F401

Or use explicitly:
    from circuit_breaker import get_breaker
    breaker = get_breaker("grok")
    if breaker.allow():
        try:
            result = call_api()
            breaker.record_success()
        except Exception as e:
            breaker.record_failure(str(e))
    else:
        # circuit is open
        ...
"""
from __future__ import annotations

import os
import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _int_env(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


def _float_env(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


FAILURE_THRESHOLD  = _int_env("BRAIN_CB_FAILURE_THRESHOLD", 3)
RECOVERY_TIMEOUT   = _float_env("BRAIN_CB_RECOVERY_TIMEOUT", 60.0)
SUCCESS_THRESHOLD  = _int_env("BRAIN_CB_SUCCESS_THRESHOLD", 1)


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class _State(str, Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    backend: str
    failure_threshold: int  = field(default_factory=lambda: FAILURE_THRESHOLD)
    recovery_timeout:  float = field(default_factory=lambda: RECOVERY_TIMEOUT)
    success_threshold: int  = field(default_factory=lambda: SUCCESS_THRESHOLD)

    _state:             _State = field(default=_State.CLOSED, init=False, repr=False)
    _failure_count:     int    = field(default=0, init=False, repr=False)
    _success_count:     int    = field(default=0, init=False, repr=False)
    _opened_at:         float  = field(default=0.0, init=False, repr=False)
    _lock:              threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    # -- public API ----------------------------------------------------------

    def allow(self) -> bool:
        """Return True if a call should be attempted."""
        with self._lock:
            if self._state == _State.CLOSED:
                return True
            if self._state == _State.OPEN:
                if time.monotonic() - self._opened_at >= self.recovery_timeout:
                    self._state = _State.HALF_OPEN
                    self._success_count = 0
                    return True  # probe call
                return False
            # HALF_OPEN — allow through
            return True

    def record_success(self) -> None:
        with self._lock:
            if self._state == _State.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = _State.CLOSED
                    self._failure_count = 0
                    _notify_bus(self.backend, "circuit_closed")
            elif self._state == _State.CLOSED:
                self._failure_count = 0  # reset on any success

    def record_failure(self, reason: str = "") -> None:
        with self._lock:
            self._failure_count += 1
            if self._state == _State.HALF_OPEN:
                # Failed during probe — re-open
                self._state = _State.OPEN
                self._opened_at = time.monotonic()
                _notify_bus(self.backend, "circuit_reopened", reason)
            elif self._state == _State.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._state = _State.OPEN
                    self._opened_at = time.monotonic()
                    _notify_bus(self.backend, "circuit_opened", reason)

    @property
    def state(self) -> str:
        return self._state.value

    def reset(self) -> None:
        """Force-reset to CLOSED (for testing)."""
        with self._lock:
            self._state = _State.CLOSED
            self._failure_count = 0
            self._success_count = 0


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_BREAKERS: Dict[str, CircuitBreaker] = {}
_REGISTRY_LOCK = threading.Lock()


def get_breaker(backend: str) -> CircuitBreaker:
    with _REGISTRY_LOCK:
        if backend not in _BREAKERS:
            _BREAKERS[backend] = CircuitBreaker(backend=backend)
        return _BREAKERS[backend]


def all_breaker_states() -> Dict[str, str]:
    """Return {backend: state_str} for dashboard / --stats."""
    with _REGISTRY_LOCK:
        return {k: v.state for k, v in _BREAKERS.items()}


# ---------------------------------------------------------------------------
# Brain bus notification (fire-and-forget)
# ---------------------------------------------------------------------------

def _notify_bus(backend: str, event: str, reason: str = "") -> None:
    try:
        import sys
        from pathlib import Path
        _p = Path(__file__).parent.parent / "harmony-engine-protocol"
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
        from brain_bus import BrainBusPublisher  # type: ignore
        pub = BrainBusPublisher(source_repo="zai-wrap")
        pub.publish_learn(
            run_id=f"cb_{backend}_{int(time.time())}",
            source="circuit_breaker",
            category="infra",
            event_type=event.upper(),
            detail=f"backend={backend} reason={reason[:200]}",
            outcome="fail" if "open" in event else "pass",
        )
    except Exception:
        pass  # bus unavailable — never crash the circuit breaker


# ---------------------------------------------------------------------------
# Patch model_dispatch.py at import time
# ---------------------------------------------------------------------------

def _patch_model_dispatch():
    try:
        import model_dispatch as _md  # type: ignore
    except ImportError:
        return

    if getattr(_md, "_CB_PATCHED", False):
        return

    _orig_dispatch = getattr(_md, "dispatch_with_fallback", None)
    if _orig_dispatch is None:
        return

    def _cb_dispatch(model: str, prompt: str, **kwargs):
        # detect backend from model name (mirrors _detect_backend logic)
        backend = getattr(_md, "_detect_backend", lambda m: m.split("-")[0])(model)
        breaker = get_breaker(backend)

        if not breaker.allow():
            # Return a ModelResponse-compatible dict / object
            try:
                from model_dispatch import ModelResponse  # type: ignore
                return ModelResponse(
                    success=False,
                    model=model,
                    backend=backend,
                    content="",
                    error=f"circuit_open:{backend}",
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=0.0,
                )
            except ImportError:
                return {
                    "success": False,
                    "model": model,
                    "backend": backend,
                    "error": f"circuit_open:{backend}",
                }

        try:
            result = _orig_dispatch(model, prompt, **kwargs)
            success = getattr(result, "success", result.get("success", False) if isinstance(result, dict) else False)
            if success:
                breaker.record_success()
            else:
                breaker.record_failure(getattr(result, "error", str(result)))
            return result
        except Exception as exc:
            breaker.record_failure(str(exc))
            raise

    _md.dispatch_with_fallback = _cb_dispatch
    _md._CB_PATCHED = True


_patch_model_dispatch()
