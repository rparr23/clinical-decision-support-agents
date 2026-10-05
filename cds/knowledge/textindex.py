"""A small TF-IDF cosine index. Stands in for a vector store in offline mode."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

STOP = set("""a an and are as at be by for from has have how i in is it its of on or that the this to was were what
when which who will with without within do does can should my me we our you your patient patients""".split())
SYNONYMS = {
    "xray": "radiography", "x-ray": "radiography", "cxr": "radiography", "radiograph": "radiography",
    "radiographs": "radiography", "film": "radiography", "preop": "preoperative", "pre-op": "preoperative",
    "presurgical": "preoperative", "surgery": "surgical", "admit": "admission", "admitted": "admission",
    "cpap": "cpap", "o2": "oxygen", "neb": "nebulizer", "nebuliser": "nebulizer", "nebulizers": "nebulizer",
    "inhalers": "inhaler", "masks": "mask", "authorisation": "authorization", "auth": "authorization",
    "pa": "authorization", "price": "fee", "cost": "fee", "costs": "fee", "copd": "copd",
}


def tokenize(text: str) -> list[str]:
    raw = re.findall(r"[a-z0-9][a-z0-9\-]*", (text or "").lower())
    out = []
    for tok in raw:
        tok = SYNONYMS.get(tok, tok)
        if tok in STOP or len(tok) < 2:
            continue
        if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        out.append(tok)
    return out


@dataclass
class Doc:
    id: str
    text: str
    meta: dict[str, Any] = field(default_factory=dict)


class TfidfIndex:
    def __init__(self, docs: list[Doc]):
        self.docs = docs
        self._tf = [Counter(tokenize(d.text)) for d in docs]
        df = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(docs)
        self._idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
        self._vecs = [self._weigh(tf) for tf in self._tf]

    def _weigh(self, tf: Counter) -> dict[str, float]:
        vec = {t: (1 + math.log(c)) * self._idf.get(t, 0.0) for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    def search(self, query: str, k: int = 5) -> list[tuple[Doc, float]]:
        q = self._weigh(Counter(tokenize(query)))
        scored = []
        for doc, vec in zip(self.docs, self._vecs):
            s = sum(w * vec.get(t, 0.0) for t, w in q.items())
            if s > 0:
                scored.append((doc, s))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]
