"""Turn an uploaded book file into a flat list of paragraphs.

No AI here: import must be instant and free. Every extractor returns paragraphs
in reading order and marks the ones the file itself declares as headings.
"""

import io
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePath
from urllib.parse import unquote

from lxml import etree, html


class UnsupportedBook(ValueError):
    pass


# An uploaded book is untrusted input. XML inside it must not pull in local files or
# URLs through entities (XXE), and an archive must not unpack into gigabytes.
MAX_UNPACKED_BYTES = 300 * 1024 * 1024


def _xml(data: bytes, *, recover: bool = False):
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False, recover=recover
    )
    return etree.fromstring(data, parser)


@dataclass
class Paragraph:
    text: str
    heading: bool = False


@dataclass
class ExtractedBook:
    paragraphs: list[Paragraph]
    title: str = ""
    author: str = ""
    kind: str = "txt"
    warnings: list[str] = field(default_factory=list)


def extract(data: bytes, filename: str) -> ExtractedBook:
    try:
        return _extract(data, filename)
    except UnsupportedBook:
        raise
    except Exception as exc:
        raise UnsupportedBook(f"The file is damaged or not what its name says: {exc}") from exc


def _extract(data: bytes, filename: str) -> ExtractedBook:
    ext = PurePath(filename).suffix.lower()
    if ext == ".pdf" or data[:5] == b"%PDF-":
        return _pdf(data)
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_UNPACKED_BYTES:
                raise UnsupportedBook("The archive unpacks to an unreasonable size")
            names = set(archive.namelist())
            if "word/document.xml" in names:
                return _docx(archive)
            if "META-INF/container.xml" in names:
                return _epub(archive)
        raise UnsupportedBook("Unknown archive format")
    text = decode_text(data)
    if ext == ".fb2" or re.match(r"\s*<\?xml[\s\S]{0,300}<FictionBook", text):
        return _fb2(data)
    if ext in {".txt", ".md", ""}:
        return ExtractedBook(paragraphs=_plain_paragraphs(text))
    raise UnsupportedBook(f"Unsupported file type: {ext}")


def decode_text(data: bytes) -> str:
    for bom, encoding in (
        (b"\xef\xbb\xbf", "utf-8"),
        (b"\xff\xfe", "utf-16"),
        (b"\xfe\xff", "utf-16"),
    ):
        if data.startswith(bom):
            return data.decode(encoding, errors="replace").lstrip("﻿")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1251", errors="replace")


def _clean(text: str) -> str:
    return re.sub(r"[ \t ]+", " ", text).strip()


def _plain_paragraphs(text: str) -> list[Paragraph]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
    lines = [ln for ln in text.split("\n") if ln.strip()]
    # Files with one paragraph per line and no blank lines between them.
    if len(lines) > 3 * len(blocks):
        blocks = lines
    return [Paragraph(_clean(b.replace("\n", " "))) for b in blocks]


# ---------- DOCX ----------

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_HEADING_STYLE = re.compile(r"^(heading|заголовок|title)\s*[1-3]?$", re.IGNORECASE)


def _docx(archive: zipfile.ZipFile) -> ExtractedBook:
    root = _xml(archive.read("word/document.xml"))
    paragraphs = []
    for p in root.iter(f"{_W}p"):
        parts = []
        for node in p.iter(f"{_W}t", f"{_W}tab", f"{_W}br"):
            parts.append(node.text or "" if node.tag == f"{_W}t" else " ")
        text = _clean("".join(parts))
        if not text:
            continue
        style = p.find(f"{_W}pPr/{_W}pStyle")
        style_name = style.get(f"{_W}val", "") if style is not None else ""
        paragraphs.append(Paragraph(text, bool(_HEADING_STYLE.match(style_name))))
    return ExtractedBook(paragraphs=paragraphs, kind="docx")


# ---------- HTML-based formats ----------

_BLOCKS = {"p", "div", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "title", "pre"}
_HEADINGS = {"h1", "h2", "h3"}


def _html_paragraphs(markup: bytes) -> list[Paragraph]:
    # Without a declared encoding lxml assumes Latin-1 and garbles Cyrillic; books are UTF-8.
    declared = re.search(rb"(?:encoding|charset)=[\"']?([\w-]+)", markup[:1000])
    encoding = declared.group(1).decode("ascii") if declared else "utf-8"
    try:
        root = html.fromstring(markup, parser=html.HTMLParser(encoding=encoding))
    except (etree.ParserError, ValueError, LookupError):
        return []
    body = root.find(".//body")
    scope = body if body is not None else root
    out: list[Paragraph] = []
    for el in scope.iter():
        if not isinstance(el.tag, str) or el.tag not in _BLOCKS:
            continue
        # Only leaf blocks: a <div> wrapping <p> elements would duplicate their text.
        if any(isinstance(c.tag, str) and c.tag in _BLOCKS for c in el.iterdescendants()):
            continue
        text = _clean(el.text_content().replace("\n", " "))
        if text:
            out.append(Paragraph(text, el.tag in _HEADINGS))
    return out


def _epub(archive: zipfile.ZipFile) -> ExtractedBook:
    container = _xml(archive.read("META-INF/container.xml"))
    rootfile = container.find(".//{*}rootfile")
    if rootfile is None:
        raise UnsupportedBook("EPUB: package file not found")
    opf_path = rootfile.get("full-path", "")
    opf = _xml(archive.read(opf_path))
    base = posixpath.dirname(opf_path)
    manifest = {item.get("id"): item.get("href") for item in opf.iterfind(".//{*}manifest/{*}item")}
    names = set(archive.namelist())
    paragraphs: list[Paragraph] = []
    for ref in opf.iterfind(".//{*}spine/{*}itemref"):
        href = manifest.get(ref.get("idref"))
        if not href:
            continue
        path = posixpath.normpath(posixpath.join(base, unquote(href.split("#")[0])))
        if path in names:
            paragraphs.extend(_html_paragraphs(archive.read(path)))
    return ExtractedBook(
        paragraphs=paragraphs,
        title=_clean(opf.findtext(".//{*}metadata/{*}title") or ""),
        author=_clean(opf.findtext(".//{*}metadata/{*}creator") or ""),
        kind="epub",
    )


# ---------- FB2 ----------


def _fb2(data: bytes) -> ExtractedBook:
    root = _xml(data, recover=True)
    paragraphs: list[Paragraph] = []
    body = root.find("{*}body")
    if body is not None:
        for el in body.iter("{*}p", "{*}v", "{*}subtitle"):
            text = _clean("".join(el.itertext()))
            if not text:
                continue
            parent = el.getparent()
            in_title = parent is not None and etree.QName(parent).localname == "title"
            # A multi-line <title> ("Глава 1" / "Возвращение") is one heading.
            if in_title and paragraphs and paragraphs[-1].heading and el.getprevious() is not None:
                paragraphs[-1].text += ". " + text
            else:
                paragraphs.append(Paragraph(text, in_title))
    first = root.findtext(".//{*}title-info/{*}author/{*}first-name") or ""
    last = root.findtext(".//{*}title-info/{*}author/{*}last-name") or ""
    return ExtractedBook(
        paragraphs=paragraphs,
        title=_clean(root.findtext(".//{*}title-info/{*}book-title") or ""),
        author=_clean(f"{first} {last}"),
        kind="fb2",
    )


# ---------- PDF ----------


def _pdf(data: bytes) -> ExtractedBook:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    lines: list[str] = []
    for page in reader.pages:
        page_lines = [ln.rstrip() for ln in (page.extract_text() or "").split("\n")]
        # Bare page numbers at the top or bottom of a page.
        while page_lines and re.fullmatch(r"\s*[-–—]?\s*\d{1,4}\s*[-–—]?\s*", page_lines[-1]):
            page_lines.pop()
        while page_lines and re.fullmatch(r"\s*[-–—]?\s*\d{1,4}\s*[-–—]?\s*", page_lines[0]):
            page_lines.pop(0)
        lines.extend(page_lines)
    if sum(len(ln) for ln in lines) < 200 * min(len(reader.pages), 5):
        raise UnsupportedBook("This PDF has almost no text layer (it looks like a scan)")

    widths = sorted(len(ln) for ln in lines if ln.strip())
    full_width = widths[int(len(widths) * 0.9)] if widths else 0
    paragraphs: list[Paragraph] = []
    current = ""
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(Paragraph(_clean(current)))
                current = ""
            continue
        if current.endswith("-") and stripped[:1].islower():
            current = current[:-1] + stripped
        else:
            current = f"{current} {stripped}" if current else stripped
        # A line that stops well short of the right margin ends its paragraph.
        if len(line.rstrip()) < full_width * 0.75 and re.search(r"[.!?…»\"”:]$", stripped):
            paragraphs.append(Paragraph(_clean(current)))
            current = ""
    if current:
        paragraphs.append(Paragraph(_clean(current)))
    meta = reader.metadata
    return ExtractedBook(
        paragraphs=paragraphs,
        title=_clean((meta.title if meta else "") or ""),
        author=_clean((meta.author if meta else "") or ""),
        kind="pdf",
        warnings=["pdf_layout"],
    )
