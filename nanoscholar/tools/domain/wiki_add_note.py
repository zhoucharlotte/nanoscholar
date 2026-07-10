"""MCP tool: add note to knowledge base."""

from nanoscholar.tools.tool import Tool, register
from nanoscholar.knowledge.wiki_store import save_note

def wiki_add_note(title: str, content: str, tags: str = "") -> str:
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    note_id = save_note(title, content, tag_list)
    return f"[Note saved] ID: {note_id}\nTitle: {title}"

wiki_add_note_tool = Tool(
    name="save_my_note",
    description="Save a note to your personal knowledge base (Markdown file). The note is stored as Markdown and indexed for search.",
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Note title"},
            "content": {"type": "string", "description": "Note content"},
            "tags": {"type": "string", "description": "Comma-separated tags"},
        },
        "required": ["title", "content"],
    },
    handler=wiki_add_note,
    category="file_write",
    approval_required=False,
)
register(wiki_add_note_tool)


