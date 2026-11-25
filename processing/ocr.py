"""Read Mistral OCR exports without executing OCR or mutating source files.

Based on the OCR input handling in the user's Ruslex v3 legacy_cli/core.py.
Physical page numbers are 1-based; printed-page offsets are explicit.
"""
from __future__ import annotations

import json
import re
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

from .abbreviations import KNOWN_ABBREVIATIONS, DOTTED_ABBREVIATIONS

WORD = re.compile(r"(?<![\w])([А-Яа-яЁё](?:[А-Яа-яЁё\u0301\u0300]|[-‑](?=[А-Яа-яЁё]))*)(?![\w])")
PAGE_MARKER = re.compile(r"(?im)^\s*<!--\s*page\s*:\s*(\d+)\s*-->\s*$")
NUMBERED_ACRONYM = re.compile(
    r"(?<![\\w])([А-ЯЁ]{2,9}-[0-9]{1,5})(?![\\w])"
)
DOTTED_MATCH = re.compile(
    r"(?<![А-Яа-яЁё])(?:т\.\s*д\.|т\.\s*е\.|т\.\s*к\.|г\.|ул\.|стр\.|рис\.|им\.)(?![А-Яа-яЁё])",
    re.IGNORECASE,
)
POS_MAP = {"INFN": "VERB", "GRND": "VERB", "ADJS": "ADJF", "PRTS": "PRTF"}


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text).replace("\u0301", "").replace("\u0300", "").lower()


def tokenize(markdown: str) -> list[tuple[str, str]]:
    """Extract Cyrillic forms and nearby text; preserve evidence for AI review."""
    clean = re.sub(r"(?ms)^```.*?^```", " ", markdown)
    clean = re.sub(r"!\[[^]]*\]\([^)]*\)", " ", clean)
    clean = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", clean)
    clean = re.sub(r"https?://\S+|<[^>]+>", " ", clean)
    result = []
    dotted_spans = []
    for match in DOTTED_MATCH.finditer(clean):
        spelling = re.sub(r"\.\s*", ". ", match.group().casefold()).strip()
        if spelling in DOTTED_ABBREVIATIONS:
            context = " ".join(clean[max(0, match.start() - 100):match.end() + 100].split())[:230]
            result.append((spelling, context))
            dotted_spans.append((match.start(), match.end()))
    for match in NUMBERED_ACRONYM.finditer(clean):
        context = " ".join(clean[max(0, match.start()-100):match.end()+100].split())[:230]
        result.append((normalize(match.group(1)), context))
        dotted_spans.append((match.start(), match.end()))
    for match in WORD.finditer(clean):
        if any(start <= match.start() < end for start, end in dotted_spans):
            continue
        context = " ".join(clean[max(0, match.start() - 100):match.end() + 100].split())[:230]
        result.append((normalize(match.group(1)), context))
    return result


def _natural_key(name: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r"(\d+)", name)]


def _page_from_name(name: str) -> int | None:
    stem = Path(name).stem
    match = re.search(r"(?:^|[-_\s])(?:page|p)[-_\s]*(\d+)$", stem, re.I)
    if match:
        return int(match.group(1))
    return int(stem) if stem.isdigit() else None


def _page_from_metadata(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    for key in ("pdf_page", "pdfPage", "page_number", "pageNumber", "number"):
        if type(value.get(key)) is int and value[key] > 0:
            return value[key]
    for key in ("page_index", "pageIndex", "index"):
        if type(value.get(key)) is int and value[key] >= 0:
            return value[key] + 1
    if isinstance(value.get("page"), dict):
        return _page_from_metadata(json.dumps(value["page"]))
    return None


def _markdown_pages(content: str) -> list[tuple[int, str]]:
    markers = list(PAGE_MARKER.finditer(content))
    if not markers:
        return [(1, content)]
    return [
        (int(marker.group(1)), content[marker.end():markers[i + 1].start() if i + 1 < len(markers) else len(content)])
        for i, marker in enumerate(markers)
    ]


def _collect_markdown(files: list[str], read_text, read_metadata) -> list[tuple[int, str]]:
    files = sorted(files, key=_natural_key)
    if not files:
        raise ValueError("OCR export contains no Markdown files")
    # Ignore the combined book file when per-page folders are available.
    if any("/" in name for name in files):
        files = [name for name in files if "/" in name]
    files = [name for name in files if Path(name).stem.casefold() not in {"header", "footer"}]
    primary = []
    for name in files:
        folder = name.rpartition("/")[0]
        if Path(name).stem.casefold() == "markdown" and folder:
            if _page_from_name(folder.split("/")[-1]) is not None or read_metadata(folder + "/metadata.json"):
                primary.append(name)
    files = [name for name in files if not any(
        name != main and name.startswith(main.rpartition("/")[0] + "/") for main in primary
    )]
    candidates = []
    for name in files:
        folder = name.rpartition("/")[0]
        number = _page_from_metadata(read_metadata(folder + "/metadata.json"))
        if number is None:
            number = _page_from_name(folder.split("/")[-1]) if folder else None
        if number is None:
            number = _page_from_name(name)
        candidates.append((name, number))
    zero_based_folders = any(number == 0 for _, number in candidates)
    pages = []
    seen = set()
    for ordinal, (name, number) in enumerate(candidates, start=1):
        physical = ordinal if number is None else number + int(zero_based_folders)
        if physical < 1 or physical in seen:
            raise ValueError(f"Ambiguous OCR page numbering for {name!r}: {physical}")
        seen.add(physical)
        pages.append((physical, read_text(name)))
    return sorted(pages)


def input_pages(path: Path) -> list[tuple[int, str]]:
    """Load Mistral JSON, per-page Markdown, ZIP, or page-marked plain text."""
    path = Path(path)
    if path.is_dir():
        names = [p.relative_to(path).as_posix() for p in path.rglob("*")
                 if p.is_file() and p.suffix.lower() in {".md", ".markdown"}]
        def read(name):
            return (path / name).read_text(encoding="utf-8-sig")
        def metadata(name):
            target = path / name
            return target.read_text(encoding="utf-8-sig") if target.is_file() else None
        return _collect_markdown(names, read, metadata)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".json":
        root = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(root, dict) and isinstance(root.get("ocr_response"), dict):
            root = root["ocr_response"]
        pages = root.get("pages") if isinstance(root, dict) else None
        if not isinstance(pages, list):
            raise ValueError("Mistral JSON needs a pages array")
        result = []
        for ordinal, page in enumerate(pages):
            if not isinstance(page, dict):
                raise ValueError("Invalid Mistral page object")
            index, markdown = page.get("index", ordinal), page.get("markdown")
            if type(index) is not int or index < 0 or not isinstance(markdown, str):
                raise ValueError("Mistral page requires a zero-based index and Markdown")
            result.append((index + 1, markdown))
        if len({number for number, _ in result}) != len(result):
            raise ValueError("Duplicate OCR page indexes")
        return sorted(result)
    if path.suffix.lower() in {".md", ".txt"}:
        return _markdown_pages(path.read_text(encoding="utf-8-sig"))
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            files = [name for name in archive.namelist()
                     if name.lower().endswith((".md", ".markdown"))
                     and not name.startswith("__MACOSX/")]
            names = files[:]
            prefix = ""
            # Remove non-page wrapping folders, never extract the ZIP to disk.
            while names and all("/" in name for name in names):
                head = names[0].split("/", 1)[0]
                if _page_from_name(head) is not None or any(
                    name.split("/", 1)[0] != head for name in names
                ):
                    break
                prefix += head + "/"
                names = [name.split("/", 1)[1] for name in names]
            known = set(archive.namelist())
            def read(name):
                return archive.read(prefix + name).decode("utf-8-sig")
            def metadata(name):
                return read(name) if prefix + name in known else None
            return _collect_markdown(names, read, metadata)
    raise ValueError("Use Mistral JSON, Markdown, a per-page folder, or a ZIP export")


def inspect(path: Path) -> dict:
    pages = input_pages(path)
    return {
        "source": str(path), "pages": len(pages),
        "first_page": pages[0][0] if pages else None,
        "last_page": pages[-1][0] if pages else None,
        "sample": [{"page": num, "preview": " ".join(md.split())[:160]}
                   for num, md in pages[:3]],
    }


def parse_forms(surface: str, analyzer, *, uppercase_hint: bool = False) -> list[dict]:
    """Keep alternate analyses for AI disambiguation, not a single guess."""
    seen = set()
    result = []
    # Known lexical abbreviations are not always parseable by pymorphy.
    # Offer a classification option to the LLM, never infer from uppercase
    # textbook headings or unfamiliar OCR tokens alone.
    if surface in DOTTED_ABBREVIATIONS:
        return [{"lemma": surface, "pos": "OTHER", "known": True,
                 "entry_type": "abbreviation",
                 "abbreviation_evidence": "known_written_abbreviation"}]
    if surface in KNOWN_ABBREVIATIONS or uppercase_hint or (
        NUMBERED_ACRONYM.fullmatch(surface.upper()) is not None
    ):
        result.append({"lemma": surface, "pos": "NOUN",
                       "known": surface in KNOWN_ABBREVIATIONS,
                       "entry_type": "abbreviation",
                       "abbreviation_evidence": "recognized_lexical_abbreviation"
                           if surface in KNOWN_ABBREVIATIONS else "uppercase_context_only"})
        seen.add((surface, "NOUN", "abbreviation"))
    for analysis in analyzer.parse(surface):
        lemma = normalize(analysis.normal_form)
        raw_pos = str(analysis.tag.POS or "UNKNOWN")
        pos = POS_MAP.get(raw_pos, raw_pos)
        category = "abbreviation" if lemma in KNOWN_ABBREVIATIONS else "word"
        if (lemma, pos, category) in seen:
            continue
        seen.add((lemma, pos, category))
        result.append({"lemma": lemma, "pos": pos,
                       "known": bool(getattr(analysis, "is_known", False)),
                       "entry_type": category})
        if len(result) >= 7:
            break
    return result


def import_book(db, *, title: str, edition: str, source: Path,
                first: int, last: int, offset: int = 0, page_shift: int = 0,
                analyzer=None) -> dict:
    """Import new pages into a WORKSPACE DB; existing pages remain untouched."""
    if first < 1 or last < first:
        raise ValueError("Invalid first/last PDF pages")
    if analyzer is None:
        import pymorphy3
        analyzer = pymorphy3.MorphAnalyzer(lang="ru")
    pages = [(n + page_shift, md) for n, md in input_pages(source)]
    selected = [(num, md) for num, md in pages if first <= num <= last]
    if not selected or len({num for num, _ in selected}) != len(selected):
        raise ValueError("No matching pages, or duplicate physical page numbers")
    # Existing numbered pages are immutable. Changing source OCR requires a new edition.
    with db:
        db.execute("INSERT OR IGNORE INTO books(title, edition) VALUES (?, ?)", (title, edition))
    book_id = db.execute("SELECT id FROM books WHERE title=? AND edition=?",
                         (title, edition)).fetchone()[0]
    counts = {"pages_added": 0, "pages_skipped": 0, "new_forms_for_AI": 0,
              "book_id": book_id}
    parsed = {}
    for physical, markdown in selected:
        existing = db.execute("SELECT markdown FROM pages WHERE book_id=? AND pdf_page=?",
                              (book_id, physical)).fetchone()
        if existing:
            if existing[0] != markdown:
                raise ValueError(f"Page {physical} already exists with different OCR; use a new edition")
            counts["pages_skipped"] += 1
            continue
        tokens = tokenize(markdown)
        frequencies = Counter(form for form, _ in tokens)
        contexts = {}
        abbreviation_hints = set()
        for form, context in tokens:
            contexts.setdefault(form, context)
            # Uppercase is a *candidate hint* only; the LLM still checks
            # surrounding text and may decline admission.
            if 2 <= len(form) <= 9 and re.search(
                r"(?<![А-Яа-яЁё])" + re.escape(form.upper()) + r"(?![А-Яа-яЁё])",
                context,
            ):
                abbreviation_hints.add(form)
        with db:
            page_id = db.execute(
                "INSERT INTO pages(book_id,pdf_page,printed_page,markdown,source) VALUES(?,?,?,?,?)",
                (book_id, physical, physical - offset, markdown, str(source))
            ).lastrowid
            for form, count in frequencies.items():
                db.execute("INSERT INTO surface_pages(page_id,surface,count,context) VALUES(?,?,?,?)",
                           (page_id, form, count, contexts[form]))
                if form not in parsed:
                    parsed[form] = parse_forms(
                        form, analyzer, uppercase_hint=form in abbreviation_hints
                    )
                result = db.execute(
                    "INSERT OR IGNORE INTO reviews(book_id,surface,analyses_json) VALUES(?,?,?)",
                    (book_id, form, json.dumps(parsed[form], ensure_ascii=False))
                )
                counts["new_forms_for_AI"] += int(result.rowcount > 0)
                review = db.execute("SELECT status,entries_json FROM reviews WHERE book_id=? AND surface=?",
                                    (book_id, form)).fetchone()
                if review and review[0] == "admitted":
                    for entry in json.loads(review[1]):
                        lemma, pos = entry[:2]
                        lexeme = db.execute("SELECT id FROM lexemes WHERE lemma=? AND pos=?",
                                            (lemma, pos)).fetchone()
                        if lexeme:
                            db.execute("INSERT OR IGNORE INTO lexeme_pages(lexeme_id,page_id,surface,context,count) "
                                       "VALUES (?,?,?,?,?)", (lexeme[0], page_id, form, contexts[form], count))
        counts["pages_added"] += 1
    return counts
