"""Hybrid, owner-scoped search over indexed document chunks."""

from dataclasses import dataclass

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.config import get_model_config
from app.ai.providers import EmbeddingProvider
from app.db.models import User


@dataclass(frozen=True)
class Citation:
    chunk_id: str
    document_id: str
    node_id: str | None
    folder_id: str | None
    file_name: str
    version: int | None
    position: int
    snippet: str
    score: float
    source: str = "upload"
    memo_id: str | None = None


def reciprocal_rank_fusion(*ranked: list[dict[str, object]], k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for rows in ranked:
        for rank, row in enumerate(rows, start=1):
            chunk_id = str(row["chunk_id"])
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


async def search_knowledge(
    session: AsyncSession,
    user: User,
    query: str,
    embedder: EmbeddingProvider,
    top_k: int | None = None,
    include_memos: bool = True,
) -> list[Citation]:
    phrase = query.strip()
    if not phrase:
        return []
    top_k = top_k or get_model_config().retrieval.top_k
    vector = (await embedder.embed([phrase]))[0]
    source_sql = """
        FROM chunks c JOIN documents d ON d.id = c.document_id
        LEFT JOIN nodes n ON n.id = d.node_id AND n.user_id = :user_id
        LEFT JOIN file_versions fv ON fv.id = d.version_id AND fv.user_id = :user_id
        LEFT JOIN memos m ON m.document_id = d.id AND m.user_id = :user_id
        WHERE c.user_id = :user_id AND d.user_id = :user_id AND d.status = 'ready'
          AND (
            (d.source = 'upload' AND n.id IS NOT NULL AND n.deleted_at IS NULL
             AND fv.version = (SELECT max(latest.version) FROM file_versions latest
                               WHERE latest.node_id = n.id AND latest.user_id = :user_id))
            OR (d.source = 'memo' AND m.id IS NOT NULL AND CAST(:include_memos AS boolean))
          )
    """
    columns = """
        SELECT c.id AS chunk_id, c.document_id, d.node_id, n.parent_id AS folder_id,
               coalesce(n.name, d.title) AS file_name, fv.version, c.position, c.content,
               d.source, m.id AS memo_id
    """
    vector_sql = text(
        columns + ", c.embedding <=> :vec AS distance " + source_sql
        + " ORDER BY c.embedding <=> :vec, c.id LIMIT :limit"
    ).bindparams(bindparam("vec", type_=Vector(1536)))
    keyword_sql = text(
        columns + ", left(c.content, 240) AS snippet " + source_sql
        + " AND c.search @@ plainto_tsquery('simple', :query)"
        + " ORDER BY ts_rank(c.search, plainto_tsquery('simple', :query)) DESC, c.id LIMIT :limit"
    )
    params = {"user_id": user.id, "limit": top_k, "include_memos": include_memos}
    vector_rows = [dict(row) for row in (await session.execute(vector_sql, {**params, "vec": vector})).mappings()]
    keyword_rows = [dict(row) for row in (await session.execute(keyword_sql, {**params, "query": phrase})).mappings()]
    merged = reciprocal_rank_fusion(vector_rows, keyword_rows)[:top_k]
    by_id = {str(row["chunk_id"]): row for row in vector_rows + keyword_rows}
    return [
        Citation(
            chunk_id=chunk_id,
            document_id=str(by_id[chunk_id]["document_id"]),
            node_id=str(by_id[chunk_id]["node_id"]) if by_id[chunk_id]["node_id"] else None,
            folder_id=str(by_id[chunk_id]["folder_id"]) if by_id[chunk_id]["folder_id"] else None,
            file_name=str(by_id[chunk_id]["file_name"]),
            version=int(by_id[chunk_id]["version"]) if by_id[chunk_id]["version"] is not None else None,
            position=int(by_id[chunk_id]["position"]),
            snippet=str(by_id[chunk_id].get("snippet") or str(by_id[chunk_id]["content"])[:240]),
            score=score,
            source=str(by_id[chunk_id]["source"]),
            memo_id=str(by_id[chunk_id]["memo_id"]) if by_id[chunk_id]["memo_id"] else None,
        )
        for chunk_id, score in merged
    ]
