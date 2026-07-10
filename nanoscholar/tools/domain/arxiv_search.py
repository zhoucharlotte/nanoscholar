"""arXiv paper search with SQLite cache."""

import re
import json
import sqlite3
import time
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from nanoscholar.tools.tool import Tool, register

_ARXIV_CACHE_DB = Path("arxiv_cache.db")

NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def _init_cache():
    with sqlite3.connect(_ARXIV_CACHE_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS arxiv_cache (
                query_hash TEXT PRIMARY KEY,
                results TEXT,
                cached_at REAL
            )
        """)


def _query_hash(query: str, max_results: int) -> str:
    import hashlib
    return hashlib.md5(f"{query}_{max_results}".encode()).hexdigest()


def _cached(query: str, max_results: int) -> str | None:
    _init_cache()
    h = _query_hash(query, max_results)
    with sqlite3.connect(_ARXIV_CACHE_DB) as conn:
        cur = conn.execute("SELECT results, cached_at FROM arxiv_cache WHERE query_hash=?", (h,))
        row = cur.fetchone()
        if row:
            return row[0]
    return None


def _set_cache(query: str, max_results: int, results: str):
    _init_cache()
    h = _query_hash(query, max_results)
    with sqlite3.connect(_ARXIV_CACHE_DB) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO arxiv_cache (query_hash, results, cached_at) VALUES (?, ?, ?)",
            (h, results, time.time()),
        )


def arxiv_search(query: str, max_results: int = 5) -> str:
    """Search arXiv papers by query string."""
    # Check cache
    cached = _cached(query, max_results)
    if cached and cached != "[No results found]":
        return cached

    # Fetch from arXiv API
    id_match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", query)
    if id_match:
        arxiv_id = "".join(part for part in id_match.groups() if part)
        url = f"http://export.arxiv.org/api/query?id_list={urllib.parse.quote(arxiv_id)}"
    else:
        normalized = " ".join(re.sub(r"[^\w\s.-]", " ", query).split())
        url = f"http://export.arxiv.org/api/query?search_query=all:{urllib.parse.quote(normalized)}&start=0&max_results={max_results}"
    req = urllib.request.Request(url, headers={"User-Agent": "Nanoscholar/0.2"})
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl._create_unverified_context()) as resp:
            xml_data = resp.read().decode("utf-8")
    except Exception as e:
        return f"[arXiv API error: {e}]"

    # Parse XML
    root = ET.fromstring(xml_data)
    entries = root.findall("atom:entry", NS)

    if not entries:
        result = "[No results found]"
        _set_cache(query, max_results, result)
        return result

    lines = []
    for i, entry in enumerate(entries, 1):
        title = (entry.find("atom:title", NS) or ET.Element("t")).text or ""
        title = " ".join(title.split())
        summary = (entry.find("atom:summary", NS) or ET.Element("s")).text or ""
        summary = " ".join(summary.split())[:300]
        # PDF link
        pdf_link = ""
        for link in entry.findall("atom:link", NS):
            if link.get("title") == "pdf":
                pdf_link = link.get("href", "")
                break
        authors = []
        for author in entry.findall("atom:author", NS):
            name = author.find("atom:name", NS)
            if name is not None and name.text:
                authors.append(name.text)
        author_str = ", ".join(authors[:3])
        if len(authors) > 3:
            author_str += " et al."
        published = (entry.find("atom:published", NS) or ET.Element("p")).text or ""
        published = published[:10] if published else ""

        lines.append(f"{i}. {title}")
        lines.append(f"   Authors: {author_str}")
        lines.append(f"   Published: {published}")
        lines.append(f"   PDF: {pdf_link}")
        lines.append(f"   Abstract: {summary}...")
        lines.append("")

    result = "\n".join(lines).strip()
    _set_cache(query, max_results, result)
    return result


def semantic_scholar_search(query: str, max_results: int = 5) -> str:
    """Search Semantic Scholar for papers not found by arXiv."""
    max_results = max(1, min(int(max_results or 5), 10))
    params = urllib.parse.urlencode(
        {
            "query": query,
            "limit": max_results,
            "fields": "title,authors,year,venue,abstract,url,openAccessPdf,externalIds",
        }
    )
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "Nanoscholar/0.2"})

    try:
        with urllib.request.urlopen(req, timeout=20, context=ssl._create_unverified_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return f"[Semantic Scholar API error: {e}]"

    papers = payload.get("data") or []
    if not papers:
        return "[No Semantic Scholar results found]"

    lines = []
    for i, paper in enumerate(papers, 1):
        authors = ", ".join(a.get("name", "") for a in (paper.get("authors") or [])[:3] if a.get("name"))
        if len(paper.get("authors") or []) > 3:
            authors += " et al."
        external_ids = paper.get("externalIds") or {}
        arxiv_id = external_ids.get("ArXiv", "")
        pdf_url = ((paper.get("openAccessPdf") or {}).get("url")) or ""
        abstract = " ".join((paper.get("abstract") or "").split())[:600]

        lines.append(f"{i}. {paper.get('title') or '[Untitled]'}")
        lines.append(f"   Authors: {authors or 'N/A'}")
        lines.append(f"   Year: {paper.get('year') or 'N/A'}")
        lines.append(f"   Venue: {paper.get('venue') or 'N/A'}")
        if arxiv_id:
            lines.append(f"   arXiv: {arxiv_id}")
            lines.append(f"   PDF: https://arxiv.org/pdf/{arxiv_id}")
        elif pdf_url:
            lines.append(f"   PDF: {pdf_url}")
        lines.append(f"   URL: {paper.get('url') or 'N/A'}")
        if abstract:
            lines.append(f"   Abstract: {abstract}...")
        lines.append("")

    return "\n".join(lines).strip()


def _extract_arxiv_id(value: str) -> str:
    match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", value)
    if not match:
        raise ValueError("No arXiv id found. Pass an id like 2507.05056v2 or an arXiv PDF URL.")
    return "".join(part for part in match.groups() if part)


def download_arxiv_pdf(identifier: str, output_dir: str = "papers") -> str:
    """Download an arXiv PDF to a local path for pdf_extract_text."""
    try:
        arxiv_id = _extract_arxiv_id(identifier)
    except ValueError as e:
        return f"[arXiv PDF download error: {e}]"

    target_dir = Path(output_dir)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return f"[arXiv PDF download error: cannot create output directory: {e}]"

    target = target_dir / f"arxiv_{arxiv_id}.pdf"
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Nanoscholar/0.2"})

    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl._create_unverified_context()) as resp:
            content_type = resp.headers.get_content_type()
            data = resp.read()
    except Exception as e:
        return f"[arXiv PDF download error: {e}]"

    if content_type != "application/pdf" and not data.startswith(b"%PDF"):
        return f"[arXiv PDF download error: arXiv did not return a PDF, content-type={content_type}]"

    try:
        target.write_bytes(data)
    except Exception as e:
        return f"[arXiv PDF download error: cannot write PDF: {e}]"

    pdf_path = target.as_posix()
    return (
        f"Downloaded arXiv PDF {arxiv_id} to {pdf_path} ({len(data)} bytes). "
        f"Next call pdf_extract_text with pdf_path='{pdf_path}'."
    )


arxiv_tool = Tool(
    name="arxiv_search",
    description="Search arXiv papers by keyword or arXiv id. Returns titles, authors, abstracts, and PDF links. Results are cached locally.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query (e.g. 'transformer attention')"},
            "max_results": {"type": "integer", "description": "Maximum number of results (default 5)", "default": 5},
        },
        "required": ["query"],
    },
    handler=arxiv_search,
    category="network",
    approval_required=False,
)
register(arxiv_tool)


semantic_scholar_tool = Tool(
    name="semantic_scholar_search",
    description=(
        "Search Semantic Scholar for academic papers by title or keywords. "
        "Use this when arxiv_search returns no results or the paper may not be on arXiv. "
        "Returns title, authors, venue, year, abstract, URL, and open-access PDF/arXiv id when available."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Paper title or search keywords"},
            "max_results": {"type": "integer", "description": "Maximum number of results, up to 10", "default": 5},
        },
        "required": ["query"],
    },
    handler=semantic_scholar_search,
    category="network",
    approval_required=False,
)
register(semantic_scholar_tool)


download_arxiv_pdf_tool = Tool(
    name="download_arxiv_pdf",
    description=(
        "Safely download an arXiv PDF by arXiv id or arXiv URL into a local papers/ directory. "
        "Use this before pdf_extract_text when a paper PDF must be read. Do not use execute_command for arXiv PDF downloads."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "identifier": {
                "type": "string",
                "description": "arXiv id or URL, e.g. 2507.05056v2 or https://arxiv.org/pdf/2507.05056v2",
            },
            "output_dir": {
                "type": "string",
                "description": "Local directory to save into, default papers",
                "default": "papers",
            },
        },
        "required": ["identifier"],
    },
    handler=download_arxiv_pdf,
    category="network",
    approval_required=False,
)
register(download_arxiv_pdf_tool)

