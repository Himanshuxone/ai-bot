"""
Local hybrid retriever: BM25 (lexical) + hashed TF-IDF vectors (semantic-ish).

Why local and dependency-free?
------------------------------
Sending document chunks to a third-party embedding API is an additional
transfer of (pseudonymised) personal and confidential financial data to a
processor. A local index avoids that entirely and runs anywhere. The
``Retriever`` interface is small, so a production deployment can swap in a
self-hosted embedding model (e.g. sentence-transformers) or a vector DB with
encryption-at-rest and per-tenant collections.

Financial tuning: numbers and period labels ("fy2024", "q3", "2023") are kept
as tokens, and queries are expanded with common finance synonyms
(revenue ~ sales ~ turnover, net income ~ profit ~ earnings ...).

[RULE: GDPR-ART44]   No document content leaves the host for embedding.
[RULE: GDPR-ART25]   Privacy-by-default architecture choice.
[RULE: OWASP-LLM08]  Index is built per tenant; there is no shared index that
                     could leak chunks across tenants.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[a-z]+[0-9]*|[0-9]+(?:[.,][0-9]+)*")
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the this to was "
    "were what which who will with how much many did does do our their there".split()
)

# Lightweight finance synonym map used for query expansion.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "revenue": ("sales", "turnover", "income"),
    "sales": ("revenue", "turnover"),
    "turnover": ("revenue", "sales"),
    "profit": ("income", "earnings", "surplus"),
    "earnings": ("profit", "income"),
    "loss": ("deficit",),
    "costs": ("expenses", "expenditure", "cogs"),
    "expenses": ("costs", "expenditure", "opex"),
    "cash": ("liquidity",),
    "debt": ("borrowings", "liabilities", "loans"),
    "assets": ("holdings",),
    "equity": ("shareholders", "capital"),
    "margin": ("profitability",),
    "ebitda": ("operating",),
    "capex": ("capital", "expenditure"),
    "dividend": ("dividends", "payout"),
}

_HASH_DIM = 2 ** 18  # feature-hashing space for the sparse vectors


def tokenize(text: str) -> list[str]:
    """Lowercase, split into word/number tokens, drop stopwords."""
    tokens = []
    for tok in _TOKEN_RE.findall(text.lower()):
        tok = tok.replace(",", "")  # "1,200" -> "1200" so formats match
        if tok not in _STOPWORDS:
            tokens.append(tok)
    return tokens


def _features(tokens: list[str]) -> Counter[int]:
    """Hash unigrams and bigrams into a sparse feature vector."""
    grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
    return Counter(int(hashlib.blake2b(g.encode(), digest_size=8).hexdigest(), 16) % _HASH_DIM
                   for g in grams)


@dataclass
class SearchHit:
    """A retrieval result: index into the chunk list and a 0..1 score."""

    position: int
    score: float


class HybridIndex:
    """In-memory BM25 + hashed-TF-IDF cosine index over a list of texts."""

    def __init__(self, texts: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self._k1, self._b = k1, b
        self._docs = [tokenize(t) for t in texts]
        self._tf = [Counter(d) for d in self._docs]
        self._lengths = [len(d) for d in self._docs]
        self._avg_len = (sum(self._lengths) / len(self._lengths)) if self._docs else 0.0
        df: Counter[str] = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(self._docs)
        # BM25 idf with +1 smoothing (never negative).
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        # Pre-compute L2-normalised TF-IDF hashed vectors.
        feat_df: Counter[int] = Counter()
        feats = [_features(d) for d in self._docs]
        for f in feats:
            feat_df.update(f.keys())
        self._feat_idf = {k: math.log((1 + n) / (1 + v)) + 1 for k, v in feat_df.items()}
        self._vectors = [self._weight(f) for f in feats]

    def _weight(self, feats: Counter[int]) -> dict[int, float]:
        """Sublinear TF x IDF, L2-normalised."""
        vec = {k: (1 + math.log(c)) * self._feat_idf.get(k, 1.0) for k, c in feats.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {k: v / norm for k, v in vec.items()}

    @staticmethod
    def expand(tokens: list[str]) -> list[str]:
        """Add finance synonyms to a tokenised query."""
        out = list(tokens)
        for tok in tokens:
            out.extend(_SYNONYMS.get(tok, ()))
        return out

    def search(self, query: str, top_k: int, exclude: set[int] | None = None) -> list[SearchHit]:
        """Return up to ``top_k`` hits ranked by a 60/40 BM25/cosine blend."""
        if not self._docs:
            return []
        exclude = exclude or set()
        q_tokens = tokenize(query)
        expanded = self.expand(q_tokens)
        bm25 = []
        for idx, tf in enumerate(self._tf):
            score = 0.0
            for tok in expanded:
                if tok not in tf:
                    continue
                freq = tf[tok]
                denom = freq + self._k1 * (1 - self._b + self._b * self._lengths[idx]
                                           / (self._avg_len or 1))
                weight = 1.0 if tok in q_tokens else 0.5  # synonyms count half
                score += weight * self._idf[tok] * freq * (self._k1 + 1) / denom
            bm25.append(score)
        max_bm25 = max(bm25) or 1.0
        q_vec = self._weight(_features(q_tokens))
        hits = []
        for idx, vec in enumerate(self._vectors):
            if idx in exclude:
                continue
            cosine = sum(w * vec.get(k, 0.0) for k, w in q_vec.items())
            score = 0.6 * (bm25[idx] / max_bm25) + 0.4 * cosine
            if score > 0:
                hits.append(SearchHit(idx, score))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]
