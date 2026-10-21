"""Role-aware tool recommender: content relevance + item-item collaborative filtering.

score(tool) = 0.65 * relevance(query, tool description)       (TF-IDF cosine)
            + 0.35 * affinity(user, tool)                      (item-item CF on usage counts)

* Tools the caller's role may not use are never returned (RBAC is enforced here, not in the prompt).
* Users with no history fall back to the popularity of tools among their role.
* Usage events are synthetic (``generate_usage_events``): users belong to latent workstreams
  with different tool mixes, which is the structure collaborative filtering is meant to recover.
  ``evaluate_offline`` measures that with leave-one-out hit@3 against a popularity baseline.
"""
from __future__ import annotations

import csv
import logging
import random
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ai_orchestrator.config import CONFIG_DIR, get_settings

log = logging.getLogger(__name__)

ROLE_RANK = {"INGEST_SERVICE": 0, "ANALYST": 1, "ADMIN": 2}
RELEVANCE_WEIGHT, AFFINITY_WEIGHT = 0.65, 0.35

WORKSTREAMS = {
    "reporting": {"POSTGRES_EXPORT": 5, "DASHBOARD_SNAPSHOT": 4, "COST_REPORT": 2, "JIRA_TICKET_GEN": 1},
    "incident": {"LOG_SEARCH": 5, "ONCALL_PAGE": 4, "JIRA_TICKET_GEN": 3, "SECURITY_AUDIT_LOG_FREEZE": 1},
    "finops": {"COST_REPORT": 5, "DASHBOARD_SNAPSHOT": 3, "POSTGRES_EXPORT": 2, "REFUND_DISPATCH": 2},
    "security": {"SECURITY_AUDIT_LOG_FREEZE": 4, "KEY_ROTATION": 4, "ACCESS_REVIEW": 3, "LOG_SEARCH": 3},
    "support": {"REFUND_DISPATCH": 4, "JIRA_TICKET_GEN": 4, "LOG_SEARCH": 2, "POSTGRES_EXPORT": 1},
}


@dataclass
class Recommendation:
    id: str
    description: str
    score: float
    relevance: float
    affinity: float
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def load_catalog() -> list[dict]:
    with open(CONFIG_DIR / "tool_catalog.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["tools"]


def role_allows(role: str, tool: dict) -> bool:
    return ROLE_RANK.get(role, 0) >= ROLE_RANK[tool["min_role"]]


def generate_usage_events(path: Path, n_users: int = 80, seed: int = 11) -> int:
    """Write synthetic tool-usage events (user_id, role, tool_id, ts) to CSV."""
    rng = random.Random(seed)
    catalog = {t["id"]: t for t in load_catalog()}
    now = datetime(2026, 10, 1, tzinfo=UTC)
    rows = []
    for i in range(n_users):
        role = "ADMIN" if i % 4 == 0 else "ANALYST"
        user = f"u{i:03d}"
        streams = rng.sample(sorted(WORKSTREAMS), k=2 if rng.random() < 0.3 else 1)
        weights: dict[str, float] = {}
        for stream in streams:
            for tool, w in WORKSTREAMS[stream].items():
                weights[tool] = weights.get(tool, 0) + w
        allowed = [t for t in weights if role_allows(role, catalog[t])]
        if not allowed:
            continue
        for _ in range(rng.randint(15, 60)):
            tool = rng.choices(allowed, weights=[weights[t] for t in allowed])[0]
            ts = now - timedelta(minutes=rng.randint(0, 90 * 24 * 60))
            rows.append((user, role, tool, ts.isoformat()))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["user_id", "role", "tool_id", "ts"])
        writer.writerows(sorted(rows, key=lambda r: r[3]))
    return len(rows)


class ToolRecommender:
    def __init__(self, events_path: Path):
        self.catalog = load_catalog()
        self.tool_ids = [t["id"] for t in self.catalog]
        self._index = {t: i for i, t in enumerate(self.tool_ids)}
        docs = [f"{t['description']} {' '.join(map(str, t['tags']))}" for t in self.catalog]
        self._vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
        self._tool_vecs = self._vectorizer.fit_transform(docs)
        if not events_path.exists():
            n = generate_usage_events(events_path)
            log.info("Generated %d synthetic tool-usage events at %s", n, events_path)
        self._load_events(events_path)

    def _load_events(self, path: Path) -> None:
        with open(path, encoding="utf-8") as fh:
            events = [r for r in csv.DictReader(fh) if r["tool_id"] in self._index]
        self.users = sorted({e["user_id"] for e in events})
        self.user_roles = {e["user_id"]: e["role"] for e in events}
        u_index = {u: i for i, u in enumerate(self.users)}
        counts = np.zeros((len(self.users), len(self.tool_ids)))
        for e in events:
            counts[u_index[e["user_id"]], self._index[e["tool_id"]]] += 1
        self.counts = counts
        self._user_index = u_index
        self._fit(counts)

    def _fit(self, counts: np.ndarray) -> None:
        self.matrix = np.log1p(counts)
        sim = cosine_similarity(self.matrix.T)
        np.fill_diagonal(sim, 0.0)
        self.item_sim = np.nan_to_num(sim)
        self.role_popularity = {}
        for role in ROLE_RANK:
            rows = [self._user_index[u] for u in self.users if self.user_roles[u] == role]
            pop = self.matrix[rows].sum(axis=0) if rows else np.zeros(len(self.tool_ids))
            self.role_popularity[role] = pop / pop.max() if pop.max() else pop

    def affinity(self, user_id: str | None, role: str, matrix: np.ndarray | None = None) -> np.ndarray:
        m = self.matrix if matrix is None else matrix
        if user_id in self._user_index and m[self._user_index[user_id]].any():
            scores = m[self._user_index[user_id]] @ self.item_sim + m[self._user_index[user_id]]
            return scores / scores.max() if scores.max() else scores
        return self.role_popularity.get(role, np.zeros(len(self.tool_ids)))

    def recommend(self, query: str, role: str, user_id: str | None = None, k: int = 3) -> list[Recommendation]:
        relevance = cosine_similarity(self._vectorizer.transform([query]), self._tool_vecs)[0]
        affinity = self.affinity(user_id, role)
        # When the request clearly matches some tools, history alone must not pull in unrelated ones.
        allowed_rel = [relevance[i] for i, t in enumerate(self.catalog) if role_allows(role, t)]
        floor = 0.25 * max(allowed_rel) if allowed_rel and max(allowed_rel) >= 0.1 else -1.0
        out = []
        for i, tool in enumerate(self.catalog):
            if not role_allows(role, tool) or relevance[i] < floor:
                continue
            score = RELEVANCE_WEIGHT * relevance[i] + AFFINITY_WEIGHT * affinity[i]
            known = user_id in self._user_index
            reason = (f"matches your request ({relevance[i]:.2f}); "
                      f"{'fits your usage history' if known else f'popular with {role.lower()}s'} ({affinity[i]:.2f})")
            out.append(Recommendation(tool["id"], tool["description"], round(float(score), 4),
                                      round(float(relevance[i]), 4), round(float(affinity[i]), 4), reason))
        out.sort(key=lambda r: r.score, reverse=True)
        return out[:k]

    def evaluate_offline(self, seed: int = 5) -> dict[str, float]:
        """Leave-one-out: hide one tool per user, rank the rest; CF vs role-popularity baseline."""
        rng = random.Random(seed)
        ranks: dict[str, list[int]] = {"cf": [], "popularity": []}
        for u in self.users:
            ui = self._user_index[u]
            used = [j for j in range(len(self.tool_ids)) if self.counts[ui, j] > 0]
            if len(used) < 3:
                continue
            held = rng.choice(used)
            train_counts = self.counts.copy()
            train_counts[ui, held] = 0
            saved = (self.matrix, self.item_sim, self.role_popularity)
            self._fit(train_counts)
            role = self.user_roles[u]
            candidates = [j for j in range(len(self.tool_ids))
                          if train_counts[ui, j] == 0 and role_allows(role, self.catalog[j])]
            for kind, scores in (("cf", self.affinity(u, role)), ("popularity", self.role_popularity[role])):
                ranking = sorted(candidates, key=lambda j: scores[j], reverse=True)
                ranks[kind].append(ranking.index(held) + 1)
            self.matrix, self.item_sim, self.role_popularity = saved
        out: dict[str, float] = {"users_evaluated": len(ranks["cf"])}
        for kind, rs in ranks.items():
            out[f"{kind}_hit_at_1"] = round(sum(r == 1 for r in rs) / len(rs), 4)
            out[f"{kind}_hit_at_3"] = round(sum(r <= 3 for r in rs) / len(rs), 4)
            out[f"{kind}_mrr"] = round(sum(1 / r for r in rs) / len(rs), 4)
        return out


@lru_cache(maxsize=1)
def get_recommender() -> ToolRecommender:
    return ToolRecommender(get_settings().data_dir / "seeds" / "tool_usage_events.csv")


if __name__ == "__main__":
    rec = get_recommender()
    print(rec.evaluate_offline())
    for r in rec.recommend("I need to export last month's orders to a spreadsheet", "ANALYST", "u001"):
        print(r)
