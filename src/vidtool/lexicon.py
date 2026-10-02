"""Term normalization for ASR output.

SenseVoice emits english proper nouns as subword fragments with spurious
spaces ("code ex", "cha t g P T", "to ken"). We cannot fix the recognizer,
but squashing a latin run (drop spaces/hyphens/dots, lowercase) and looking
it up in a glossary recovers them deterministically.

Built-in table covers common AI/dev terms; callers can inject their own
via --glossary (they usually know the video's domain).
"""

from __future__ import annotations

import re

# squash-key -> canonical form
DEFAULT_GLOSSARY: dict[str, str] = {
    # products / brands
    "chatgpt": "ChatGPT", "chtgpt": "ChatGPT", "chatgbt": "ChatGPT",
    "chatgp": "ChatGPT", "chatgpt2": "ChatGPT",
    "gpt": "GPT", "gbt": "GPT", "gpts": "GPTs", "gpt5": "GPT-5",
    "gpt6": "GPT-6", "gbt6": "GPT-6",
    "codex": "Codex", "codedex": "Codex", "codeex": "Codex",
    "openai": "OpenAI", "anthropic": "Anthropic",
    "claude": "Claude", "gemini": "Gemini", "deepseek": "DeepSeek",
    "deepsick": "DeepSeek", "llama": "Llama", "luna": "Luna",
    "github": "GitHub", "gitlab": "GitLab", "git": "Git", "gitee": "Gitee",
    "cloudflare": "Cloudflare", "vercel": "Vercel", "netlify": "Netlify",
    "cursor": "Cursor", "windsurf": "Windsurf", "vscode": "VS Code",
    "copilot": "Copilot", "whisper": "Whisper", "sensevoice": "SenseVoice",
    "manus": "Manus", "dify": "Dify", "coze": "Coze", "n8n": "n8n",
    "midjourney": "Midjourney", "comfyui": "ComfyUI", "stable diffusion": "Stable Diffusion",
    # acronyms
    "api": "API", "mcp": "MCP", "sdk": "SDK", "cli": "CLI", "gui": "GUI",
    "llm": "LLM", "rag": "RAG", "agent": "agent", "token": "token",
    "prompt": "prompt", "skill": "skill", "plugin": "plugin", "hook": "hook",
    "html": "HTML", "css": "CSS", "json": "JSON", "yaml": "YAML",
    "http": "HTTP", "https": "HTTPS", "url": "URL", "uri": "URI",
    "tcp": "TCP", "dns": "DNS", "cdn": "CDN", "ssh": "SSH", "vps": "VPS",
    "sql": "SQL", "orm": "ORM", "crdt": "CRDT", "simd": "SIMD",
    # douyin/bilibili context
    "bilibili": "bilibili", "douyin": "douyin", "tiktok": "TikTok",
    "ppt": "PPT", "pdf": "PDF", "excel": "Excel", "word": "Word",
    "wifi": "Wi-Fi", "ai": "AI", "agi": "AGI",
    "tensorflow": "TensorFlow", "pytorch": "PyTorch", "onnx": "ONNX",
    "numpy": "NumPy", "uv": "uv", "pip": "pip", "npm": "npm", "npx": "npx",
    "nodejs": "Node.js", "node": "Node",
}

# a latin run possibly split by single spaces/hyphens/dots into fragments
_RUN_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9]*(?:[ \-\.][A-Za-z][A-Za-z0-9]*)+"   # multi-fragment
    r"|[A-Za-z][A-Za-z0-9]*"                                    # single word
)


def normalize_text(text: str, extra: dict[str, str] | None = None) -> str:
    """Replace latin runs whose squashed form is a known term."""
    table = dict(DEFAULT_GLOSSARY)
    if extra:
        table.update({k.lower(): v for k, v in extra.items()})

    def sub(m: re.Match) -> str:
        run = m.group(0)
        squash = re.sub(r"[ \-\.]", "", run).lower()
        hit = table.get(squash)
        if hit:
            return hit
        # user glossary entries may be multi-word keys ("to ken" -> "token")
        if extra:
            hit = extra.get(run.lower())
            if hit:
                return hit
        return run

    return _RUN_RE.sub(sub, text)


def normalize_segments(segments: list[dict],
                       extra: dict[str, str] | None = None) -> list[dict]:
    for s in segments:
        s["text"] = normalize_text(s["text"], extra)
    return segments


def parse_glossary_arg(arg: str | None) -> dict[str, str] | None:
    """Accept 'a=b;c=d' inline strings or a JSON {"a": "b"} file path."""
    if not arg:
        return None
    import json
    from pathlib import Path
    p = Path(arg)
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except Exception:
            pass
    out: dict[str, str] = {}
    for part in re.split(r"[;\n]", arg):
        if "=" in part:
            k, v = part.split("=", 1)
            k, v = k.strip(), v.strip()
            if k and v:
                out[k] = v
    return out or None


def glossary_hash(extra: dict[str, str] | None) -> str:
    """Stable short hash so transcript cache keys can include the glossary."""
    if not extra:
        return ""
    import hashlib
    import json as _json
    payload = _json.dumps(sorted(extra.items()), ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]
