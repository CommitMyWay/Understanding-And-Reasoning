"""
context_manager.py
------------------
Session context store for the VoC Task Understanding skill.

Fix #8: tracks clarification_attempts per field; caps at MAX_RETRIES_PER_FIELD.
Fix #9: file-based persistence via JSON temp file so CLI shell-out calls
        share state across process boundaries.

Usage (CLI):
    python tools/context_manager.py init --session my-session-id
    python tools/context_manager.py save --session my-session-id --context '{...}'
    python tools/context_manager.py get --session my-session-id
    python tools/context_manager.py append_turn --session my-session-id --role user --message "..."
    python tools/context_manager.py strip_pii --session my-session-id
    python tools/context_manager.py get_intent_json --session my-session-id
    python tools/context_manager.py reset --session my-session-id
"""

import argparse
import json
import os
import re
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MAX_RETRIES_PER_FIELD = 2  # Fix #8: cap clarification attempts per required field

# ---------------------------------------------------------------------------
# File-based persistence (Fix #9)
# ---------------------------------------------------------------------------

def _session_file(session_id: str) -> str:
    """Return path to the JSON file backing this session."""
    tmp = tempfile.gettempdir()
    return os.path.join(tmp, f"voc_ctx_{session_id}.json")


def _load_from_disk(session_id: str) -> dict | None:
    path = _session_file(session_id)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _save_to_disk(session: dict):
    path = _session_file(session["session_id"])
    with open(path, "w") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)

# ---------------------------------------------------------------------------
# In-memory cache (avoids disk reads on every call in same process)
# ---------------------------------------------------------------------------

_SESSIONS: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# PII patterns
# ---------------------------------------------------------------------------

_PII_PATTERNS = [
    r"\b[\w.+-]+@[\w-]+\.\w{2,}\b",   # email
    r"\b(?:\+84|0)\d{9,10}\b",         # VN phone
    r"\b\d{9,12}\b",                   # numeric ID
]


def _strip_pii_str(text: str) -> str:
    for p in _PII_PATTERNS:
        text = re.sub(p, "[REDACTED]", text, flags=re.IGNORECASE)
    return text


def _strip_pii_recursive(obj):
    if isinstance(obj, str):
        return _strip_pii_str(obj)
    if isinstance(obj, dict):
        return {k: _strip_pii_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_pii_recursive(i) for i in obj]
    return obj

# ---------------------------------------------------------------------------
# Intent skeleton
# ---------------------------------------------------------------------------

ALL_DATA_SOURCES = ["App Store", "CH Play", "Youtube", "Voz", "Tinhte", "Reddit"]


def _empty_intent() -> dict:
    return {
        "subject": None,
        "market": None,
        "goal": None,
        "focus": None,
        "data_source": list(ALL_DATA_SOURCES),  # default = all 6 sources
        "filters": {
            "time_range": "last_90_days",
            "platform": "all",
            "sentiment": "all",
            "keywords": [],
        },
        "clarifications_done": [],
        "plan_steps": [],
    }


def _empty_session(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "intent": _empty_intent(),
        "history": [],
        "state": "collecting",
        # Fix #8: track attempts per field
        "clarification_attempts": {
            "subject": 0,
            "market": 0,
            "goal": 0,
            "focus": 0,
        },
    }

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_session(session_id: str) -> dict:
    session = _empty_session(session_id)
    _SESSIONS[session_id] = session
    _save_to_disk(session)
    return deepcopy(session)


def get_session(session_id: str) -> dict:
    """Return the current session from memory or disk, creating if absent."""
    if session_id in _SESSIONS:
        return deepcopy(_SESSIONS[session_id])
    # Fix #9: try loading from disk (cross-process persistence)
    on_disk = _load_from_disk(session_id)
    if on_disk:
        _SESSIONS[session_id] = on_disk
        return deepcopy(on_disk)
    return init_session(session_id)


def save_context(session_id: str, intent_update: dict) -> dict:
    """Merge intent_update into the session's intent. Internal meta-fields stripped."""
    session = get_session(session_id)
    internal_keys = {"missing_required", "mode"}

    for key, value in intent_update.items():
        if key in internal_keys:
            continue
        if key in session["intent"]:
            session["intent"][key] = value

    if intent_update.get("mode") == "planning":
        session["state"] = "planning"
    elif intent_update.get("mode") == "deep_dive":
        session["state"] = "deep_dive"

    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _SESSIONS[session_id] = session
    _save_to_disk(session)
    return deepcopy(session)


def append_turn(session_id: str, role: str, message: str) -> dict:
    if role not in ("user", "agent"):
        raise ValueError(f"Invalid role: {role}. Must be 'user' or 'agent'.")
    session = get_session(session_id)
    session["history"].append({
        "role": role,
        "message": _strip_pii_str(message),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _SESSIONS[session_id] = session
    _save_to_disk(session)
    return deepcopy(session)


def increment_clarification_attempt(session_id: str, field: str) -> dict:
    """
    Fix #8: increment attempt counter for a field.
    Returns the updated session including whether max retries is reached.
    """
    session = get_session(session_id)
    attempts = session.get("clarification_attempts", {})
    attempts[field] = attempts.get(field, 0) + 1
    session["clarification_attempts"] = attempts
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _SESSIONS[session_id] = session
    _save_to_disk(session)
    result = deepcopy(session)
    result["max_retries_reached"] = attempts[field] >= MAX_RETRIES_PER_FIELD
    result["attempts_for_field"] = attempts[field]
    return result


def get_clarification_attempts(session_id: str, field: str) -> int:
    """Return how many times this field has been clarified."""
    session = get_session(session_id)
    return session.get("clarification_attempts", {}).get(field, 0)


def mark_confirmed(session_id: str) -> dict:
    session = get_session(session_id)
    session["state"] = "confirmed"
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _SESSIONS[session_id] = session
    _save_to_disk(session)
    return deepcopy(session)


def strip_pii(session_id: str) -> dict:
    session = get_session(session_id)
    session["intent"] = _strip_pii_recursive(session["intent"])
    session["history"] = _strip_pii_recursive(session["history"])
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    _SESSIONS[session_id] = session
    _save_to_disk(session)
    return deepcopy(session)


def get_intent_json(session_id: str) -> dict:
    """Clean intent object safe to pass downstream. Strips PII first."""
    strip_pii(session_id)
    session = _SESSIONS[session_id]
    return deepcopy(session["intent"])


def reset_session(session_id: str) -> dict:
    """Wipe in-memory and on-disk state for the session."""
    path = _session_file(session_id)
    if os.path.exists(path):
        os.remove(path)
    if session_id in _SESSIONS:
        del _SESSIONS[session_id]
    return init_session(session_id)

# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="VoC session context manager.")
    parser.add_argument(
        "command",
        choices=[
            "init", "get", "save", "append_turn",
            "strip_pii", "get_intent_json", "reset",
            "increment_attempt", "get_attempts",
        ],
    )
    parser.add_argument("--session", required=True)
    parser.add_argument("--context", default=None)
    parser.add_argument("--role", default=None)
    parser.add_argument("--message", default=None)
    parser.add_argument("--field", default=None)
    args = parser.parse_args()

    try:
        if args.command == "init":
            result = init_session(args.session)
        elif args.command == "get":
            result = get_session(args.session)
        elif args.command == "save":
            if not args.context:
                print(json.dumps({"error": "--context required"}), file=sys.stderr)
                sys.exit(1)
            result = save_context(args.session, json.loads(args.context))
        elif args.command == "append_turn":
            if not args.role or not args.message:
                print(json.dumps({"error": "--role and --message required"}), file=sys.stderr)
                sys.exit(1)
            result = append_turn(args.session, args.role, args.message)
        elif args.command == "strip_pii":
            result = strip_pii(args.session)
        elif args.command == "get_intent_json":
            result = get_intent_json(args.session)
        elif args.command == "reset":
            result = reset_session(args.session)
        elif args.command == "increment_attempt":
            if not args.field:
                print(json.dumps({"error": "--field required"}), file=sys.stderr)
                sys.exit(1)
            result = increment_clarification_attempt(args.session, args.field)
        elif args.command == "get_attempts":
            if not args.field:
                print(json.dumps({"error": "--field required"}), file=sys.stderr)
                sys.exit(1)
            result = {"field": args.field, "attempts": get_clarification_attempts(args.session, args.field)}
        else:
            print(json.dumps({"error": f"Unknown command: {args.command}"}), file=sys.stderr)
            sys.exit(1)

        print(json.dumps(result, ensure_ascii=False, indent=2))

    except (json.JSONDecodeError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
