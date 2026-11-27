"""Check that no name from a real book (characters, places, aliases, book titles) got into the repo.

Lorebook changes must work for any book: a name from a user's book in code, tests, docs or a
commit message means a fix was tailored to that book. The names come from the local database
(every project except the demo books in `demo/`) and are cached in `data/book-names.txt`,
which is git-ignored, so this script itself never holds a name.

    uv run python scripts/check_book_names.py            # scan, refresh the cache if missing
    uv run python scripts/check_book_names.py --refresh  # re-read the names from the database

Common words that happen to be names and give false alarms go into
`data/book-names-ignore.txt`, one per line. Exit code 1 when something is found.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "data" / "book-names.txt"
IGNORE = REPO / "data" / "book-names-ignore.txt"
DEMO_DIR = REPO / "demo"
SKIP_SUFFIXES = {".lock", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".zip", ".docx", ".pdf"}
SKIP_NAMES = {"uv.lock", "package-lock.json"}
MAX_BYTES = 2_000_000

# Belarusian and Russian spellings of one name differ in a few letters; both sides are folded.
_FOLD = str.maketrans(
    {"і": "и", "І": "И", "ў": "в", "Ў": "В", "ё": "е", "Ё": "Е", "э": "е", "Э": "Е"}
)
_ENDING = re.compile(r"[аяоеыиуюйь]+$")
_LETTER = "а-яёa-zіўэ"
# Case endings: vowels, й/ь and the м/х of plural cases ("-ам", "-ях", "-ами").
_CASE_ENDING = "[аяоеыиуюйьмх]{0,3}"


def fold(text: str) -> str:
    return text.translate(_FOLD)


def names_from_db() -> list[str]:
    from sqlalchemy import text

    from app.db import get_engine

    texts = [p.read_text(encoding="utf-8") for p in DEMO_DIR.glob("*.txt")]
    demo = fold(" ".join(texts))
    # A demo book's first line is its title; projects made from a demo book are skipped.
    demo_titles = {t.strip().splitlines()[0].strip() for t in texts if t.strip()}
    with get_engine().connect() as conn:
        projects = [
            (pid, title)
            for pid, title in conn.execute(text("select id, title from projects")).all()
            if title.strip() not in demo_titles
        ]
        ids = [pid for pid, _ in projects]
        rows = conn.execute(
            text("select name, aliases from entities where project_id = any(:ids)"), {"ids": ids}
        ).all()
    titles = [title for _, title in projects]
    found: set[str] = set()
    for value in [n for n, aliases in rows for n in [n, *(aliases or [])]] + titles:
        # Whole names and the capitalised words inside them ("Aunt X" -> "X").
        for part in [value, *re.findall(rf"[A-ZА-ЯЁІЎЭ][{_LETTER}]+", value)]:
            part = part.strip()
            if len(part) >= 3 and fold(part) not in demo:
                found.add(part)
    return sorted(found)


def load_names(refresh: bool) -> list[str]:
    sys.path.insert(0, str(REPO / "backend"))
    if refresh or not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text("\n".join(names_from_db()) + "\n", encoding="utf-8")
    names = [n for n in CACHE.read_text(encoding="utf-8").splitlines() if n.strip()]
    ignored = set()
    if IGNORE.exists():
        ignored = {fold(n.strip()) for n in IGNORE.read_text(encoding="utf-8").splitlines()}
    return [n for n in names if fold(n) not in ignored]


def pattern_for(name: str) -> re.Pattern:
    """Case-sensitive on the first letter, tolerant to case endings of Slavic names."""
    folded = fold(name)
    if " " in folded:
        return re.compile(rf"(?<![{_LETTER}]){re.escape(folded)}")
    stem = _ENDING.sub("", folded)
    if len(stem) < 4:
        # Short names: the word itself or with a vowel ending only, so a name does not catch
        # every longer word that starts the same way.
        return re.compile(rf"(?<![{_LETTER}]){re.escape(folded)}(?![{_LETTER}])")
    return re.compile(rf"(?<![{_LETTER}]){re.escape(stem)}{_CASE_ENDING}(?![{_LETTER}])")


def latin_patterns(name: str) -> list[re.Pattern]:
    """The name in Latin letters, as it gets into variable and file names ("ref01_<name>.png")."""
    from app.scenes.service import slug

    stem = _ENDING.sub("", fold(name).lower())
    if " " in stem:
        return []
    variants = {slug(stem)}
    # Other ways people spell the same sounds in Latin.
    for a, b in [("yu", "u"), ("ya", "a"), ("kh", "h"), ("ts", "t"), ("dz", "d"), ("y", "i")]:
        variants |= {v.replace(a, b) for v in variants}
    return [
        re.compile(rf"(?<![a-z]){re.escape(v)}[a-z]{{0,4}}(?![a-z])", re.IGNORECASE)
        for v in variants
        if len(v) >= 4
    ]


def matchers(name: str) -> list:
    """Searches for one name: as written, in capitals ("TITLE LINE") and in Latin letters."""
    cased = pattern_for(name)
    capitals = re.compile(cased.pattern, re.IGNORECASE)

    def as_written(line: str) -> str | None:
        m = cased.search(line)
        return m.group(0) if m else None

    def in_capitals(line: str) -> str | None:
        found = [m.group(0) for m in capitals.finditer(line) if m.group(0).isupper()]
        return found[0] if found else None

    latin = latin_patterns(name)

    def in_latin(line: str) -> str | None:
        found = [m.group(0) for p in latin for m in p.finditer(line)]
        return found[0] if found else None

    return [as_written, in_capitals, in_latin]


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=False
    ).stdout


def files_to_scan() -> list[Path]:
    listed = git("ls-files", "--cached", "--others", "--exclude-standard").splitlines()
    out = []
    for rel in listed:
        path = REPO / rel
        if path.name in SKIP_NAMES or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if path.is_file() and path.stat().st_size <= MAX_BYTES:
            out.append(path)
    return out


def scan(names: list[str]) -> list[str]:
    checks = [check for n in names for check in matchers(n)]
    hits = []
    sources: list[tuple[str, str]] = []
    for path in files_to_scan():
        try:
            sources.append((str(path.relative_to(REPO)), path.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):
            continue
    unpushed = git("log", "@{u}..HEAD", "--format=commit %h%n%B")
    if unpushed:
        sources.append(("<unpushed commit messages>", unpushed))
    for label, content in sources:
        for number, line in enumerate(content.splitlines(), 1):
            folded = fold(line)
            words = {w for check in checks if (w := check(folded))}
            if words:
                hits.append(f"{label}:{number}: " + ", ".join(sorted(words)))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="re-read names from the database")
    args = parser.parse_args()
    names = load_names(args.refresh)
    hits = scan(names)
    for hit in hits:
        print(hit)
    print(f"names checked: {len(names)}, found: {len(hits)}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
