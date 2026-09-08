"""Lexical retrieval over scheme prose (BM25), dependency-free.

BM25 is the default so that the baseline runs anywhere and reproduces exactly. It is
also, deliberately, a *fair* baseline rather than a weak one: it indexes the full scheme
text including the verbatim eligibility wording, so the retriever sees every fact the
grounding pipeline's rules were encoded from.

One caveat matters for RQ2 and is worth stating plainly rather than discovering later.
Lexical matching is not language-neutral: a code-mixed query carries fewer English
content words, so BM25 retrieval degrades under code-mixing for reasons that have
nothing to do with reasoning. Attributing the *whole* code-mix gap to reasoning would
therefore be wrong. Run :class:`DenseRetriever` with a multilingual encoder as a second
retrieval condition, and report the lexical and dense retrieval-recall numbers next to
the matching numbers, so a reader can separate the two effects.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from ..kb import SchemeKB

_TOKEN = re.compile(r"[\w஀-௿]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Casefold and split on word characters, keeping Tamil script tokens intact."""
    return _TOKEN.findall(unicodedata.normalize("NFC", text).casefold())


@dataclass
class BM25Retriever:
    """Okapi BM25 over the schemes' ``retrieval_text()``."""

    kb: SchemeKB
    k1: float = 1.5
    b: float = 0.75
    name: str = "bm25"

    doc_ids: list[str] = field(default_factory=list, init=False)
    _tf: list[Counter] = field(default_factory=list, init=False)
    _lengths: list[int] = field(default_factory=list, init=False)
    _df: Counter = field(default_factory=Counter, init=False)
    _avg_len: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        for scheme in sorted(self.kb, key=lambda s: s.id):
            tokens = tokenize(scheme.retrieval_text())
            self.doc_ids.append(scheme.id)
            counts = Counter(tokens)
            self._tf.append(counts)
            self._lengths.append(len(tokens))
            for term in counts:
                self._df[term] += 1
        self._avg_len = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0

    def _idf(self, term: str) -> float:
        n = len(self.doc_ids)
        df = self._df.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def score(self, query: str) -> list[tuple[str, float]]:
        """Score every scheme against ``query``, highest first."""
        terms = tokenize(query)
        scored: list[tuple[str, float]] = []
        for index, scheme_id in enumerate(self.doc_ids):
            tf = self._tf[index]
            length = self._lengths[index] or 1
            total = 0.0
            for term in terms:
                freq = tf.get(term, 0)
                if not freq:
                    continue
                denominator = freq + self.k1 * (1 - self.b + self.b * length / (self._avg_len or 1))
                total += self._idf(term) * freq * (self.k1 + 1) / denominator
            scored.append((scheme_id, total))
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored

    def retrieve(self, query: str, k: int = 8) -> list[str]:
        """Top-``k`` scheme ids. Ties break by id so runs are reproducible."""
        return [scheme_id for scheme_id, _ in self.score(query)[:k]]


@dataclass
class DenseRetriever:
    """Embedding retrieval, for the multilingual-encoder condition.

    Kept behind an injected ``encode`` function so the core package has no heavy
    dependency: pass ``SentenceTransformer(...).encode`` or any callable mapping a list
    of strings to a list of vectors.
    """

    kb: SchemeKB
    encode: Callable[[Sequence[str]], Sequence[Sequence[float]]]
    name: str = "dense"

    doc_ids: list[str] = field(default_factory=list, init=False)
    _vectors: list[Sequence[float]] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        schemes = sorted(self.kb, key=lambda s: s.id)
        self.doc_ids = [s.id for s in schemes]
        self._vectors = list(self.encode([s.retrieval_text() for s in schemes]))

    def retrieve(self, query: str, k: int = 8) -> list[str]:
        query_vector = list(self.encode([query]))[0]
        scored = [
            (scheme_id, _cosine(query_vector, vector))
            for scheme_id, vector in zip(self.doc_ids, self._vectors)
        ]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return [scheme_id for scheme_id, _ in scored[:k]]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class OracleRetriever:
    """Returns every scheme. The ceiling condition for the retrieval-vs-matching gap.

    Running the baseline with this retriever removes retrieval error entirely, so any
    remaining error is reasoning error. It is the cleanest way to show that RQ1's gap is
    not an artefact of a weak retriever, and it costs nothing on a KB this size.
    """

    kb: SchemeKB
    name: str = "oracle_all"

    def retrieve(self, query: str, k: int = 0) -> list[str]:
        return self.kb.ids()


def recall_at_k(retrieved: Iterable[str], gold: Iterable[str]) -> float | None:
    gold_set = set(gold)
    if not gold_set:
        return None
    return len(set(retrieved) & gold_set) / len(gold_set)
