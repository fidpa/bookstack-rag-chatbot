"""Overlapping word-window chunking shared by wiki pages and uploaded documents."""

import re
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

# A unit ends at a sentence mark followed by a capital letter or digit, or at a
# line break. Line breaks matter: list items, table cells and headings carry no
# sentence punctuation, and without them a whole page would become one unit.
_UNIT_BOUNDARY = re.compile(r"(?<=[.!?])[ \t]+(?=[A-ZÄÖÜ0-9\"'(])|\n+")

# (start_pos, end_pos, text) of one sentence or line inside the normalised text
Unit = Tuple[int, int, str]


@dataclass
class TextSpan:
    """One chunk of text with its position in the normalised input."""

    text: str
    start_pos: int
    end_pos: int
    word_count: int


class TextChunker:
    """
    Split text into chunks of at most `chunk_size` words.

    Consecutive chunks share up to `overlap` words, and chunks below `min_size`
    words are merged into their successor where that stays within 130% of
    chunk_size.
    """

    def __init__(self, chunk_size: int, overlap: int, min_size: int):
        if overlap >= chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")
        if chunk_size < min_size:
            raise ValueError(f"chunk_size must be at least {min_size} words")
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.min_size = min_size

    def split(self, text: str) -> List[TextSpan]:
        """Chunks of `text`, in order; [] for empty or near-empty input."""
        if not text or len(text.strip()) < 10:
            return []
        text = normalize(text)
        units = self._split_oversized(split_units(text))
        return self._merge_small(self._pack(units))

    def _split_oversized(self, units: List[Unit]) -> List[Unit]:
        """
        Cut units longer than a whole chunk into overlap-sized word windows.

        A unit that alone exceeds chunk_size (a long line without sentence marks)
        would otherwise become a chunk of arbitrary size. Windows of `overlap` words
        keep the overlap mechanism working across the cut.
        """
        result: List[Unit] = []
        for start, end, unit in units:
            words = list(re.finditer(r"\S+", unit))
            if len(words) <= self.chunk_size:
                result.append((start, end, unit))
                continue
            for i in range(0, len(words), self.overlap):
                window = words[i : i + self.overlap]
                s, e = window[0].start(), window[-1].end()
                result.append((start + s, start + e, unit[s:e]))
        return result

    def _pack(self, units: List[Unit]) -> List[TextSpan]:
        """Pack units into chunks of at most chunk_size words, with overlap."""
        spans: List[TextSpan] = []
        current: List[Unit] = []
        current_words = 0

        for unit in units:
            words = len(unit[2].split())

            if current_words + words > self.chunk_size and current:
                spans.append(_span(current))

                # Carry trailing units into the next chunk, up to `overlap` words
                carried: List[Unit] = []
                carried_words = 0
                for u in reversed(current):
                    u_words = len(u[2].split())
                    if carried_words + u_words > self.overlap:
                        break
                    carried.insert(0, u)
                    carried_words += u_words
                current, current_words = carried, carried_words

            current.append(unit)
            current_words += words

        if current:
            spans.append(_span(current))
        return spans

    def _merge_small(self, spans: List[TextSpan]) -> List[TextSpan]:
        """Merge chunks below min_size into the following chunk where it fits."""
        merged: List[TextSpan] = []
        i = 0
        while i < len(spans):
            span = spans[i]
            if span.word_count < self.min_size and i < len(spans) - 1:
                nxt = spans[i + 1]
                if span.word_count + nxt.word_count <= self.chunk_size * 1.3:
                    merged.append(
                        TextSpan(
                            text=f"{span.text} {nxt.text}",
                            start_pos=span.start_pos,
                            end_pos=nxt.end_pos,
                            word_count=span.word_count + nxt.word_count,
                        )
                    )
                    i += 2
                    continue
            merged.append(span)
            i += 1
        return merged


def normalize(text: str) -> str:
    """Collapse whitespace inside lines while keeping the line structure."""
    text = re.sub(r"&\w+;", " ", text)  # entities that survived unescaping
    lines = [re.sub(r"[ \t\f\v\r]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def split_units(text: str) -> List[Unit]:
    """Split text into sentences and lines, keeping their positions."""
    units: List[Unit] = []
    start = 0
    for match in _UNIT_BOUNDARY.finditer(text):
        _append_unit(units, text, start, match.start())
        start = match.end()
    _append_unit(units, text, start, len(text))
    return units


def _append_unit(units: List[Unit], text: str, start: int, end: int):
    segment = text[start:end]
    stripped = segment.strip()
    if stripped:
        offset = start + segment.index(stripped)
        units.append((offset, offset + len(stripped), stripped))


def _span(units: Sequence[Unit]) -> TextSpan:
    text = " ".join(u[2] for u in units)
    return TextSpan(
        text=text,
        start_pos=units[0][0],
        end_pos=units[-1][1],
        word_count=len(text.split()),
    )


def chunk_statistics(word_counts: List[int], overlap: int, chunk_size: int) -> Dict:
    """Word-count statistics for a list of chunks."""
    if not word_counts:
        return {
            "total_chunks": 0,
            "avg_words_per_chunk": 0,
            "min_words": 0,
            "max_words": 0,
            "total_words": 0,
        }
    return {
        "total_chunks": len(word_counts),
        "avg_words_per_chunk": sum(word_counts) / len(word_counts),
        "min_words": min(word_counts),
        "max_words": max(word_counts),
        "total_words": sum(word_counts),
        "overlap_ratio": overlap / chunk_size,
    }
