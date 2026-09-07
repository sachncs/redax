"""Algorithm 1 from the RedactionBench paper: combinator structure construction.

A "combinator" is a small piece of punctuation/whitespace that sits between two
labeled entity spans and tells us how to fuse them into larger entities. The
paper defines four kinds:

* Punct: a single yellow separator char between two labeled spans, excluding
  `\\ / @`, brackets/braces/parens/quotes/backticks, and ASCII letters/digits.
* Slash: a `/` between two digit-only spans.
* Bridge: a closing delimiter followed by yellow whitespace.
* Pair: matched delimiters enclosing yellow spans.

The algorithm builds two graphs over the union of red and yellow spans, then
returns connected components: red fusion groups (composed only of red spans)
and contextual components (composed only of yellow spans).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from app.bench.annotation import LabelledSpan, SpanCategory

PUNCT: frozenset[str] = frozenset("\\/@[]{}()<>\"'`")

LETTERS: frozenset[str] = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
DIGITS: frozenset[str] = frozenset("0123456789")

PAIRS: dict[str, str] = {
    "(": ")",
    "[": "]",
    "{": "}",
    "<": ">",
    '"': '"',
    "'": "'",
    "`": "`",
}
OPENERS: frozenset[str] = frozenset(c for c in PAIRS if c not in "\"'`")
CLOSERS: frozenset[str] = frozenset(c for c in PAIRS.values() if c not in "\"'`")
SYMMETRIC: frozenset[str] = frozenset("\"'`")


def is_punct_char(ch: str) -> bool:
    """A single char qualifies as a Punct connector per the paper.

    "excluding `\\ / @`, brackets, braces, parentheses, quotes, backticks,
    and ASCII letters/digits"
    """
    if ch in PUNCT:
        return False
    return ch not in LETTERS and ch not in DIGITS


def is_whitespace(ch: str) -> bool:
    """Return True if ``ch`` is a space or tab character."""
    return ch in (" ", "\t")


def span_text(text: str, span: LabelledSpan) -> str:
    """Return the slice of ``text`` covered by ``span``."""
    return text[span.start : span.end]


def is_digit_only(text: str, span: LabelledSpan) -> bool:
    """Return True if every character in ``span`` is an ASCII digit."""
    return all(c in DIGITS for c in span_text(text, span))


def iter_neighbor_pairs(
    spans: list[LabelledSpan],
) -> Iterable[tuple[LabelledSpan, LabelledSpan, int, int]]:
    """Yield (a, b, a_end, b_start) for each pair of adjacent spans."""
    ordered = sorted(spans, key=lambda s: (s.start, s.end))
    for i in range(len(ordered) - 1):
        a = ordered[i]
        b = ordered[i + 1]
        yield a, b, a.end, b.start


@dataclass(frozen=True)
class PairRange:
    """An inclusive character range `[o, l]` of a matched delimiter pair.

    The opening delimiter sits at `o`, the closing delimiter at `l`. The
    algorithm stores this as inclusive indices into the source text.
    """

    o: int
    end: int


@dataclass(frozen=True)
class SpanGroup:
    """A partition of spans produced by connected-component grouping.

    Members are the spans belonging to this group, sorted by start position.
    `key` is the smallest span id (or any stable identifier) for diagnostics.
    """

    members: tuple[LabelledSpan, ...]

    @property
    def start(self) -> int:
        """Start offset of the first member span."""
        return self.members[0].start

    def __iter__(self) -> Iterator[LabelledSpan]:
        return iter(self.members)

    def __len__(self) -> int:
        return len(self.members)

    def __bool__(self) -> bool:
        return bool(self.members)


@dataclass(frozen=True)
class ConnectorStructure:
    """The output of Algorithm 1.

    `red_fusion_groups` is the partition of red spans produced by `red_graph`.
    `context_components` is the partition of yellow spans produced by
    `yellow_graph`. `pair_ranges` are the inclusive character ranges of
    matched delimiter pairs enclosing yellow spans. `effective_markers` is
    the ordered list of single-character markers (punct chars, slash,
    delimiters) that act as connectors.
    """

    red_fusion_groups: tuple[SpanGroup, ...]
    context_components: tuple[SpanGroup, ...]
    pair_ranges: tuple[PairRange, ...]
    effective_markers: tuple[str, ...]


def red_edges(
    spans: list[LabelledSpan],
    yellow_graph: dict[tuple[int, int, SpanCategory], list[tuple[int, int, SpanCategory]]],
    red_graph: dict[tuple[int, int, SpanCategory], list[tuple[int, int, SpanCategory]]],
    effective_markers: list[str],
    text: str,
) -> None:
    """Apply the Punct rule (edges to both graphs) and Slash/Bridge rules
    (yellow_graph only).

    Bridge detection requires the last character of span `a` to be a closing
    delimiter and the text between `a.end` and `b.start` to start with
    whitespace. Punct and Slash only inspect the text between spans.
    """
    for a, b, a_end, b_start in iter_neighbor_pairs(spans):
        between = text[a_end:b_start]
        if not between:
            continue
        a_text = span_text(text, a)
        ka = (a.start, a.end, a.category)
        kb = (b.start, b.end, b.category)
        if between.startswith(" ") and a_text and a_text[-1] in CLOSERS:
            yellow_graph.setdefault(ka, []).append(kb)
            yellow_graph.setdefault(kb, []).append(ka)
            effective_markers.append(a_text[-1])
            effective_markers.append(between[0])
            continue
        if len(between) == 1:
            ch = between[0]
            if is_punct_char(ch):
                red_graph.setdefault(ka, []).append(kb)
                red_graph.setdefault(kb, []).append(ka)
                yellow_graph.setdefault(ka, []).append(kb)
                yellow_graph.setdefault(kb, []).append(ka)
                effective_markers.append(ch)
                continue
            if ch == "/" and is_digit_only(text, a) and is_digit_only(text, b):
                yellow_graph.setdefault(ka, []).append(kb)
                yellow_graph.setdefault(kb, []).append(ka)
                effective_markers.append(ch)
        elif len(between) == 2:
            d, w = between[0], between[1]
            if d in CLOSERS and is_whitespace(w):
                yellow_graph.setdefault(ka, []).append(kb)
                yellow_graph.setdefault(kb, []).append(ka)
                effective_markers.append(d)
                effective_markers.append(w)


def pair_ranges(
    spans: list[LabelledSpan],
    yellow_spans: list[LabelledSpan],
    text: str,
) -> tuple[list[PairRange], list[str]]:
    """Find matched delimiter pairs enclosing at least one yellow span.

    We scan the text for opening delimiters and match them to closing
    delimiters using a stack. Pairs whose interior contains only yellow
    spans (no red) AND encloses at least one yellow span are recorded.
    """
    accumulated: list[PairRange] = []
    markers: list[str] = []
    if not yellow_spans:
        return accumulated, markers

    def overlaps_yellow(o: int, l_end: int) -> bool:
        """A yellow span overlaps `[o, l_end+1)` (the pair's inclusive range).

        We include yellows whose start sits exactly on `o` (the opening
        delimiter yellow span) and yellows whose end sits at `l_end+1` (the
        closing delimiter yellow span).
        """
        lo = o
        hi = l_end + 1
        return any(s.start < hi and s.end > lo for s in yellow_spans)

    def crosses_red(o: int, l_end: int) -> bool:
        """Return True if any MANDATORY span is fully contained in [o, l_end]."""
        return any(
            s.category is SpanCategory.MANDATORY and s.start >= o and s.end <= l_end + 1
            for s in spans
        )

    stack: list[int] = []
    for i, ch in enumerate(text):
        if ch in SYMMETRIC:
            if stack and text[stack[-1]] == ch:
                opener_pos = stack.pop()
                if overlaps_yellow(opener_pos, i) and not crosses_red(opener_pos, i):
                    accumulated.append(PairRange(o=opener_pos, end=i))
                    markers.append(ch)
                    markers.append(ch)
            else:
                stack.append(i)
        elif ch in OPENERS:
            stack.append(i)
        elif ch in CLOSERS:
            if not stack:
                continue
            opener_pos = stack.pop()
            opener_ch = text[opener_pos]
            expected_close = PAIRS[opener_ch]
            if ch != expected_close:
                continue
            if not overlaps_yellow(opener_pos, i):
                continue
            if crosses_red(opener_pos, i):
                continue
            accumulated.append(PairRange(o=opener_pos, end=i))
            markers.append(opener_ch)
            markers.append(ch)

    return accumulated, markers


def connected_components(
    nodes: list[LabelledSpan],
    graph: dict[tuple[int, int, SpanCategory], list[tuple[int, int, SpanCategory]]],
) -> list[SpanGroup]:
    """Group nodes by connected component of `graph`."""
    if not nodes:
        return []
    seen: set[tuple[int, int, SpanCategory]] = set()
    components: list[SpanGroup] = []
    by_key: dict[tuple[int, int, SpanCategory], LabelledSpan] = {
        (n.start, n.end, n.category): n for n in nodes
    }
    for node in nodes:
        nkey = (node.start, node.end, node.category)
        if nkey in seen:
            continue
        comp: list[LabelledSpan] = []
        stack = [nkey]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp.append(by_key[cur])
            for neighbor_key in graph.get(cur, ()):
                if neighbor_key not in seen and neighbor_key in by_key:
                    stack.append(neighbor_key)
        comp.sort(key=lambda s: (s.start, s.end))
        components.append(SpanGroup(members=tuple(comp)))
    components.sort(key=lambda g: g.start)
    return components


def build_connector_structure(
    text: str,
    red: list[LabelledSpan],
    yellow: list[LabelledSpan],
) -> ConnectorStructure:
    """Run Algorithm 1 from the paper.

    `red` and `yellow` must be disjoint half-open spans partitioning the set
    of labeled entity spans. Adjacency (end == start) is allowed. Returns
    red fusion groups, contextual components, pair ranges, and effective
    markers.
    """
    spans = list(red) + list(yellow)
    yellow_graph: dict[tuple[int, int, SpanCategory], list[tuple[int, int, SpanCategory]]] = {}
    red_graph: dict[tuple[int, int, SpanCategory], list[tuple[int, int, SpanCategory]]] = {}
    effective_markers: list[str] = []

    red_edges(spans, yellow_graph, red_graph, effective_markers, text)
    found_pairs, pair_markers = pair_ranges(spans, yellow, text)
    effective_markers.extend(pair_markers)

    red_groups = connected_components(list(red), red_graph)
    context_components = connected_components(list(yellow), yellow_graph)

    return ConnectorStructure(
        red_fusion_groups=tuple(red_groups),
        context_components=tuple(context_components),
        pair_ranges=tuple(found_pairs),
        effective_markers=tuple(effective_markers),
    )


def is_connector_marker(span: LabelledSpan, structure: ConnectorStructure) -> bool:
    """Return True if `span` is a single-char yellow span that is one of the
    detected connector markers (Punct char, slash, or pair delimiter).

    Used by Algorithm 2 to drop "singleton" contextual entities whose only
    span is a connector marker (these don't represent real entities).
    """
    if span.end - span.start != 1:
        return False
    return bool(structure.effective_markers)
