"""Web-fetch tool."""

from urllib.parse import urlparse
from urllib.request import Request, urlopen

from nanoscholar.tools.tool import Tool, register
from nanoscholar import __version__


def read_web(url: str) -> str:
    parsed = urlparse(url)
    if parsed.path.lower().endswith(".pdf") or "/pdf/" in parsed.path.lower():
        return (
            "[PDF URL detected. Do not use read_web for PDFs. "
            "For arXiv papers, call arxiv_search first, then download_arxiv_pdf, "
            "then pdf_extract_text on the downloaded local file.]"
        )

    try:
        req = Request(url, headers={"User-Agent": f"nanoscholar/{__version__}"})
        with urlopen(req, timeout=10) as r:
            content_type = r.headers.get_content_type()
            if content_type == "application/pdf":
                return (
                    "[PDF content detected. Do not use read_web for PDFs. "
                    "For arXiv papers, call arxiv_search first, then download_arxiv_pdf, "
                    "then pdf_extract_text on the downloaded local file.]"
                )
            return r.read().decode(
                r.headers.get_content_charset() or "utf-8", errors="replace"
            )
    except Exception as e:
        return f"Error: {e}"


web_tool = Tool(
    name="read_web",
    description="Fetch decoded text from a web page or API. Do not use for PDF URLs; use download_arxiv_pdf and pdf_extract_text for arXiv PDFs.",
    input_schema={
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
    handler=read_web,
    category="network",
    approval_required=False,
)

register(web_tool)

