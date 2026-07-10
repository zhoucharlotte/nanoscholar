"""Geometry-only PDF text extraction using PyMuPDF text blocks."""

from nanoscholar.tools.tool import Tool, register


def _cluster_x_positions(blocks: list, page_width: float) -> list[list]:
    """Cluster text blocks by horizontal position."""
    if not blocks:
        return []

    ordered = sorted(blocks, key=lambda block: block[0])
    centers = [(block[0] + block[2]) / 2 for block in ordered]
    widths = [max(1.0, block[2] - block[0]) for block in ordered]
    median_width = sorted(widths)[len(widths) // 2]
    threshold = max(page_width * 0.08, median_width * 0.35)

    clusters: list[list] = []
    current = [ordered[0]]
    last_center = centers[0]
    for block, center in zip(ordered[1:], centers[1:]):
        if center - last_center <= threshold:
            current.append(block)
        else:
            clusters.append(current)
            current = [block]
        last_center = center
    clusters.append(current)
    return clusters


def _looks_like_two_columns(clusters: list[list], page_width: float) -> bool:
    if len(clusters) < 2:
        return False

    clusters = sorted(clusters, key=lambda group: min(block[0] for block in group))
    left = clusters[0]
    right = clusters[-1]
    total = sum(len(group) for group in clusters)
    if len(left) < total * 0.18 or len(right) < total * 0.18:
        return False

    left_edge = max(block[2] for block in left)
    right_edge = min(block[0] for block in right)
    gutter = right_edge - left_edge
    if gutter < page_width * 0.04:
        return False

    left_center = sum((block[0] + block[2]) / 2 for block in left) / len(left)
    right_center = sum((block[0] + block[2]) / 2 for block in right) / len(right)
    return right_center - left_center > page_width * 0.25


def _sort_blocks_by_columns(blocks: list, page_width: float) -> list:
    """Restore reading order for single-column and two-column academic PDFs."""
    if not blocks:
        return []

    clusters = _cluster_x_positions(blocks, page_width)
    if not _looks_like_two_columns(clusters, page_width):
        return sorted(blocks, key=lambda block: (block[1], block[0]))

    clusters = sorted(clusters, key=lambda group: min(block[0] for block in group))
    left = clusters[0]
    right = clusters[-1]
    middle = [block for group in clusters[1:-1] for block in group]

    wide = [block for block in blocks if block[2] - block[0] > page_width * 0.62]
    wide_ids = {id(block) for block in wide}
    left = [block for block in left if id(block) not in wide_ids]
    right = [block for block in right if id(block) not in wide_ids]
    middle = [block for block in middle if id(block) not in wide_ids]

    result = sorted(wide, key=lambda block: (block[1], block[0]))
    result.extend(sorted(left, key=lambda block: (block[1], block[0])))
    result.extend(sorted(middle, key=lambda block: (block[1], block[0])))
    result.extend(sorted(right, key=lambda block: (block[1], block[0])))
    return result


def pdf_extract_text(pdf_path: str, max_chars: int = 0, discard_headers: bool = True) -> str:
    """Extract text from PDF with geometry-only layout reconstruction.

    Args:
        pdf_path: Path to PDF file.
        max_chars: Max characters to return. 0 = full text.
        discard_headers: Skip blocks in top/bottom 8% of each page.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return "[PyMuPDF is not installed. Install the 'pymupdf' package to use pdf_extract_text.]"

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        return f"[Error opening PDF: {e}]"

    result_parts: list[str] = []
    total = 0

    try:
        for page in doc:
            page_width = page.rect.width
            page_height = page.rect.height
            blocks = [
                block
                for block in page.get_text("blocks")
                if len(block) >= 5 and str(block[4]).strip()
            ]

            if discard_headers:
                keep = []
                for block in blocks:
                    _, y0, _, y1, text = block[:5]
                    if not str(text).strip():
                        continue
                    if y0 < page_height * 0.08 or y1 > page_height * 0.92:
                        continue
                    keep.append(block)
                blocks = keep

            for block in _sort_blocks_by_columns(blocks, page_width):
                text = str(block[4]).strip()
                if not text:
                    continue
                if max_chars > 0 and total + len(text) > max_chars:
                    text = text[: max_chars - total]
                result_parts.append(text)
                total += len(text)
                if max_chars > 0 and total >= max_chars:
                    break

            if max_chars > 0 and total >= max_chars:
                break

        doc.close()
        return "\n\n".join(result_parts) if result_parts else "[No text extracted]"
    except Exception as e:
        doc.close()
        return f"[PDF extraction error: {e}]"


pdf_tool = Tool(
    name="pdf_extract_text",
    description=(
        "The required native tool for reading/extracting local PDF files. "
        "Uses zero-model geometry-only layout analysis over PyMuPDF text-block coordinates, "
        "including x-coordinate clustering for two-column academic papers and header/footer filtering. "
        "Use this after download_arxiv_pdf. Do not use execute_command, pip install, python scripts, curl, or read_web to parse PDFs."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pdf_path": {"type": "string", "description": "Path to the PDF file"},
            "max_chars": {"type": "integer", "description": "Max characters (0 for full text)", "default": 0},
            "discard_headers": {"type": "boolean", "description": "Skip page numbers and headers", "default": True},
        },
        "required": ["pdf_path"],
    },
    handler=pdf_extract_text,
    category="file_read",
    approval_required=False,
)
register(pdf_tool)

