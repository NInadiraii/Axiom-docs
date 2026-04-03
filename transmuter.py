"""
Contextual Transmuter — converts informal, messy, or fragmented input
into high-stakes professional documents using Claude.
"""

import os
import anthropic

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Export it before starting the server."
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


SYSTEM_PROMPT = """You are a "Contextual Transmuter" Expert. Your goal is to take informal, messy, or fragmented input (handwritten notes, voice transcripts, or rough drafts) and convert them into high-stakes, professional documents.

CORE CAPABILITIES:

* Academic Rigor: If the input is student-focused (e.g., poetry analysis, lecture notes, literary study), structure it into a formal report with an Introduction, Thematic Analysis, Vocabulary Breakdown, and Scholarly Conclusion. Use APA/MLA formatting logic.

* Professional Compliance: If the input is business-focused (e.g., meeting notes, contract drafts, brainstorm sessions), structure it into a Statement of Work, formal Proposal, or Legal Memo as appropriate. Highlight any "Red Flags" or missing data points in a dedicated section.

* The "Bridge" Logic: Maintain the user's original intent but elevate the vocabulary to a "Senior Consultant" or "Post-Graduate" level. Never dumb down; always elevate.

CONSTRAINTS:

* Never say "Here is your report." or "Here is your document." Just generate the document directly.
* If the input is a poem or literary text, provide a section-by-section breakdown of deeper meanings.
* Use Markdown for clear hierarchy — Headings (##, ###), Tables, **Bolding**, and bullet points.
* If critical data is missing (e.g., a date, a client name, a dollar amount), insert a clear placeholder like [INSERT DATE HERE] or [CLIENT NAME].
* For business documents, always include a "Red Flags / Missing Information" section at the end if any gaps are detected.
* For academic documents, always include a "Vocabulary & Key Terms" section.
* Output length should match the complexity of the input — be thorough, not brief."""

ACADEMIC_HINT = "\n\nMODE OVERRIDE: Treat this as an ACADEMIC document. Structure with Introduction, Thematic Analysis, Vocabulary & Key Terms, and Scholarly Conclusion."
PROFESSIONAL_HINT = "\n\nMODE OVERRIDE: Treat this as a PROFESSIONAL/BUSINESS document. Structure as a formal Proposal, Statement of Work, or Legal Memo as appropriate. Include a Red Flags / Missing Information section."

_ACADEMIC_KEYWORDS = {
    "poem", "poetry", "analysis", "lecture", "essay", "thesis", "chapter",
    "literature", "stanza", "verse", "metaphor", "allegory", "symbolism",
    "narrative", "protagonist", "rhetorical", "literary", "anthology",
    "motif", "theme", "imagery", "prose", "sonnet", "haiku", "ballad",
}
_PROFESSIONAL_KEYWORDS = {
    "meeting", "contract", "proposal", "client", "budget", "revenue",
    "project", "scope", "deliverable", "timeline", "invoice", "vendor",
    "stakeholder", "roi", "kpi", "quarterly", "milestone", "sow",
    "agreement", "negotiation", "procurement", "compliance", "legal",
}


def detect_mode(text: str) -> str:
    """Heuristically detect whether the input is academic or professional."""
    words = set(text.lower().split())
    academic_score = len(words & _ACADEMIC_KEYWORDS)
    professional_score = len(words & _PROFESSIONAL_KEYWORDS)

    if academic_score > professional_score:
        return "academic"
    if professional_score > academic_score:
        return "professional"
    return "professional"  # default


def transmute(raw_text: str, mode: str = "auto", target_doc: str = "") -> dict:
    """
    Transmute raw informal input into a polished professional document.

    Args:
        raw_text:   The raw input text (notes, transcript, draft, etc.)
        mode:       "auto" | "academic" | "professional"
        target_doc: Optional description of the desired output document
                    (e.g. "5-page literary analysis for my professor",
                     "investor pitch deck proposal").

    Returns:
        {
            "document":      <markdown string>,
            "detected_mode": "academic" | "professional",
            "input_tokens":  <int>,
            "output_tokens": <int>,
        }
    """
    raw_text = raw_text.strip()
    if not raw_text:
        raise ValueError("Input text cannot be empty.")
    if len(raw_text) > 24_000:
        raise ValueError("Input exceeds 24,000 characters. Please shorten it.")

    detected_mode = mode if mode != "auto" else detect_mode(raw_text)

    # Build the user message
    parts = []
    if target_doc:
        parts.append(f"TARGET DOCUMENT TYPE: {target_doc}")
    parts.append(f"RAW INPUT:\n{raw_text}")
    user_content = "\n\n".join(parts)

    # Append mode hint to system prompt if explicitly set
    system = SYSTEM_PROMPT
    if mode == "academic":
        system += ACADEMIC_HINT
    elif mode == "professional":
        system += PROFESSIONAL_HINT

    client = _get_client()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )

    document = message.content[0].text

    return {
        "document": document,
        "detected_mode": detected_mode,
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
    }
