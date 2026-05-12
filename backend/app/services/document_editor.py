"""Section-level Markdown editor for the generated guide.

The guide uses fixed `## Section Name` headings. This module replaces a single
section's body while leaving the rest of the document untouched, so the agent
can update one section at a time without rewriting the whole file.
"""

import re
from typing import Iterable


SECTIONS: tuple[str, ...] = (
    "Document Status",
    "Version History",
    "Page Overview",
    "Where To Find This Page",
    "Who Can Access",
    "Page Layout",
    "How To Use This Page",
    "Form Fields & Validations",
    "Tips & Shortcuts",
    "Browser Walkthrough Evidence",
    "Screenshots And Assets",
    "Limitations & Known Issues",
    "Gaps & Red Flags",
    "FAQ",
    "Approval",
)


RED_FLAGS_SECTION = "Gaps & Red Flags"
SCREENSHOTS_SECTION = "Screenshots And Assets"


def _heading_regex(name: str) -> re.Pattern[str]:
    escaped = re.escape(name)
    return re.compile(rf"^##\s+{escaped}\s*$", re.MULTILINE)


def resolve_section(name: str) -> str | None:
    """Match a section name case-insensitively against the known sections."""
    target = name.strip().lower()
    for s in SECTIONS:
        if s.lower() == target:
            return s
    return None


def replace_section(doc: str, section_name: str, new_body: str) -> str:
    """Replace the body of `## {section_name}` until the next `## ` heading or EOF."""
    resolved = resolve_section(section_name)
    if resolved is None:
        raise ValueError(f"Unknown section: {section_name!r}")

    heading_re = _heading_regex(resolved)
    match = heading_re.search(doc)
    if match is None:
        raise ValueError(f"Section heading not found in document: {resolved!r}")

    body_start = match.end()
    next_heading = re.search(r"^##\s+\S", doc[body_start:], re.MULTILINE)
    body_end = body_start + next_heading.start() if next_heading else len(doc)

    cleaned = new_body.strip()
    return doc[:body_start] + "\n" + cleaned + "\n\n" + doc[body_end:]


def append_red_flag(doc: str, expected: str, observed: str, recommended: str) -> str:
    """Append a red-flag entry to the Gaps & Red Flags section."""
    heading = RED_FLAGS_SECTION
    heading_re = _heading_regex(heading)
    match = heading_re.search(doc)
    if match is None:
        raise ValueError(f"{heading} section missing")

    body_start = match.end()
    next_heading = re.search(r"^##\s+\S", doc[body_start:], re.MULTILINE)
    body_end = body_start + next_heading.start() if next_heading else len(doc)
    existing = doc[body_start:body_end].strip()

    entry = (
        f"- **Expected:** {expected.strip()}\n"
        f"  **Observed:** {observed.strip()}\n"
        f"  **Recommended:** {recommended.strip()}"
    )

    if existing in ("", "_None recorded yet._"):
        new_body = entry
    else:
        new_body = existing + "\n" + entry

    return doc[:body_start] + "\n" + new_body + "\n\n" + doc[body_end:]


def section_names_for_prompt(browser_enabled: bool) -> Iterable[str]:
    for s in SECTIONS:
        if not browser_enabled and s == "Browser Walkthrough Evidence":
            continue
        yield s


def append_to_section(doc: str, section_name: str, markdown_to_append: str) -> str:
    """Append Markdown content to the end of a section's existing body."""
    resolved = resolve_section(section_name)
    if resolved is None:
        raise ValueError(f"Unknown section: {section_name!r}")

    heading_re = _heading_regex(resolved)
    match = heading_re.search(doc)
    if match is None:
        raise ValueError(f"Section heading not found in document: {resolved!r}")

    body_start = match.end()
    next_heading = re.search(r"^##\s+\S", doc[body_start:], re.MULTILINE)
    body_end = body_start + next_heading.start() if next_heading else len(doc)
    existing = doc[body_start:body_end].strip()

    # An italic-only single-line body (e.g. "_TBD_", "_None recorded yet._",
    # "_Annotated screenshots of the page…_") is a placeholder — replace it
    # rather than appending below it.
    is_placeholder = bool(re.fullmatch(r"_[^_\n]+_", existing))

    if existing == "" or is_placeholder:
        new_body = markdown_to_append.strip()
    else:
        new_body = existing + "\n\n" + markdown_to_append.strip()

    return doc[:body_start] + "\n" + new_body + "\n\n" + doc[body_end:]
