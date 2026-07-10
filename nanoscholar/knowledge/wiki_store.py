"""Knowledge base: save/search Markdown notes with BM25."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

_NOTES_DIR = Path("knowledge_base") / "notes"
_INDEX_FILE = Path("knowledge_base") / "index.json"


# ── Tokenizer ────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Simple tokenizer: English words + Chinese character bigrams."""
    text = text.lower()
    tokens: list[str] = []
    for word in re.findall(r"[a-z0-9]+", text):
        if len(word) > 1:
            tokens.append(word)
    chars = re.findall('[\u4e00-\u9fff]', text)
    for i in range(len(chars) - 1):
        tokens.append(chars[i] + chars[i + 1])
    if len(chars) <= 4:
        tokens.extend(chars)
    return tokens


# ── Index persistence ───────────────────────────────────────

def _load_index() -> dict:
    if _INDEX_FILE.exists():
        with open(_INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"notes": []}


def _save_index(index: dict):
    _INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


# ── Public API ─────────────────────────────────────────────

def save_note(title: str, content: str, tags: list[str] | None = None) -> str:
    """Save a note as a Markdown file and append to the index."""
    _NOTES_DIR.mkdir(parents=True, exist_ok=True)
    tags = tags or []
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", title)[:50]
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{safe_name}.md"
    filepath = _NOTES_DIR / filename

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        if tags:
            f.write(f"Tags: {', '.join(tags)}\n\n")
        f.write(content)

    idx = _load_index()
    entry = {
        "id": f"note_{len(idx['notes']) + 1}",
        "title": title,
        "tags": tags,
        "filename": filename,
        "created": datetime.now().isoformat(),
    }
    idx["notes"].append(entry)
    _save_index(idx)
    return entry["id"]


def read_note(filename: str) -> str:
    """Read one note by indexed filename."""
    safe = Path(filename).name
    fp = _NOTES_DIR / safe
    if not fp.exists():
        return ""
    return fp.read_text(encoding="utf-8")


def list_notes(only_papers: bool = False, limit: int = 100) -> list[dict[str, Any]]:
    """List indexed notes, optionally filtering to paper notes only."""
    idx = _load_index()
    notes = idx.get("notes", [])
    results: list[dict[str, Any]] = []

    for entry in reversed(notes):
        tags = entry.get("tags") or []
        title = entry.get("title") or ""
        if only_papers and "paper" not in tags and not str(title).startswith("Paper: "):
            continue
        results.append(
            {
                "id": entry.get("id", ""),
                "title": title,
                "tags": tags,
                "filename": entry.get("filename", ""),
                "created": entry.get("created", ""),
            }
        )
        if len(results) >= max(1, int(limit or 100)):
            break

    return results


def search_notes(query: str, top_k: int = 5, snippet_chars: int = 4000) -> list[dict[str, Any]]:
    """Search notes by BM25. Returns list of {title, tags, snippet, score}."""
    from rank_bm25 import BM25Okapi

    idx = _load_index()
    if not idx["notes"]:
        return []

    corpus: list[str] = []
    valid: list[dict] = []
    for entry in idx["notes"]:
        fp = _NOTES_DIR / entry["filename"]
        if not fp.exists():
            continue
        try:
            text = fp.read_text(encoding="utf-8")
            corpus.append(f"{entry['title']} {' '.join(entry['tags'])} {text}")
            valid.append(entry)
        except Exception:
            continue

    if not corpus:
        return []

    tok_corpus = [_tokenize(d) for d in corpus]
    bm25 = BM25Okapi(tok_corpus)
    tok_query = _tokenize(query)
    scores = bm25.get_scores(tok_query)

    scored = [(scores[i], valid[i]) for i in range(len(valid))]
    scored.sort(key=lambda x: x[0], reverse=True)
    scored = [s for s in scored if s[0] > 0][:top_k]

    if not scored:
        # Fallback: substring match
        results = []
        ql = query.lower()
        for entry in valid:
            fp = _NOTES_DIR / entry["filename"]
            text = fp.read_text(encoding="utf-8")
            if ql in text.lower() or ql in entry["title"].lower():
                results.append({
                    "score": 0.5, "title": entry["title"],
                    "tags": entry["tags"], "filename": entry["filename"], "snippet": text[:snippet_chars],
                })
        return results[:top_k]

    results = []
    for score, entry in scored:
        fp = _NOTES_DIR / entry["filename"]
        text = fp.read_text(encoding="utf-8")
        results.append({
            "score": round(float(score), 3),
            "title": entry["title"],
            "tags": entry["tags"],
            "filename": entry["filename"],
            "snippet": text[:snippet_chars],
        })
    return results
