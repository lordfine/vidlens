"""agentio — the agent contract for vidlens.

Every command prints a single JSON object to stdout on success.
Every failure prints a JSON error object to *stderr* with a `hint`
telling the calling agent what to do next, and exits with a stable code:

  0  success
  1  bad input / content problem (dead link, no subtitles, unsupported page)
  2  login required (agent should ask the user for --cookie)
  3  network / anti-bot failure (retry later or with --cookie)
  4  missing local dependency (ffmpeg, ASR model — run `vidlens doctor`)
"""

from __future__ import annotations

import json
import sys

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_AUTH = 2
EXIT_BLOCKED = 3
EXIT_DEPS = 4


class vidlensError(Exception):
    """Base error carrying an agent-facing code + hint."""

    errcode = "error"
    exit_code = EXIT_ERROR

    def __init__(self, message: str, *, hint: str | None = None,
                 errcode: str | None = None, exit_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        if errcode is not None:
            self.errcode = errcode
        if exit_code is not None:
            self.exit_code = exit_code


class AuthNeededError(vidlensError):
    errcode = "auth_needed"
    exit_code = EXIT_AUTH


class BlockedError(vidlensError):
    errcode = "blocked"
    exit_code = EXIT_BLOCKED


class DependencyError(vidlensError):
    errcode = "dependency_missing"
    exit_code = EXIT_DEPS


class NotSupportedError(vidlensError):
    errcode = "not_supported"
    exit_code = EXIT_ERROR


def _dumps(payload: dict, pretty: bool) -> str:
    return json.dumps(payload, ensure_ascii=False,
                      indent=2 if pretty else None, default=str)


def emit(payload: dict, *, pretty: bool = False) -> None:
    """Print a success JSON object to stdout (exit stays 0)."""
    payload.setdefault("ok", True)
    sys.stdout.write(_dumps(payload, pretty) + "\n")
    sys.stdout.flush()


def emit_error(err: vidlensError, *, pretty: bool = False) -> int:
    """Print a structured error to stderr; returns the exit code."""
    obj = {
        "ok": False,
        "error": {
            "code": err.errcode,
            "message": err.message,
            "hint": err.hint,
        },
    }
    sys.stderr.write(_dumps(obj, pretty) + "\n")
    sys.stderr.flush()
    return err.exit_code
