"""Intent routing for progressive tool disclosure.

Layer 1: keyword anchoring.
Layer 2: lightweight offline matching against example queries.
Layer 3: history inheritance from recent tool calls.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from nanoscholar.tools.tool import list_tools

logger = logging.getLogger("nanoscholar.router")


_INTENTS: list[tuple[str, list[str], list[str]]] = [
    (
        "weather",
        ["\u5929\u6c14", "weather", "\u6e29\u5ea6", "\u6c14\u6e29", "wttr", "\u4e0b\u96e8", "\u4e0b\u96ea", "\u98ce", "\u6e7f\u5ea6"],
        ["read_web"],
    ),
    (
        "research",
        ["\u8bba\u6587", "paper", "arxiv", "research", "\u641c\u7d22", "\u5b66\u672f", "\u6587\u732e", "\u671f\u520a", "\u4f1a\u8bae"],
        ["ingest_paper", "arxiv_search", "semantic_scholar_search", "download_arxiv_pdf", "pdf_extract_text"],
    ),
    (
        "code",
        ["python", "\u4ee3\u7801", "\u8fd0\u884c", "\u8ba1\u7b97", "\u811a\u672c", "\u6267\u884c", "print", "\u6392\u5e8f", "\u7b97\u6cd5"],
        ["run_python_isolated", "execute_command"],
    ),
    (
        "experiment",
        ["\u5b9e\u9a8c", "\u8bb0\u5f55", "\u6307\u6807", "\u5bf9\u6bd4", "accuracy", "loss", "f1"],
        ["log_experiment", "compare_experiments"],
    ),
    (
        "knowledge",
        ["\u7b14\u8bb0", "\u77e5\u8bc6\u5e93", "wiki", "\u4fdd\u5b58", "\u8bb0\u4f4f", "note", "\u5907\u5fd8"],
        ["list_my_notes", "search_my_notes", "save_my_note"],
    ),
    (
        "task",
        ["\u63d0\u9192", "\u4efb\u52a1", "\u5b9a\u65f6", "\u8c03\u5ea6", "\u4ee5\u540e", "\u6bcf\u9694", "\u6bcf\u5929", "\u6bcf\u5c0f\u65f6", "\u5206\u949f"],
        ["add_task", "list_tasks", "remove_task"],
    ),
    (
        "file",
        ["\u6587\u4ef6", "\u76ee\u5f55", "\u6587\u4ef6\u5939", "\u5217\u8868", "\u8bfb\u53d6", "\u5199\u5165", "dir", "ls", "type", "del"],
        ["execute_command", "read_file", "write_file"],
    ),
    (
        "pdf",
        ["pdf", "\u6458\u8981", "\u63d0\u53d6", "\u6587\u6863"],
        ["pdf_extract_text", "read_file"],
    ),
]

_CORE: set[str] = {
    "execute_command",
    "read_file",
    "run_sub_agent",
    "run_sub_agents",
    "run_agent_team",
    "search_my_notes",
}

_RESEARCH_HINTS = [
    "paper",
    "arxiv",
    "pdf",
    "research",
    "inter:",
    "mitigating hallucination",
    "vision-language",
    "large vision-language",
    "璁烘枃",
    "鏂囩尞",
    "杩欑瘒",
]

_RESEARCH_HINTS.extend(
    [
        "article",
        "literature",
        "survey",
        "llm",
        "language model",
        "agent memory",
        "small language model",
        "\u8bba\u6587",
        "\u6587\u7ae0",
        "\u6587\u732e",
        "\u5b66\u672f",
        "\u8fd9\u7bc7",
        "\u5e2e\u6211\u770b\u770b",
        "\u5728\u505a\u4ec0\u4e48",
        "\u8bf4\u4e86\u4ec0\u4e48",
        "\u8bb2\u4e86\u4ec0\u4e48",
    ]
)

_COMMAND_HINTS = [
    "execute_command",
    "shell",
    "cmd",
    "powershell",
    "\u547d\u4ee4",
    "\u7ec8\u7aef",
]

_CLEAN_RESEARCH_HINTS = [
    "\u8bba\u6587",
    "\u6587\u732e",
    "\u6587\u7ae0",
    "\u5b66\u672f",
    "\u8fd9\u7bc7",
    "\u8fd9\u7bc7\u6587\u732e",
    "\u8fd9\u7bc7\u6587\u7ae0",
    "\u5e2e\u6211\u770b\u770b",
    "\u5e2e\u6211\u627e",
    "\u627e\u4e00\u4e0b",
    "\u8bb2\u4e86\u4ec0\u4e48",
    "\u8bf4\u4e86\u4ec0\u4e48",
    "\u5728\u505a\u4ec0\u4e48",
    "\u6709\u4ec0\u4e48\u542f\u53d1",
    "paper",
    "arxiv",
    "pdf",
    "literature",
    "article",
    "survey",
]

_CLEAN_RESEARCH_HINTS.extend(
    [
        "\u8bba\u6587",
        "\u6587\u732e",
        "\u6587\u7ae0",
        "\u5b66\u672f",
        "\u8fd9\u7bc7",
        "\u8fd9\u7bc7\u6587\u732e",
        "\u8fd9\u7bc7\u6587\u7ae0",
        "\u5e2e\u6211\u770b\u770b",
        "\u5e2e\u6211\u627e",
        "\u627e\u4e00\u4e0b",
        "\u8bb2\u4e86\u4ec0\u4e48",
        "\u8bf4\u4e86\u4ec0\u4e48",
        "\u5728\u505a\u4ec0\u4e48",
        "\u6709\u4ec0\u4e48\u542f\u53d1",
    ]
)

_KNOWLEDGE_LISTING_HINTS = [
    "\u6211\u7684\u77e5\u8bc6\u5e93",
    "\u77e5\u8bc6\u5e93\u91cc",
    "\u77e5\u8bc6\u5e93\u91cc\u6709\u54ea\u4e9b",
    "\u6709\u54ea\u4e9b\u8bba\u6587",
    "\u5217\u51fa\u77e5\u8bc6\u5e93",
    "\u5217\u51fa\u8bba\u6587",
    "\u7b14\u8bb0\u5217\u8868",
    "knowledge base",
    "what papers",
    "list papers",
    "list notes",
]

_INTENT_EXAMPLES: dict[str, list[str]] = {
    "weather": [
        "\u4eca\u5929\u5929\u6c14\u600e\u4e48\u6837",
        "\u660e\u5929\u4f1a\u4e0b\u96e8\u5417",
        "\u5317\u4eac\u6e29\u5ea6\u591a\u5c11",
        "\u67e5\u4e00\u4e0b\u4e0a\u6d77\u7684\u5929\u6c14",
        "\u6c14\u6e29\u591a\u5c11\u5ea6",
        "\u6700\u8fd1\u51e0\u5929\u51b7\u5417",
        "\u6e7f\u5ea6\u591a\u5c11",
        "\u660e\u5929\u9002\u5408\u51fa\u95e8\u5417",
    ],
    "research": [
        "\u641c\u7d22\u8bba\u6587",
        "\u627e\u4e00\u4e0b\u5173\u4e8e transformer \u7684\u6587\u7ae0",
        "\u67e5\u6587\u732e",
        "\u5b66\u672f\u641c\u7d22",
        "\u5e2e\u6211\u627e\u4e00\u7bc7 attention \u7684\u8bba\u6587",
        "\u641c\u4e00\u4e0b\u6700\u65b0\u7684\u7814\u7a76",
        "\u67e5\u4e00\u4e0b\u8fd9\u4e2a\u65b9\u5411\u7684\u8bba\u6587",
        "\u627e\u53c2\u8003\u6587\u732e",
    ],
    "code": [
        "\u8fd0\u884c\u4e00\u6bb5 python \u4ee3\u7801",
        "\u5e2e\u6211\u7b97\u4e00\u4e2a",
        "\u5199\u4e00\u4e2a\u6392\u5e8f\u7b97\u6cd5",
        "\u6267\u884c\u4ee3\u7801",
        "\u8ba1\u7b97 1+1",
        "\u5e2e\u6211\u5199\u4e2a\u7a0b\u5e8f",
        "\u7b97\u7b97\u8fd9\u4e2a\u8868\u8fbe\u5f0f",
    ],
    "experiment": [
        "\u8bb0\u5f55\u5b9e\u9a8c\u7ed3\u679c",
        "\u5bf9\u6bd4\u4e00\u4e0b\u6307\u6807",
        "\u8bb0\u5f55\u5b9e\u9a8c",
        "\u67e5\u5b9e\u9a8c\u8bb0\u5f55",
        "\u770b\u770b\u4e0a\u6b21\u5b9e\u9a8c\u7684\u6548\u679c",
    ],
    "knowledge": [
        "\u67e5\u770b\u6211\u7684\u7b14\u8bb0",
        "\u641c\u7d22\u7b14\u8bb0",
        "\u67e5\u4e00\u4e0b\u77e5\u8bc6\u5e93",
        "\u4fdd\u5b58\u8fd9\u6761\u4fe1\u606f",
        "\u5e2e\u6211\u8bb0\u4f4f",
        "\u770b\u770b\u6211\u8bb0\u8fc7\u4ec0\u4e48",
    ],
    "task": [
        "\u63d0\u9192\u6211",
        "\u5b9a\u4e00\u4e2a\u4efb\u52a1",
        "\u6bcf\u5929\u6267\u884c",
        "\u5b9a\u65f6\u63d0\u9192",
        "\u5e2e\u6211\u8bb0\u4f4f\u4ee5\u540e",
        "\u8bbe\u7f6e\u4e00\u4e2a\u5b9a\u65f6\u4efb\u52a1",
    ],
    "file": [
        "\u67e5\u770b\u6587\u4ef6",
        "\u8bfb\u53d6\u6587\u4ef6",
        "\u5217\u51fa\u76ee\u5f55",
        "\u4fdd\u5b58\u6587\u4ef6",
        "\u5199\u6587\u4ef6",
        "\u770b\u770b\u76ee\u5f55\u5185\u5bb9",
    ],
    "pdf": [
        "\u63d0\u53d6 PDF \u6458\u8981",
        "\u8bfb\u4e00\u4e0b\u8fd9\u7bc7\u8bba\u6587",
        "PDF \u63d0\u53d6",
        "\u89e3\u6790 PDF",
        "\u5e2e\u6211\u770b\u4e00\u4e0b\u8fd9\u4e2a PDF",
    ],
}


def _tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens = [w for w in re.findall(r"[a-z0-9]+", text) if len(w) > 1]
    chars = [c for c in text if "\u4e00" <= c <= "\u9fff"]
    tokens.extend(chars[i] + chars[i + 1] for i in range(len(chars) - 1))
    if len(chars) <= 4:
        tokens.extend(chars)
    return tokens


def _example_match(query: str) -> tuple[str | None, float]:
    q_tokens = _tokenize(query)
    if not q_tokens:
        return None, 0.0

    q_counts = Counter(q_tokens)
    best_intent: str | None = None
    best_score = 0.0

    for intent, examples in _INTENT_EXAMPLES.items():
        for example in examples:
            ex_counts = Counter(_tokenize(example))
            common = set(q_counts) & set(ex_counts)
            if not common:
                continue
            dot = sum(q_counts[t] * ex_counts[t] for t in common)
            denom = (
                sum(c * c for c in q_counts.values()) ** 0.5
                * sum(c * c for c in ex_counts.values()) ** 0.5
            )
            score = dot / denom if denom else 0.0
            if score > best_score:
                best_score = score
                best_intent = intent

    if best_score >= 0.25:
        return best_intent, round(best_score, 3)
    return None, round(best_score, 3)


def _add_intent_tools(result: dict[str, Any], intent: str, confidence: float, layer: int) -> None:
    for intent_name, _keywords, tool_names in _INTENTS:
        if intent_name == intent:
            result["tools"].update(tool_names)
            result["intent"] = intent
            result["confidence"] = confidence
            result["layer"] = layer
            return


def _is_research_like(query: str, intent: str | None) -> bool:
    lower = query.lower()
    return intent in {"research", "pdf"} or any(
        hint in lower for hint in (_RESEARCH_HINTS + _CLEAN_RESEARCH_HINTS)
    )


def _is_knowledge_listing_request(query: str) -> bool:
    lower = query.lower()
    return any(hint in lower for hint in _KNOWLEDGE_LISTING_HINTS)


def _looks_like_paper_title_request(query: str) -> bool:
    """Catch English paper-title queries followed by Chinese reading requests."""
    text = query.strip()
    lower = text.lower()
    if not text:
        return False

    academic_terms = [
        "llm",
        "language model",
        "agent",
        "memory",
        "reasoning",
        "visual",
        "uncertainty",
        "collaboration",
        "hallucination",
        "transformer",
    ]
    ask_terms = [
        "\u8bba\u6587",
        "\u6587\u7ae0",
        "\u6587\u732e",
        "\u8fd9\u7bc7",
        "\u5e2e\u6211\u770b\u770b",
        "\u770b\u770b\u8fd9\u7bc7",
        "\u5728\u505a\u4ec0\u4e48",
        "\u8bf4\u4e86\u4ec0\u4e48",
        "\u8bb2\u4e86\u4ec0\u4e48",
        "summary",
        "summarize",
    ]
    has_academic_signal = any(term in lower for term in academic_terms)
    has_ask_signal = any(term in lower for term in (ask_terms + _CLEAN_RESEARCH_HINTS))
    title_words = re.findall(r"[A-Za-z][A-Za-z0-9-]+", text)
    title_like = len(title_words) >= 4 and sum(1 for word in title_words if word[:1].isupper()) >= 2
    return (has_academic_signal and has_ask_signal) or (title_like and has_ask_signal)


def _explicitly_requests_command(query: str) -> bool:
    lower = query.lower()
    return any(hint in lower for hint in _COMMAND_HINTS)


def classify(query: str, history: list[dict] | None = None) -> dict[str, Any]:
    """Classify a user query and return selected tool names plus routing metadata."""
    if not query.strip():
        return {
            "tools": {"search_my_notes"},
            "intent": None,
            "confidence": 0.0,
            "layer": 0,
        }

    result: dict[str, Any] = {
        "tools": set(_CORE),
        "intent": None,
        "confidence": 0.0,
        "layer": 0,
    }
    text = query.lower()

    if _is_knowledge_listing_request(query):
        _add_intent_tools(result, "knowledge", 0.99, 1)
        return result

    if _looks_like_paper_title_request(query):
        _add_intent_tools(result, "research", 0.98, 1)
        return result

    for intent_name, keywords, tool_names in _INTENTS:
        matched = [kw for kw in keywords if kw in text]
        if matched:
            score = min(0.95 + 0.02 * (len(matched) - 1), 0.99)
            result["tools"].update(tool_names)
            if score > result["confidence"]:
                result["intent"] = intent_name
                result["confidence"] = score
                result["layer"] = 1

    if result["confidence"] < 0.85:
        intent, score = _example_match(text)
        if intent:
            _add_intent_tools(result, intent, score, 2)

    if result["confidence"] < 0.7 and history:
        for msg in history[-8:]:
            if msg.get("role") != "assistant" or not msg.get("tool_calls"):
                continue
            for tc in msg["tool_calls"]:
                fn = tc.get("function", tc)
                tname = fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)
                if tname:
                    result["tools"].add(tname)
        if any(t not in _CORE for t in result["tools"]):
            result["confidence"] = max(result["confidence"], 0.6)
            if result["layer"] == 0:
                result["layer"] = 3

    return result


def route(user_input: str) -> list[str]:
    """Return relevant tool names for the user input."""
    return sorted(classify(user_input)["tools"])


def build_schema(user_input: str, history: list[dict] | None = None) -> list[dict]:
    """Build a filtered OpenAI-compatible tools schema."""
    classified = classify(user_input, history)
    selected_names = classified["tools"]
    recent_text = " ".join(
        str(m.get("content", "")) for m in (history or [])[-8:]
    )
    research_context = _is_research_like(
        f"{user_input}\n{recent_text}", classified["intent"]
    )
    if research_context and not _explicitly_requests_command(user_input):
        selected_names = selected_names - {
            "execute_command",
            "run_python_isolated",
            "run_sub_agent",
            "run_sub_agents",
            "run_agent_team",
            "write_file",
        }
    if classified["intent"] == "knowledge" and _is_knowledge_listing_request(user_input):
        selected_names = selected_names - {
            "execute_command",
            "write_file",
            "run_python_isolated",
            "run_sub_agent",
            "run_sub_agents",
            "run_agent_team",
        }

    all_tools = list_tools()
    priority = {
        "list_my_notes": 0,
        "ingest_paper": 0,
        "search_my_notes": 1,
        "arxiv_search": 2,
        "semantic_scholar_search": 3,
        "download_arxiv_pdf": 4,
        "pdf_extract_text": 5,
    }
    selected = sorted(
        [t for t in all_tools if t.name in selected_names],
        key=lambda t: priority.get(t.name, 100),
    )
    if not selected:
        selected = all_tools

    logger.info(
        "Route: %d/%d tools (intent=%s conf=%.2f layer=%d)",
        len(selected),
        len(all_tools),
        classified["intent"] or "none",
        classified["confidence"],
        classified["layer"],
    )

    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in selected
    ]

