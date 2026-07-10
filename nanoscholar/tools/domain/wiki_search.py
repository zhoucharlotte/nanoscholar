"""MCP tool: search knowledge base."""

from nanoscholar.tools.tool import Tool, register
from nanoscholar.knowledge.wiki_store import list_notes, search_notes

def wiki_search(query: str, top_k: int = 5, max_chars: int = 6000) -> str:
    results = search_notes(query, top_k, snippet_chars=max_chars)
    if not results:
        return "[No matching notes found]"
    # Format results: clear sections with key info highlighted
    sections = []
    for r in results:
        snippet = r['snippet'][:max_chars].strip()
        # Try to extract a focused answer snippet around the query
        # by finding lines containing query terms
        lines_raw = snippet.split("\n")
        key_lines = [l for l in lines_raw if any(w.lower() in l.lower() for w in query.split()[:3])]
        highlighted = " | ".join(k.strip() for k in key_lines[:5]) if key_lines else snippet[:200]
        sections.append(
            f"[{r['title']}]\n"
            f"Tags: {', '.join(r['tags']) if r['tags'] else 'none'}\n"
            f"KEY INFO: {highlighted}\n"
            f"FULL:\n{snippet}"
        )
    return ("\n\n---\n\n".join(sections)).strip() or  "[No results]"


def list_my_notes(only_papers: bool = False, limit: int = 100) -> str:
    results = list_notes(only_papers=only_papers, limit=limit)
    if not results:
        scope = "papers" if only_papers else "notes"
        return f"[No {scope} found in knowledge base]"

    header = "[Knowledge base papers]" if only_papers else "[Knowledge base notes]"
    lines = [header, f"Count: {len(results)}", ""]
    for idx, item in enumerate(results, 1):
        tags = ", ".join(item["tags"]) if item["tags"] else "none"
        lines.append(f"{idx}. {item['title']}")
        lines.append(f"   ID: {item['id']}")
        lines.append(f"   Tags: {tags}")
        lines.append(f"   File: {item['filename']}")
        lines.append(f"   Created: {item['created'] or 'N/A'}")
        lines.append("")
    return "\n".join(lines).strip()

wiki_search_tool = Tool(
    name="search_my_notes",
    description=(
        "Search the local knowledge base. Treat results as cached notes, not fresh evidence. "
        "For paper-reading requests, prefer ingest_paper first; use search_my_notes for follow-up "
        "questions about a paper that was already ingested. If notes do not clearly match the requested "
        "paper, do not speculate from them."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "top_k": {"type": "integer", "description": "Max results", "default": 5},
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return per note. Use larger values for paper follow-up questions.",
                "default": 6000,
            },
        },
        "required": ["query"],
    },
    handler=wiki_search,
    category="file_read",
    approval_required=False,
)
register(wiki_search_tool)

list_notes_tool = Tool(
    name="list_my_notes",
    description=(
        "List items already stored in the local knowledge base. Use only_papers=true when the user asks "
        "which papers are in the knowledge base, instead of searching by guessed keywords or shelling out "
        "to inspect directories."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "only_papers": {
                "type": "boolean",
                "description": "If true, list only paper notes",
                "default": False,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of notes to list",
                "default": 100,
            },
        },
    },
    handler=list_my_notes,
    category="file_read",
    approval_required=False,
)
register(list_notes_tool)



