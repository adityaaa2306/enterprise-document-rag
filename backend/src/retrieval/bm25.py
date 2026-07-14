"""
Minimal BM25 index per document (Phase 2.B).

No external dependency — Okapi BM25 over tokenized chunk texts.
Persisted under VECTOR_DB_PATH/bm25/{document_id}.json

Process-level memory cache: load_index reads disk at most once per document_id
per process (unless invalidated).
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from src.core.config import settings

log = logging.getLogger(__name__)
_lock = threading.RLock()
_MEMORY: Dict[str, "BM25Index"] = {}

_TOKEN = re.compile(r"[a-zA-Z0-9_]{2,}")


def tokenize(text: str) -> List[str]:
    return _TOKEN.findall((text or "").lower())


def _bm25_dir() -> str:
    path = os.path.join(settings.VECTOR_DB_PATH, "bm25")
    os.makedirs(path, exist_ok=True)
    return path


def _path(document_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", document_id)
    return os.path.join(_bm25_dir(), f"{safe}.json")


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_ids: List[str] = []
        self.doc_tokens: List[List[str]] = []
        self.doc_len: List[int] = []
        self.df: Dict[str, int] = {}
        self.avgdl: float = 0.0
        self.N: int = 0
        # term -> list of (doc_index, tf) for O(df) scoring instead of O(N)
        self.postings: Dict[str, List[Tuple[int, int]]] = {}

    def _rebuild_postings(self) -> None:
        postings: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
        for i, toks in enumerate(self.doc_tokens):
            tf_map: Dict[str, int] = {}
            for t in toks:
                tf_map[t] = tf_map.get(t, 0) + 1
            for t, tf in tf_map.items():
                postings[t].append((i, tf))
        self.postings = dict(postings)

    def build(self, docs: List[Tuple[str, str]]) -> None:
        """docs: list of (chunk_id, text)."""
        self.doc_ids = []
        self.doc_tokens = []
        self.doc_len = []
        self.df = {}
        for cid, text in docs:
            toks = tokenize(text)
            self.doc_ids.append(cid)
            self.doc_tokens.append(toks)
            self.doc_len.append(len(toks))
            seen = set(toks)
            for t in seen:
                self.df[t] = self.df.get(t, 0) + 1
        self.N = len(self.doc_ids)
        self.avgdl = (sum(self.doc_len) / self.N) if self.N else 0.0
        self._rebuild_postings()

    def search(self, query: str, k: int = 20) -> List[Tuple[str, float]]:
        if self.N == 0:
            return []
        q_terms = tokenize(query)
        if not q_terms:
            return []
        if not self.postings and self.doc_tokens:
            self._rebuild_postings()

        scores = [0.0] * self.N
        for term in q_terms:
            df = self.df.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1 + (self.N - df + 0.5) / (df + 0.5))
            for i, tf in self.postings.get(term, ()):
                dl = self.doc_len[i] or 1
                denom = tf + self.k1 * (1 - self.b + self.b * dl / max(self.avgdl, 1e-9))
                scores[i] += idf * (tf * (self.k1 + 1)) / denom
        ranked = sorted(
            [(self.doc_ids[i], scores[i]) for i in range(self.N) if scores[i] > 0],
            key=lambda x: x[1],
            reverse=True,
        )
        return ranked[:k]

    def to_dict(self) -> dict:
        return {
            "k1": self.k1,
            "b": self.b,
            "doc_ids": self.doc_ids,
            "doc_tokens": self.doc_tokens,
            "doc_len": self.doc_len,
            "df": self.df,
            "avgdl": self.avgdl,
            "N": self.N,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BM25Index":
        idx = cls(k1=data.get("k1", 1.5), b=data.get("b", 0.75))
        idx.doc_ids = list(data.get("doc_ids") or [])
        idx.doc_tokens = list(data.get("doc_tokens") or [])
        idx.doc_len = list(data.get("doc_len") or [])
        idx.df = dict(data.get("df") or {})
        idx.avgdl = float(data.get("avgdl") or 0.0)
        idx.N = int(data.get("N") or len(idx.doc_ids))
        idx._rebuild_postings()
        return idx


def invalidate_memory(document_id: Optional[str] = None) -> None:
    with _lock:
        if document_id is None:
            _MEMORY.clear()
        else:
            _MEMORY.pop(document_id, None)


def save_index(document_id: str, index: BM25Index) -> None:
    path = _path(document_id)
    with _lock:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(index.to_dict(), f)
        os.replace(tmp, path)
        _MEMORY[document_id] = index
    log.info(f"BM25 index saved for {document_id} ({index.N} docs)")


def load_index(document_id: str) -> BM25Index | None:
    with _lock:
        cached = _MEMORY.get(document_id)
        if cached is not None:
            return cached

    path = _path(document_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        idx = BM25Index.from_dict(data)
        with _lock:
            _MEMORY[document_id] = idx
        return idx
    except Exception as e:
        log.warning(f"BM25 load failed for {document_id}: {e}")
        return None


def build_and_save(document_id: str, docs: List[Tuple[str, str]]) -> BM25Index:
    idx = BM25Index()
    idx.build(docs)
    save_index(document_id, idx)
    return idx


def delete_index(document_id: str) -> None:
    path = _path(document_id)
    invalidate_memory(document_id)
    if os.path.exists(path):
        os.remove(path)
