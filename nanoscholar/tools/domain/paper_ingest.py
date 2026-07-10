"""Composite paper ingestion tool: search, download, extract, and save notes."""

from __future__ import annotations

import re
from collections import Counter

from nanoscholar.knowledge.wiki_store import read_note, save_note, search_notes
from nanoscholar.tools.domain.arxiv_search import arxiv_search, download_arxiv_pdf, semantic_scholar_search
from nanoscholar.tools.domain.pdf_tools import pdf_extract_text
from nanoscholar.tools.tool import Tool, register


def _field(block: str, name: str) -> str:
    match = re.search(rf"^\s*{re.escape(name)}:\s*(.+)$", block, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def _first_result_block(text: str) -> str:
    parts = re.split(r"\n\s*\n", text.strip(), maxsplit=1)
    return parts[0] if parts else text.strip()


def _result_blocks(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]


def _title_from_block(block: str, fallback: str) -> str:
    first = block.splitlines()[0].strip() if block.strip() else ""
    first = re.sub(r"^\d+\.\s*", "", first).strip()
    return first or fallback.strip()


def _arxiv_id_from_text(text: str) -> str:
    match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", text)
    return "".join(part for part in match.groups() if part) if match else ""


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[a-z0-9]+", text) if len(t) > 1]


def _title_similarity(query: str, title: str) -> float:
    q = Counter(_tokens(query))
    t = Counter(_tokens(title))
    if not q or not t:
        return 0.0
    common = set(q) & set(t)
    overlap = sum(min(q[token], t[token]) for token in common)
    return overlap / max(1, len(q))


def _best_result_block(search_result: str, query: str) -> tuple[str, float]:
    best_block = ""
    best_score = -1.0
    for block in _result_blocks(search_result):
        title = _title_from_block(block, query)
        score = _title_similarity(query, title)
        if score > best_score:
            best_block = block
            best_score = score
    return best_block or _first_result_block(search_result), max(best_score, 0.0)


def _compact_excerpt(text: str, max_chars: int) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    text = re.sub(r"[ \t]+", " ", text)
    return text[:max_chars].rstrip()


def _existing_paper_note(query: str) -> dict[str, str] | None:
    """Return a cached paper note only when it looks like the same paper."""
    candidates = search_notes(query, top_k=5, snippet_chars=12000)
    query_arxiv = _arxiv_id_from_text(query)
    best: dict[str, str] | None = None
    best_score = 0.0

    for item in candidates:
        title = str(item.get("title", ""))
        tags = [str(tag).lower() for tag in item.get("tags", [])]
        snippet = str(item.get("snippet", ""))
        if "paper" not in tags:
            continue
        if query_arxiv and query_arxiv in snippet:
            return item

        title_score = _title_similarity(query, title.removeprefix("Paper:").strip())
        if title_score > best_score:
            best = item
            best_score = title_score

    if best and best_score >= 0.65:
        return best
    return None


def ingest_paper(
    query: str,
    force_refresh: bool = False,
    max_pdf_chars: int = 0,
) -> str:
    """Search a paper, download/read its PDF when available, and save a note.

    This tool is intentionally composite so paper-reading tasks do not burn one
    agent-loop step per search/download/extract/save operation.
    """
    if not force_refresh:
        top = _existing_paper_note(query)
    else:
        top = None
    if top:
        full_note = read_note(top.get("filename", ""))
        content = full_note or top["snippet"]
        return (
            "[Paper already in knowledge base]\n"
            f"Title: {top['title']}\n"
            f"Tags: {', '.join(top['tags']) if top['tags'] else 'none'}\n"
            "No re-download or re-extraction was performed. Use force_refresh=true to re-ingest.\n"
            f"Note content:\n{content[:12000]}"
        )

    arxiv_result = arxiv_search(query, max_results=3)
    source = "arXiv"
    result_block = ""
    arxiv_id = ""
    search_result = arxiv_result

    if arxiv_result.startswith("[No results") or arxiv_result.startswith("[arXiv API error"):
        search_result = semantic_scholar_search(query, max_results=3)
        source = "Semantic Scholar"

    if search_result.startswith("[") and "error" in search_result.lower():
        return search_result

    result_block, match_score = _best_result_block(search_result, query)
    if match_score < 0.55 and not _arxiv_id_from_text(query):
        semantic_result = semantic_scholar_search(query, max_results=5)
        if not semantic_result.startswith("["):
            semantic_block, semantic_score = _best_result_block(semantic_result, query)
            if semantic_score > match_score:
                search_result = semantic_result
                source = "Semantic Scholar"
                result_block = semantic_block
                match_score = semantic_score

    if match_score < 0.45 and not _arxiv_id_from_text(query):
        return (
            "[Paper not confidently matched]\n"
            f"Query: {query}\n"
            f"Best title: {_title_from_block(result_block, query)}\n"
            f"Match score: {match_score:.2f}\n"
            "I did not save this to the knowledge base because the search result may be a different paper. "
            "Please provide an arXiv ID, DOI, or URL, or retry with force_refresh=true if you still want this result.\n\n"
            f"Search result:\n{search_result[:2000]}"
        )

    title = _title_from_block(result_block, query)
    authors = _field(result_block, "Authors")
    published = _field(result_block, "Published") or _field(result_block, "Year")
    venue = _field(result_block, "Venue")
    abstract = _field(result_block, "Abstract")
    pdf_url = _field(result_block, "PDF")
    url = _field(result_block, "URL")
    arxiv_id = _arxiv_id_from_text(result_block) or _arxiv_id_from_text(pdf_url)

    pdf_path = ""
    extracted = ""
    if arxiv_id:
        download_result = download_arxiv_pdf(arxiv_id)
        path_match = re.search(r" to ([^\s]+\.pdf)", download_result)
        if path_match:
            pdf_path = path_match.group(1)
            extracted = pdf_extract_text(pdf_path, max_chars=max_pdf_chars)
    elif pdf_url and "arxiv.org/pdf" in pdf_url:
        download_result = download_arxiv_pdf(pdf_url)
        path_match = re.search(r" to ([^\s]+\.pdf)", download_result)
        if path_match:
            pdf_path = path_match.group(1)
            extracted = pdf_extract_text(pdf_path, max_chars=max_pdf_chars)

    note_parts = [
        f"Source: {source}",
        f"Query: {query}",
    ]
    if arxiv_id:
        note_parts.append(f"arXiv: {arxiv_id}")
    if authors:
        note_parts.append(f"Authors: {authors}")
    if published:
        note_parts.append(f"Published/Year: {published}")
    if venue:
        note_parts.append(f"Venue: {venue}")
    if pdf_url:
        note_parts.append(f"PDF: {pdf_url}")
    if url:
        note_parts.append(f"URL: {url}")
    if pdf_path:
        note_parts.append(f"Local PDF: {pdf_path}")
    note_parts.append(f"Title Match Score: {match_score:.2f}")
    if abstract:
        note_parts.append("\n## Abstract\n" + abstract)
    if extracted and not extracted.startswith("["):
        section_title = "Extracted Full Text" if max_pdf_chars == 0 else "Extracted Main Text Excerpt"
        note_parts.append(f"\n## {section_title}\n" + _compact_excerpt(extracted, max_pdf_chars or len(extracted)))
    else:
        note_parts.append("\n## Search Result\n" + search_result)

    content = "\n".join(note_parts).strip()
    note_id = save_note(
        title=f"Paper: {title}",
        content=content,
        tags=["paper", "research", source.lower().replace(" ", "-")],
    )

    return (
        "[Paper ingested]\n"
        f"Note ID: {note_id}\n"
        f"Title: {title}\n"
        f"Source: {source}\n"
        f"arXiv: {arxiv_id or 'N/A'}\n"
        f"Local PDF: {pdf_path or 'N/A'}\n\n"
        "Saved a structured note in knowledge_base/notes. Key content:\n"
        f"{content[:6000]}"
    )


ingest_paper_tool = Tool(
    name="ingest_paper",
    description=(
        "Composite paper workflow: search arXiv/Semantic Scholar, download arXiv PDF if available, "
        "extract main text, and save a structured Markdown note into the local knowledge base. "
        "Use this first for paper questions. If a matching paper note already exists, this returns it "
        "without re-downloading or re-extracting. Do not answer from old memory when this tool cannot "
        "confidently identify the requested paper; ask for an arXiv ID, DOI, or URL instead."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Paper title, arXiv id, URL, or keywords"},
            "force_refresh": {
                "type": "boolean",
                "description": "If false, return existing knowledge-base note when found",
                "default": False,
            },
            "max_pdf_chars": {
                "type": "integer",
                "description": "Maximum PDF text characters to store in the note. 0 means full extracted text.",
                "default": 0,
            },
        },
        "required": ["query"],
    },
    handler=ingest_paper,
    category="network",
    approval_required=False,
)
register(ingest_paper_tool)

