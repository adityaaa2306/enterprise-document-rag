"""
Heading Validation Engine.

Does not trust triage/PyPDF Title labels. Scores every candidate with
visual, structural, linguistic, semantic, and document signals, then
classifies and accepts/rejects.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.core.config import settings
from src.structure.types import HeadingClass, HeadingDecision, LayoutBlock

log = logging.getLogger(__name__)

# Generalized section lexicon (research / tech / legal / financial / manuals).
_HEADING_LEXICON = {
    "abstract",
    "acknowledgement",
    "acknowledgment",
    "acknowledgements",
    "acknowledgments",
    "appendix",
    "background",
    "bibliography",
    "conclusion",
    "conclusions",
    "contents",
    "discussion",
    "evaluation",
    "executive summary",
    "experiment",
    "experiments",
    "findings",
    "future work",
    "glossary",
    "implementation",
    "index",
    "introduction",
    "literature review",
    "method",
    "methodology",
    "methods",
    "motivation",
    "objective",
    "objectives",
    "overview",
    "preface",
    "problem statement",
    "references",
    "related work",
    "results",
    "scope",
    "summary",
    "system architecture",
    "system design",
    "table of contents",
    "toc",
    "works cited",
    # tech / product reports
    "architecture",
    "assumptions",
    "carbon",
    "chunking",
    "design",
    "limitations",
    "pipeline",
    "routing",
    "security",
    "threat model",
    "validation",
    # financial / legal / gov
    "article",
    "balance sheet",
    "cash flow",
    "clause",
    "financial statements",
    "income statement",
    "notes",
    "risk factors",
    "schedule",
    "section",
}

_NUMBERED = re.compile(
    r"^(?:"
    r"(?:chapter|section|part|appendix|article|clause)\s+[ivxlcdm\d]+[.:)\-]?\s+"
    r"|\d+(?:\.\d+){0,4}\.?\s+"
    r"|[IVXLCDM]+\.\s+"
    r"|[A-Z]\.\s+"
    r")",
    re.I,
)
_MARKDOWN = re.compile(r"^#{1,6}\s+\S+")
_DATE = re.compile(
    r"^(?:"
    r"(?:date\s*[:\-]\s*)?"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\s+\d{4}"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|date\s*[:\-].*"
    r")$",
    re.I,
)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
_URL = re.compile(r"https?://|www\.", re.I)
_FIGURE = re.compile(r"^(?:figure|fig\.|table|eq\.|equation|algorithm)\s*[\d.:]", re.I)
_CAPTION = re.compile(r"^(?:figure|fig\.|table|caption)\b", re.I)
_PAGE_NUM = re.compile(r"^(?:page\s+)?\d{1,4}$", re.I)
_STATUS = re.compile(r"^(?:status|version|rev(?:ision)?|draft)\s*[:\-]", re.I)
_TEAM_LABEL = re.compile(
    r"^(?:team(?:\s+members?)?|author(?:s)?|prepared by|submitted by|"
    r"supervisor|advisor|mentor|affiliation|department|university|"
    r"institute|organization|email|phone|address|contact)\s*:?\s*$",
    re.I,
)
_PERSON = re.compile(
    r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}$"
)
_PERSON_DENY = {
    "project manager",
    "team members",
    "frontend choices",
    "backend choices",
    "users table",
    "documents table",
    "chunks table",
    "key outcomes",
    "future work",
    "related work",
    "problem statement",
    "system design",
    "model design",
    "data flow",
    "tech stack",
}
_AFFILIATION = re.compile(
    r"\b(university|institute|college|department|ltd|inc|corp|gmbh|pvt)\b",
    re.I,
)
_VERBISH = re.compile(
    r"\b(is|are|was|were|be|been|being|have|has|had|do|does|did|"
    r"will|would|should|could|can|may|might|must|shall)\b",
    re.I,
)


def _letters(s: str) -> str:
    return "".join(c for c in s if c.isalpha())


def _upper_ratio(s: str) -> float:
    letters = _letters(s)
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def _title_case_ratio(words: Sequence[str]) -> float:
    alpha = [w for w in words if w[:1].isalpha()]
    if not alpha:
        return 0.0
    return sum(1 for w in alpha if w[:1].isupper()) / len(alpha)


def _lexicon_hit(text: str) -> bool:
    # Do NOT strip Roman-numeral letters from the word itself (re.I + IVXLCDM
    # previously turned "Introduction" into "ntroduction").
    t = (text or "").strip()
    t = re.sub(
        r"^(?:(?:chapter|section|part|appendix|article|clause)\s+[ivxlcdm\d]+[.:)\-]?\s+)",
        "",
        t,
        flags=re.I,
    )
    t = re.sub(r"^[\d.\s\-#:]+", "", t).strip().lower()
    t = re.sub(r"[^\w\s\-]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return False
    if t in _HEADING_LEXICON:
        return True
    tokens = t.replace("-", " ").split()
    for phrase in _HEADING_LEXICON:
        if " " in phrase:
            if phrase in t and len(t) <= len(phrase) + 24:
                return True
        else:
            if phrase in tokens and len(tokens) <= 2:
                return True
            if tokens and tokens[-1] == phrase and len(tokens) <= 2:
                return True
    return False


def score_heading_candidate(
    block: LayoutBlock,
    *,
    prev_blank: bool = False,
    next_blank: bool = False,
    page_line_index: int = 0,
    page_line_count: int = 1,
    triage_marked_title: bool = False,
) -> HeadingDecision:
    """
    Multi-signal heading confidence in [0, 1] + classification.
    """
    text = (block.text or "").strip()
    signals: Dict[str, Any] = {
        "triage_marked_title": triage_marked_title,
        "prev_blank": prev_blank,
        "next_blank": next_blank,
    }
    reject: List[str] = []
    score = 0.0

    if not text or len(text) < 2:
        return HeadingDecision(
            block_index=block.index,
            text=text,
            confidence=0.0,
            classification="ignore",
            accepted=False,
            signals=signals,
            reject_reasons=["empty"],
        )

    words = text.split()
    n_words = len(words)
    signals["word_count"] = n_words
    signals["length"] = len(text)
    signals["upper_ratio"] = round(_upper_ratio(text), 3)
    signals["title_case_ratio"] = round(_title_case_ratio(words), 3)

    # --- Hard reject linguistic / metadata ---
    if _EMAIL.search(text) or _URL.search(text):
        reject.append("email_or_url")
    if _DATE.match(text) or (
        n_words <= 6 and re.search(r"\b20\d{2}\b", text) and "chapter" not in text.lower()
    ):
        # bare dates / "Date: December 2025"
        if _DATE.match(text) or text.lower().startswith("date"):
            reject.append("date")
    if _PAGE_NUM.match(text):
        reject.append("page_number")
    if _TEAM_LABEL.match(text) or (text.rstrip().endswith(":") and n_words <= 5):
        reject.append("label_or_colon_metadata")
    # Mid-line colon labels ("Architecture: Decoder-only Transformer")
    if ":" in text and not _NUMBERED.match(text) and not _MARKDOWN.match(text):
        left = text.split(":", 1)[0].strip()
        if len(left.split()) <= 4:
            reject.append("label_or_colon_metadata")
    if _STATUS.match(text):
        reject.append("status_metadata")
    if _PERSON.match(text) and not _lexicon_hit(text) and not _NUMBERED.match(text):
        if text.strip().lower() not in _PERSON_DENY and not any(
            w.lower() in {"table", "choices", "manager", "diagram", "schema", "flow"}
            for w in text.split()
        ):
            reject.append("person_name")
    if _AFFILIATION.search(text) and n_words <= 10 and not _NUMBERED.match(text):
        reject.append("affiliation")
    if text.endswith((".", ",", ";", "?")) and not _NUMBERED.match(text):
        reject.append("sentence_punctuation")
    if n_words > 16 and not _MARKDOWN.match(text):
        reject.append("too_long")
    if _VERBISH.search(text) and n_words >= 6 and not _lexicon_hit(text):
        reject.append("verb_phrase_sentence")

    # Inside table / figure markers from upstream
    bt = (block.block_type or "").lower()
    if bt == "table" or "table" in (block.meta or {}):
        reject.append("inside_table")
    if block.meta.get("in_footer"):
        reject.append("footer")
    if block.meta.get("in_header"):
        reject.append("header")

    # Classification priors from patterns
    classification: HeadingClass = "body"
    level = 0

    if "date" in reject:
        classification = "date"
    elif "person_name" in reject:
        classification = "person_name"
    elif "label_or_colon_metadata" in reject or "status_metadata" in reject:
        classification = "label" if "label_or_colon_metadata" in reject else "metadata"
    elif "affiliation" in reject:
        classification = "metadata"
    elif "footer" in reject:
        classification = "footer"
    elif "header" in reject:
        classification = "header"
    elif _FIGURE.match(text) or _CAPTION.match(text):
        classification = "figure_title" if text.lower().startswith("fig") else "table_title"
        if "caption" in text.lower() or _CAPTION.match(text):
            classification = "caption"
        score += 0.25  # captions are recognized but not section openers
        signals["caption_like"] = True
    else:
        # Structural boosts
        if _MARKDOWN.match(text):
            rest_md = re.sub(r"^#{1,6}\s+", "", text).strip()
            # Code-comment / schema dump style — not a document section heading
            if (
                re.match(r"^[a-z]", rest_md)
                or re.search(r"\b(API|JSON|SQL|HTTP|GET|POST|BaseModel|Collection)\b", rest_md)
                or re.match(r"^(User|Document|RAG|ChromaDB|Query)\b", rest_md)
            ):
                score += 0.05
                signals["markdown_codeish"] = True
                reject.append("markdown_code_comment")
            else:
                score += 0.55
                level = min(3, text.count("#"))
                classification = (
                    "major_heading"
                    if level <= 1
                    else ("minor_heading" if level == 2 else "subsection")
                )
                signals["markdown"] = True
        if _NUMBERED.match(text):
            rest = re.sub(
                r"^(?:(?:chapter|section|part|appendix|article|clause)\s+[ivxlcdm\d]+[.:)\-]?\s+"
                r"|\d+(?:\.\d+){0,4}\.?\s+"
                r"|[IVXLCDM]+\.\s+"
                r"|[A-Z]\.\s+)",
                "",
                text,
                flags=re.I,
            ).strip()
            multi = bool(re.match(r"^\d+\.\d+", text.strip()))
            rest_upper = _upper_ratio(rest) >= 0.72
            lex = _lexicon_hit(rest) or _lexicon_hit(text)
            if multi:
                score += 0.55
                level = 2 if text.split()[0].count(".") == 1 else 3
                classification = "minor_heading" if level == 2 else "subsection"
                signals["numbered_subsection"] = True
            elif rest_upper or lex or re.search(
                r"\b(chapter|section|appendix|part|article|clause)\b", text, re.I
            ):
                score += 0.55
                level = 1
                classification = "major_heading"
                signals["numbered_major"] = True
            elif re.match(
                r"^(?:article|clause|section)\s+\d+", text.strip(), re.I
            ):
                score += 0.55
                level = 1
                classification = "major_heading"
                signals["legal_article"] = True
            elif _title_case_ratio(rest.split()) >= 0.85 and 2 <= len(rest.split()) <= 8:
                # TOC-style "3. Tech Stack" — real heading; still weaker than ALL CAPS chapters
                score += 0.38
                level = 1
                classification = "minor_heading"
                signals["numbered_title_case"] = True
            else:
                # Likely a numbered list item
                score += 0.10
                signals["numbered_listish"] = True
                if classification == "body":
                    classification = "ignore"
        if _lexicon_hit(text):
            score += 0.55  # exact/primary lexicon headings clear the threshold alone
            if classification == "body":
                classification = "major_heading"
                level = 1
            signals["lexicon"] = True

        # Visual / orthographic
        if prev_blank:
            score += 0.08
        if next_blank:
            score += 0.05
        ur = _upper_ratio(text)
        if ur >= 0.85 and 2 <= n_words <= 10:
            score += 0.28
            signals["all_caps"] = True
            if classification == "body":
                classification = "minor_heading"
                level = 2
        tcr = _title_case_ratio(words)
        if tcr >= 0.85 and 2 <= n_words <= 10 and not text.endswith(":"):
            score += 0.18
            signals["title_case"] = True
            if classification == "body":
                classification = "minor_heading"
                level = 2

        # Short isolated lines near top of page slightly boosted
        if page_line_count > 0 and page_line_index <= 2 and n_words <= 8:
            score += 0.05
            signals["page_top"] = True

        # Triage Title is a weak prior only
        if triage_marked_title:
            score += 0.10
            signals["triage_prior"] = True

        # Downgrade title-case alone without other evidence
        if (
            signals.get("title_case")
            and not signals.get("numbered")
            and not signals.get("lexicon")
            and not signals.get("all_caps")
            and not signals.get("markdown")
        ):
            score -= 0.12
            signals["title_case_alone_penalty"] = True

    # Apply reject penalties
    hard = {
        "email_or_url",
        "date",
        "page_number",
        "label_or_colon_metadata",
        "status_metadata",
        "person_name",
        "affiliation",
        "inside_table",
        "footer",
        "header",
        "sentence_punctuation",
        "too_long",
        "verb_phrase_sentence",
        "markdown_code_comment",
    }
    hard_hits = [r for r in reject if r in hard]
    if hard_hits:
        score = min(score, 0.25)
        score -= 0.15 * len(hard_hits)

    score = max(0.0, min(1.0, score))

    # Captions / non-section classes never open sections
    threshold = float(getattr(settings, "HEADING_CONFIDENCE_THRESHOLD", 0.55) or 0.55)
    opens = classification in ("major_heading", "minor_heading", "subsection")
    accepted = bool(opens and score >= threshold and not hard_hits)

    if not opens and classification not in (
        "caption",
        "table_title",
        "figure_title",
        "date",
        "person_name",
        "label",
        "metadata",
        "footer",
        "header",
        "ignore",
        "body",
    ):
        classification = "ignore"

    if not accepted and opens:
        reject.append(f"below_threshold_{threshold}")
        # demote failed opener candidates
        if score < threshold:
            classification = "ignore"

    return HeadingDecision(
        block_index=block.index,
        text=text,
        confidence=round(score, 4),
        classification=classification if accepted or classification != "body" else "ignore",
        accepted=accepted,
        level=level if accepted else 0,
        signals=signals,
        reject_reasons=reject,
    )


def validate_headings(
    blocks: Sequence[LayoutBlock],
) -> Tuple[List[HeadingDecision], List[HeadingDecision], List[HeadingDecision]]:
    """
    Return (all_decisions, accepted, rejected_candidates).
    Every short/title-like line is scored; long body paragraphs skipped as candidates.
    """
    decisions: List[HeadingDecision] = []
    # Precompute blank-line neighbors using empty blocks or meta
    texts = [(b.text or "").strip() for b in blocks]

    for i, block in enumerate(blocks):
        text = texts[i]
        if not text:
            continue
        words = text.split()
        triage_title = (block.block_type or "") == "Title"
        # Candidate if triage said Title, or short line, or numbered/markdown
        is_candidate = (
            triage_title
            or len(words) <= 14
            or bool(_NUMBERED.match(text))
            or bool(_MARKDOWN.match(text))
        )
        if not is_candidate:
            continue
        # Skip huge body paragraphs
        if len(words) > 20 and not _NUMBERED.match(text) and not _MARKDOWN.match(text):
            continue

        prev_blank = i == 0 or not texts[i - 1]
        next_blank = i + 1 >= len(texts) or not texts[i + 1]
        page = block.page
        page_idxs = [j for j, b in enumerate(blocks) if b.page == page]
        page_line_index = page_idxs.index(i) if i in page_idxs else 0
        page_line_count = max(1, len(page_idxs))

        d = score_heading_candidate(
            block,
            prev_blank=prev_blank,
            next_blank=next_blank,
            page_line_index=page_line_index,
            page_line_count=page_line_count,
            triage_marked_title=triage_title,
        )
        decisions.append(d)

    accepted = [d for d in decisions if d.accepted]
    rejected = [d for d in decisions if not d.accepted]
    log.info(
        "HeadingValidation: candidates=%s accepted=%s rejected=%s threshold=%s",
        len(decisions),
        len(accepted),
        len(rejected),
        getattr(settings, "HEADING_CONFIDENCE_THRESHOLD", 0.55),
    )
    return decisions, accepted, rejected
