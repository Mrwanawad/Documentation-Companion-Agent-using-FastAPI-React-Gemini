"""Section-level Markdown editor for the generated guide.

The guide uses fixed `## Section Name` headings. This module replaces a single
section's body while leaving the rest of the document untouched, so the agent
can update one section at a time without rewriting the whole file.

Sections are bilingual: every section has a canonical English name (the key used
throughout the backend) and an Arabic label. Heading lookups match EITHER
language, so the same code path works whether the guide was authored in English
or Arabic, and a guide can be switched between the two with
`set_document_language`.
"""

import re
from datetime import datetime, timezone
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
    "Attachments & References",
    "Approval",
)


# Canonical English name -> Arabic heading label. The English label IS the
# canonical key. Keep this the single source of truth for section names.
SECTION_LABELS: dict[str, dict[str, str]] = {
    "Document Status": {"en": "Document Status", "ar": "حالة المستند"},
    "Version History": {"en": "Version History", "ar": "سجل الإصدارات"},
    "Page Overview": {"en": "Page Overview", "ar": "نظرة عامة على الصفحة"},
    "Where To Find This Page": {"en": "Where To Find This Page", "ar": "مكان وجود هذه الصفحة"},
    "Who Can Access": {"en": "Who Can Access", "ar": "من يمكنه الوصول"},
    "Page Layout": {"en": "Page Layout", "ar": "تخطيط الصفحة"},
    "How To Use This Page": {"en": "How To Use This Page", "ar": "كيفية استخدام هذه الصفحة"},
    "Form Fields & Validations": {"en": "Form Fields & Validations", "ar": "حقول النموذج وقواعد التحقق"},
    "Tips & Shortcuts": {"en": "Tips & Shortcuts", "ar": "نصائح واختصارات"},
    "Browser Walkthrough Evidence": {"en": "Browser Walkthrough Evidence", "ar": "أدلة جولة المتصفح"},
    "Screenshots And Assets": {"en": "Screenshots And Assets", "ar": "لقطات الشاشة والمرفقات"},
    "Limitations & Known Issues": {"en": "Limitations & Known Issues", "ar": "القيود والمشكلات المعروفة"},
    "Gaps & Red Flags": {"en": "Gaps & Red Flags", "ar": "الثغرات والتنبيهات"},
    "FAQ": {"en": "FAQ", "ar": "الأسئلة الشائعة"},
    "Attachments & References": {"en": "Attachments & References", "ar": "المرفقات والمراجع"},
    "Approval": {"en": "Approval", "ar": "الاعتماد"},
}


RED_FLAGS_SECTION = "Gaps & Red Flags"
SCREENSHOTS_SECTION = "Screenshots And Assets"
ATTACHMENTS_SECTION = "Attachments & References"


# Localized placeholder bodies for a fresh guide.
_INTRO = {
    "en": "_Page-level user guide. This document describes a single page/screen within the system._",
    "ar": "_دليل استخدام على مستوى الصفحة. يصف هذا المستند صفحة/شاشة واحدة داخل النظام._",
}

_PLACEHOLDERS: dict[str, dict[str, str]] = {
    "Document Status": {
        "en": "- **Status:** Draft\n- **Version:** v1.0",
        "ar": "- **الحالة:** مسودة\n- **الإصدار:** v1.0",
    },
    "Version History": {
        "en": "- v1.0 — Draft created",
        "ar": "- v1.0 — تم إنشاء المسودة",
    },
    "Page Overview": {
        "en": "_What this page is and what it lets the user do. One short paragraph._",
        "ar": "_ما هذه الصفحة وما الذي تتيح للمستخدم القيام به. فقرة قصيرة واحدة._",
    },
    "Where To Find This Page": {
        "en": "_Navigation path from the app entry point (e.g. Sidebar → Projects → Boards)._",
        "ar": "_مسار التنقل من نقطة دخول التطبيق (مثال: الشريط الجانبي ← المشاريع ← اللوحات)._",
    },
    "Who Can Access": {
        "en": "_Roles and permissions required to view/use this page._",
        "ar": "_الأدوار والصلاحيات المطلوبة لعرض/استخدام هذه الصفحة._",
    },
    "Page Layout": {
        "en": "_The main visual regions of the page (header, list, form, side panel, footer)._",
        "ar": "_المناطق المرئية الرئيسية في الصفحة (الرأس، القائمة، النموذج، اللوحة الجانبية، التذييل)._",
    },
    "How To Use This Page": {
        "en": "_Step-by-step instructions for the most common tasks performed on this page._",
        "ar": "_تعليمات خطوة بخطوة لأكثر المهام شيوعًا التي تُنفَّذ على هذه الصفحة._",
    },
    "Form Fields & Validations": {
        "en": "_For pages with inputs: each field's label, type, required?, validation rule, default._",
        "ar": "_للصفحات التي تحتوي على مدخلات: لكل حقل تسميته ونوعه وهل هو مطلوب وقاعدة التحقق والقيمة الافتراضية._",
    },
    "Tips & Shortcuts": {
        "en": "_Keyboard shortcuts, less obvious behaviors, power-user tips._",
        "ar": "_اختصارات لوحة المفاتيح والسلوكيات الأقل وضوحًا ونصائح المستخدم المتقدم._",
    },
    "Browser Walkthrough Evidence": {
        "en": "_TBD_",
        "ar": "_قيد الإعداد_",
    },
    "Screenshots And Assets": {
        "en": "_Annotated screenshots of the page with element tables go here._",
        "ar": "_تُوضع هنا لقطات الشاشة الموضّحة للصفحة مع جداول العناصر._",
    },
    "Limitations & Known Issues": {
        "en": "_Things this page can't do today, or known bugs._",
        "ar": "_الأشياء التي لا تستطيع هذه الصفحة القيام بها حاليًا، أو الأخطاء المعروفة._",
    },
    "Gaps & Red Flags": {
        "en": "_None recorded yet._",
        "ar": "_لا يوجد شيء مُسجَّل بعد._",
    },
    "FAQ": {
        "en": "_Common questions about this page._",
        "ar": "_أسئلة شائعة حول هذه الصفحة._",
    },
    "Attachments & References": {
        "en": "_None yet._",
        "ar": "_لا يوجد بعد._",
    },
    "Approval": {
        "en": "- **Reviewer:** Coject R&D Team\n- **State:** pending",
        "ar": "- **المراجِع:** فريق البحث والتطوير في Coject\n- **الحالة:** قيد الانتظار",
    },
}

_NONE_YET = {"en": "_None yet._", "ar": "_لا يوجد بعد._"}

_RED_FLAG_LABELS = {
    "en": {"expected": "Expected", "observed": "Observed", "recommended": "Recommended"},
    "ar": {"expected": "المتوقع", "observed": "المُلاحَظ", "recommended": "التوصية"},
}

_ATTACHMENT_ADDED = {"en": "added", "ar": "أُضيف بتاريخ"}


def _lang(language: str) -> str:
    return "ar" if str(language).lower() in ("ar", "arabic", "العربية") else "en"


def localized_heading(canonical: str, language: str = "en") -> str:
    """The section's heading text in the requested language (falls back to canonical)."""
    return SECTION_LABELS.get(canonical, {}).get(_lang(language), canonical)


def _heading_regex_any(canonical: str) -> re.Pattern[str]:
    """Match `## <heading>` for a section in EITHER language."""
    labels = SECTION_LABELS.get(canonical)
    if labels:
        alts = "|".join(re.escape(v) for v in dict.fromkeys(labels.values()))
    else:
        alts = re.escape(canonical)
    return re.compile(rf"^##\s+(?:{alts})\s*$", re.MULTILINE | re.IGNORECASE)


def resolve_section(name: str) -> str | None:
    """Match a section name (English or Arabic) against the known sections,
    case-insensitively. Returns the canonical English name."""
    target = name.strip().lower()
    for canonical, labels in SECTION_LABELS.items():
        for label in labels.values():
            if label.lower() == target:
                return canonical
    return None


def detect_doc_language(doc: str) -> str:
    """Infer a guide's language from its section headings ("ar" or "en")."""
    ar = en = 0
    for line in doc.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            for labels in SECTION_LABELS.values():
                if heading == labels["ar"]:
                    ar += 1
                    break
                if heading.lower() == labels["en"].lower():
                    en += 1
                    break
    return "ar" if ar > en else "en"


def replace_section(doc: str, section_name: str, new_body: str) -> str:
    """Replace the body of `## {section_name}` until the next `## ` heading or EOF."""
    resolved = resolve_section(section_name)
    if resolved is None:
        raise ValueError(f"Unknown section: {section_name!r}")

    match = _heading_regex_any(resolved).search(doc)
    if match is None:
        raise ValueError(f"Section heading not found in document: {resolved!r}")

    body_start = match.end()
    next_heading = re.search(r"^##\s+\S", doc[body_start:], re.MULTILINE)
    body_end = body_start + next_heading.start() if next_heading else len(doc)

    cleaned = new_body.strip()
    return doc[:body_start] + "\n" + cleaned + "\n\n" + doc[body_end:]


def append_red_flag(doc: str, expected: str, observed: str, recommended: str) -> str:
    """Append a red-flag entry to the Gaps & Red Flags section, in the doc's language."""
    match = _heading_regex_any(RED_FLAGS_SECTION).search(doc)
    if match is None:
        raise ValueError(f"{RED_FLAGS_SECTION} section missing")

    body_start = match.end()
    next_heading = re.search(r"^##\s+\S", doc[body_start:], re.MULTILINE)
    body_end = body_start + next_heading.start() if next_heading else len(doc)
    existing = doc[body_start:body_end].strip()

    labels = _RED_FLAG_LABELS[detect_doc_language(doc)]
    entry = (
        f"- **{labels['expected']}:** {expected.strip()}\n"
        f"  **{labels['observed']}:** {observed.strip()}\n"
        f"  **{labels['recommended']}:** {recommended.strip()}"
    )

    # Treat an empty body or any italic-only placeholder (EN or AR) as "no entries yet".
    is_placeholder = existing == "" or bool(re.fullmatch(r"_[^_\n]+_", existing))
    new_body = entry if is_placeholder else existing + "\n" + entry

    return doc[:body_start] + "\n" + new_body + "\n\n" + doc[body_end:]


def section_names_for_prompt(browser_enabled: bool, language: str = "en") -> Iterable[str]:
    lang = _lang(language)
    for s in SECTIONS:
        if not browser_enabled and s == "Browser Walkthrough Evidence":
            continue
        yield SECTION_LABELS[s][lang]


def append_to_section(doc: str, section_name: str, markdown_to_append: str) -> str:
    """Append Markdown content to the end of a section's existing body."""
    resolved = resolve_section(section_name)
    if resolved is None:
        raise ValueError(f"Unknown section: {section_name!r}")

    match = _heading_regex_any(resolved).search(doc)
    if match is None:
        raise ValueError(f"Section heading not found in document: {resolved!r}")

    body_start = match.end()
    next_heading = re.search(r"^##\s+\S", doc[body_start:], re.MULTILINE)
    body_end = body_start + next_heading.start() if next_heading else len(doc)
    existing = doc[body_start:body_end].strip()

    # An italic-only single-line body (e.g. "_TBD_", "_None recorded yet._",
    # "_قيد الإعداد_") is a placeholder — replace it rather than appending below it.
    is_placeholder = bool(re.fullmatch(r"_[^_\n]+_", existing))

    if existing == "" or is_placeholder:
        new_body = markdown_to_append.strip()
    else:
        new_body = existing + "\n\n" + markdown_to_append.strip()

    return doc[:body_start] + "\n" + new_body + "\n\n" + doc[body_end:]


def ensure_section(doc: str, section_name: str, placeholder: str | None = None) -> str:
    """Guarantee a section exists. Older guides predate some sections, so insert
    the heading (before Approval if present, else at EOF) when missing, using the
    document's detected language for both the heading and the placeholder."""
    resolved = resolve_section(section_name) or section_name
    if _heading_regex_any(resolved).search(doc):
        return doc

    lang = detect_doc_language(doc)
    heading = localized_heading(resolved, lang)
    if placeholder is None:
        placeholder = _NONE_YET[lang]
    block = f"## {heading}\n{placeholder}\n"

    approval = _heading_regex_any("Approval").search(doc)
    if approval is not None:
        idx = approval.start()
        return doc[:idx].rstrip() + "\n\n" + block + "\n" + doc[idx:]
    return doc.rstrip() + "\n\n" + block


def link_attachment(doc: str, filename: str, url: str, note: str = "") -> str:
    """Append a `- [filename](url) — added <date>` line to Attachments & References,
    creating the section on demand for pre-existing guides."""
    doc = ensure_section(doc, ATTACHMENTS_SECTION)
    lang = detect_doc_language(doc)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    label = filename.replace("]", "").strip() or "file"
    entry = f"- [{label}]({url}) — {_ATTACHMENT_ADDED[lang]} {today}"
    if note.strip():
        entry += f" — {note.strip()}"
    return append_to_section(doc, ATTACHMENTS_SECTION, entry)


def guide_template(name: str, language: str = "en") -> str:
    """Build a fresh guide for a page, with all headings and placeholder bodies
    in the requested language. Headings come from SECTION_LABELS so they always
    match what the editor looks for."""
    lang = _lang(language)
    parts = [f"# {name}", "", _INTRO[lang], ""]
    for s in SECTIONS:
        parts.append(f"## {SECTION_LABELS[s][lang]}")
        parts.append(_PLACEHOLDERS[s][lang])
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def set_document_language(doc: str, target_language: str) -> str:
    """Relabel every recognized section heading to the target language, leaving
    bodies untouched (the agent translates those separately)."""
    lang = _lang(target_language)
    out: list[str] = []
    for line in doc.split("\n"):
        if line.startswith("## "):
            canonical = resolve_section(line[3:].strip())
            if canonical:
                out.append(f"## {SECTION_LABELS[canonical][lang]}")
                continue
        out.append(line)
    return "\n".join(out)
