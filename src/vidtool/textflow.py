"""Turn sentence-level ASR segments into readable paragraphs.

Readability unit for humans AND agents is the topic block, not the single
short sentence. Rules (conservative, purely local):

- a short fragment (<min_merge chars, no strong punctuation ending) is
  folded into the previous sentence instead of starting a new one
- a new paragraph starts on a long pause (>max_gap) between sentences,
  when the current paragraph is long enough (>min_window), or when it
  has exceeded max_window seconds
- sentences join without spaces at CJK boundaries, with a space at
  latin/digit boundaries
"""

from __future__ import annotations

import re

_STRONG_END = "。！？；!?…"
_CJK = r"\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af"


def join_sentences(parts: list[str]) -> str:
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not out:
            out = p
        elif re.search(r"[A-Za-z0-9]$", out) and re.match(r"^[A-Za-z0-9]", p):
            out += " " + p
        else:
            out += p
    return out


def to_paragraphs(segments: list[dict], *, max_window: float = 55.0,
                  min_window: float = 20.0, max_gap: float = 1.8,
                  min_merge: int = 12) -> list[dict]:
    paras: list[dict] = []
    cur: dict | None = None   # {start, end, parts: []}

    def close():
        nonlocal cur
        if cur and cur["parts"]:
            paras.append({
                "start": round(cur["start"], 2),
                "end": round(cur["end"], 2),
                "text": join_sentences(cur["parts"]),
            })
        cur = None

    for s in segments:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        start, end = float(s.get("start", 0)), float(s.get("end", 0))
        if cur is None:
            cur = {"start": start, "end": end, "parts": [text]}
            continue
        gap = start - cur["end"]
        dur = cur["end"] - cur["start"]
        # fold short fragments into the current sentence flow
        if len(text) < min_merge and text[-1:] not in _STRONG_END:
            cur["parts"].append(text)
            cur["end"] = end
            continue
        if gap > max_gap or dur >= max_window or (
                dur >= min_window and text[-1:] in _STRONG_END
                and cur["parts"][-1][-1:] in _STRONG_END):
            close()
            cur = {"start": start, "end": end, "parts": [text]}
            continue
        cur["parts"].append(text)
        cur["end"] = end
    close()
    return paras


def fmt_stamp(sec: float) -> str:
    sec = max(int(sec), 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def render_paragraphs(paras: list[dict], *, stamp_len: int = 7) -> str:
    """`[3:24] text` per paragraph, blank line between — easy to scan."""
    lines = []
    for p in paras:
        stamp = fmt_stamp(p["start"]).rjust(stamp_len)
        lines.append(f"[{stamp}] {p['text']}")
    return "\n\n".join(lines) + "\n"
