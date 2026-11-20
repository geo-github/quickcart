"""Project settings, read from environment variables.

The git-ignored `.env` file in the project root is loaded automatically when python-dotenv
is installed. Other modules read these values as `settings.NAME` at call time, so tests can
change them with `monkeypatch.setattr(settings, "NAME", value)`.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:  # python-dotenv is optional: plain environment variables work too
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def _str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _path(name: str, default: str) -> Path:
    p = Path(_str(name, default))
    return p if p.is_absolute() else ROOT / p


# --- LLM platform (confidential values live only in .env) ---------------------------------
LLM_BASE_URL = _str("LLM_BASE_URL")          # ends in /v1
LLM_API_KEY = _str("LLM_API_KEY")            # sent as the x-bf-vk header
LLM_MAIN = _str("LLM_MAIN", "vllm/mistralai/Mistral-7B-Instruct-v0.3")
LLM_LIGHT = _str("LLM_LIGHT", "ollama/gemma2:2b")
EMBED_MODEL = _str("EMBED_MODEL", "ollama/nomic-embed-text")

LLM_MODE = _str("LLM_MODE", "live")          # live | record | replay | cache
TOOL_MODE = _str("TOOL_MODE", "native")      # native | prompted
JSON_MODE = _str("JSON_MODE", "schema")      # schema | prompted
LLM_AUTO_FALLBACK = _bool("LLM_AUTO_FALLBACK", True)
LLM_TIMEOUT_S = _int("LLM_TIMEOUT_S", 60)
LLM_MAX_RETRIES = _int("LLM_MAX_RETRIES", 3)
LLM_CACHE_DIR = _path("LLM_CACHE_DIR", "var/llm_cache")

# --- Storage ------------------------------------------------------------------------------
DB_PATH = _path("DB_PATH", "var/app.db")
CHROMA_PATH = _path("CHROMA_PATH", "var/chroma")

# --- Agent limits (W2) and memory ---------------------------------------------------------
MAX_TURNS = _int("MAX_TURNS", 8)
MAX_STEPS = _int("MAX_STEPS", 12)
SESSION_TOKEN_BUDGET = _int("SESSION_TOKEN_BUDGET", 60000)
HISTORY_TOKEN_BUDGET = _int("HISTORY_TOKEN_BUDGET", 3000)

# --- Feature switches ---------------------------------------------------------------------
ENABLE_ORCHESTRATOR = _bool("ENABLE_ORCHESTRATOR", True)
GUARDS_ENABLED = _bool("GUARDS_ENABLED", True)
TOOL_TRANSPORT = _str("TOOL_TRANSPORT", "inprocess")   # inprocess | mcp
