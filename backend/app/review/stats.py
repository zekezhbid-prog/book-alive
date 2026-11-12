"""Numbers by chapter: length, sentence length, dialogue, the most frequent words.

Computed from the text alone, without a model, so they are instant and free. They are not
remarks: they let the writer see at a glance that one chapter is twice as heavy as the rest
or that another is nothing but dialogue."""

import re
from collections import Counter
from dataclasses import dataclass, field

from app.review.checks import LANG_BE, LANG_EN

WORD = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*")
# A sentence ends with . ! ? … (one or more), maybe followed by closing quotes or brackets,
# and then a space or the end of the paragraph.
SENTENCE_END = re.compile(r"[.!?…]+[»”\"')\]]*(?=\s|$)")
# What follows the mark keeps the sentence going: a small letter («Что? — спросил он»,
# abbreviations like «т. е.»), maybe after a dash.
CONTINUES = re.compile(r"\s*(?:[—–-]\s*)?[^\W\d_](?<=[^\W\d_A-ZА-ЯЁІЎ])")
# A line of dialogue in Russian and Belarusian: the paragraph opens with a dash, and the
# author's words between lines are set off by dashes too: «— Иду, — сказал он. — Жди».
DASH_LINE = re.compile(r"^\s*[—–-]\s*")
DASH_SPLIT = re.compile(r"\s[—–-]\s")
QUOTED_RU = re.compile(r"«[^«»]+»")
QUOTED_EN = re.compile(r"[“\"][^“”\"]+[”\"]")
# Quoted text shorter than this is a title or a word in quotes, not a line someone says.
QUOTE_MIN_WORDS = 4

LONGEST = 3
TOP_WORDS = 12
QUOTE_CHARS = 220
# Words shorter than this are almost always particles, prepositions and pronouns.
MIN_WORD = 3


def _stop(words: str) -> frozenset[str]:
    """Service words, compared with ё read as е."""
    return frozenset(w.replace("ё", "е") for w in words.split())


STOP_RU = _stop(
    """
    и в во не что он она оно они на я с со как а то все всё так его её ее но да ты к у же вы
    за бы по только ей мне было вот от меня еще ещё нет о из ему теперь когда даже ну вдруг
    ли если уже или ни быть был была были было него до вас нибудь опять уж вам ведь там
    потом себя ничего ей может тут где есть надо ней для мы тебя их чем сам чтоб без будто
    чего раз тоже себе под будет ж тогда кто этот этого этой этом эту эти этих этим того
    потому какой совсем ним здесь том один почти мой тем чтобы нее неё сейчас куда зачем
    всех никогда можно при наконец два об другой хоть после над больше тот через эта нас про
    всего них какая много разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть
    том нельзя такой им более всегда конечно всю между это ее своей свои своих свой своего
    своим своё свое своя который которая которое которые которого которой которых которым
    которую которыми очень весь вся всё всем всеми сказал сказала спросил спросила ответил
    ответила тоже также лишь пока ведь вон снова потом теперь чтоб нему ними нею тебе собой
    себе меня мною тобой вами нами наш наша наше наши нашего вашего ваш ваша ваше ваши тех
    тому той тою такая такое такие таких какие какое каких кого чему чем нем нём оно оне сам
    сама сами само самой самого даже ещё лишь уже будто словно точно бывает было стал стала
    стали стало стать буду будешь будем будете будут есть нет надо нужно можно нельзя пусть
    давай ничто никто нигде кое одна одно одни
    """
)
STOP_BE = _stop(
    """
    і й ў у не што ён яна яно яны на я з са як а то ўсё усё так яго яе але ды ты к да ж вы
    за б бы па толькі ёй мне было вось ад мяне яшчэ няма аб з ён яму цяпер калі нават ну
    раптам ці калі ўжо або ні быць быў была былі было яго да вас небудзь зноў ужо вам бо там
    потым сябе нічога можа тут дзе ёсць трэба ёй для мы цябе іх чым сам каб без быццам чаго
    раз таксама сабе пад будзе тады хто гэты гэтага гэтай гэтым гэту гэтыя гэтых таго таму
    які зусім ім тут той адзін амаль мой тым зараз куды навошта ўсіх ніколі можна пры
    нарэшце два другі хоць пасля над больш праз гэта нас пра усяго іх якая шмат тры мая лепш
    крыху нельга такі заўсёды вядома паміж свой свая сваё свае свайго сваёй сваім які якая
    якое якія якога якой якіх вельмі увесь уся ўвесь ўся ўсе усе сказаў сказала спытаў
    спытала адказаў адказала толькі пакуль зноў цяпер яму імі ёю табе сабою наш наша наша
    нашы ваш ваша вашы тых той такая такое такія якія якое каго чаму ім сама самі сама самой
    самога словна стаў стала сталі стала стаць буду будзеш будзем будзеце будуць трэба няхай
    ніхто нідзе
    """
)
STOP_EN = _stop(
    """
    the and to of a in that it is was he she for on are as with his her they i at be this
    have from or one had by but not what all were we when your can said there use an each
    which do how their if will up other about out many then them these so some would make
    like him into time has look two more go see no way could my than been who its now did
    get come made may over down only just me you our us very where after back also any most
    should here off still too even why again much own same such both those few while through
    before under around because being don't didn't i'm it's that's there's can't won't isn't
    wasn't couldn't would've let's yes yeah oh asked replied says say
    """
)
STOP = {LANG_BE: STOP_BE, LANG_EN: STOP_EN}


@dataclass
class Sentence:
    paragraph: int
    quote: str
    words: int


@dataclass
class WordCount:
    word: str
    count: int


@dataclass
class ChapterStats:
    chapter_id: str
    title: str
    chars: int
    words: int
    sentences: int
    paragraphs: int
    # Words per sentence.
    avg_sentence: float
    # Share of the words that are characters speaking, from 0 to 1.
    dialogue: float
    longest: list[Sentence] = field(default_factory=list)
    top_words: list[WordCount] = field(default_factory=list)


@dataclass
class BookStats:
    language: str
    chapters: list[ChapterStats]
    words: int
    chars: int
    avg_sentence: float
    dialogue: float
    top_words: list[WordCount]


def words(text: str) -> list[str]:
    return WORD.findall(text)


def sentences(paragraph: str) -> list[str]:
    """The sentences of one paragraph. A mark followed by a small letter does not end one:
    «“Куда?” — спросила она» is a single sentence. An abbreviation before a capital (a
    name after «г.») still breaks a sentence in two; on a chapter it hardly moves the average."""
    out: list[str] = []
    start = 0
    for match in SENTENCE_END.finditer(paragraph):
        if CONTINUES.match(paragraph, match.end()):
            continue
        piece = paragraph[start : match.end()].strip()
        if words(piece):
            out.append(piece)
        start = match.end()
    rest = paragraph[start:].strip()
    if words(rest):
        out.append(rest)
    return out


def dialogue_words(paragraph: str, language: str) -> int:
    """How many words of the paragraph are spoken by characters."""
    if language == LANG_EN:
        return sum(
            len(found)
            for found in (words(m.group()) for m in QUOTED_EN.finditer(paragraph))
            if len(found) >= QUOTE_MIN_WORDS or paragraph.lstrip().startswith(("“", '"'))
        )
    if DASH_LINE.match(paragraph):
        # Lines and the author's words take turns: speech, author, speech…
        parts = DASH_SPLIT.split(DASH_LINE.sub("", paragraph, count=1))
        return sum(len(words(part)) for part in parts[::2])
    return sum(
        len(found)
        for found in (words(m.group()) for m in QUOTED_RU.finditer(paragraph))
        if len(found) >= QUOTE_MIN_WORDS
    )


def _cut(text: str) -> str:
    if len(text) <= QUOTE_CHARS:
        return text
    cut = text.rfind(" ", 0, QUOTE_CHARS)
    return text[: cut if cut > 0 else QUOTE_CHARS] + "…"


def _frequent(counter: Counter[str], limit: int) -> list[WordCount]:
    return [WordCount(word, count) for word, count in counter.most_common(limit) if count > 1]


def _counted(text_words: list[str], stop: frozenset[str]) -> Counter[str]:
    return Counter(
        w
        for w in (word.lower().replace("ё", "е") for word in text_words)
        if len(w) >= MIN_WORD and w not in stop
    )


def chapter_stats(
    chapter_id: str, title: str, text: str, language: str
) -> tuple[ChapterStats, Counter[str]]:
    stop = STOP.get(language, STOP_RU)
    found: list[Sentence] = []
    all_words: list[str] = []
    spoken = 0
    paragraphs = text.split("\n\n") if text.strip() else []
    for index, paragraph in enumerate(paragraphs):
        for sentence in sentences(paragraph):
            found.append(Sentence(index, sentence, len(words(sentence))))
        all_words.extend(words(paragraph))
        spoken += dialogue_words(paragraph, language)
    counter = _counted(all_words, stop)
    total = len(all_words)
    longest = sorted(found, key=lambda s: -s.words)[:LONGEST]
    stats = ChapterStats(
        chapter_id=chapter_id,
        title=title,
        chars=len(text),
        words=total,
        sentences=len(found),
        paragraphs=sum(1 for p in paragraphs if p.strip()),
        avg_sentence=round(total / len(found), 1) if found else 0.0,
        dialogue=round(min(spoken / total, 1.0), 3) if total else 0.0,
        longest=[Sentence(s.paragraph, _cut(s.quote), s.words) for s in longest],
        top_words=_frequent(counter, TOP_WORDS),
    )
    return stats, counter


def book_stats(chapters: list[tuple[str, str, str]], language: str) -> BookStats:
    """`chapters` are (id, title, text) in book order."""
    out: list[ChapterStats] = []
    book: Counter[str] = Counter()
    spoken = 0.0
    sentence_count = 0
    for chapter_id, title, text in chapters:
        stats, counter = chapter_stats(chapter_id, title, text, language)
        out.append(stats)
        book.update(counter)
        spoken += stats.dialogue * stats.words
        sentence_count += stats.sentences
    total = sum(c.words for c in out)
    return BookStats(
        language=language,
        chapters=out,
        words=total,
        chars=sum(c.chars for c in out),
        avg_sentence=round(total / sentence_count, 1) if sentence_count else 0.0,
        dialogue=round(spoken / total, 3) if total else 0.0,
        top_words=_frequent(book, TOP_WORDS * 2),
    )
