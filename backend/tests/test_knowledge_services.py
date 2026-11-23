from types import SimpleNamespace

import pytest

from app.ai.fakes import FakeEmbeddingProvider, KeywordEmbeddingProvider
from app.services.retrieval import reciprocal_rank_fusion, search_knowledge


@pytest.mark.asyncio
async def test_fake_embedding_providers_are_deterministic_and_normalized() -> None:
	provider = FakeEmbeddingProvider(dimensions=16)
	first, repeated = await provider.embed(["same", "same"])
	assert first == repeated
	assert len(first) == 16
	assert sum(value * value for value in first) == pytest.approx(1)

	keywords = KeywordEmbeddingProvider(dimensions=64)
	one, shared = await keywords.embed(["blue house", "blue garden"])
	assert sum(a * b for a, b in zip(one, shared, strict=True)) > 0


def test_reciprocal_rank_fusion_merges_rankings() -> None:
	vector = [{"chunk_id": "both"}, {"chunk_id": "vector"}]
	keyword = [{"chunk_id": "both"}, {"chunk_id": "keyword"}]
	merged = reciprocal_rank_fusion(vector, keyword)
	assert merged[0][0] == "both"
	assert {identifier for identifier, _ in merged} == {"both", "vector", "keyword"}


@pytest.mark.asyncio
async def test_hybrid_search_keeps_vector_only_keyword_only_and_combined_hits() -> None:
	def row(chunk_id: str) -> dict[str, object]:
		return {
			"chunk_id": chunk_id, "document_id": f"{chunk_id}-doc", "node_id": f"{chunk_id}-node",
			"folder_id": None, "file_name": f"{chunk_id}.txt", "version": 1, "position": 0,
			"content": f"content {chunk_id}", "snippet": None, "source": "upload", "memo_id": None
		}

	class Result:
		def __init__(self, rows: list[dict[str, object]]) -> None:
			self.rows = rows

		def mappings(self):
			return self

		def __iter__(self):
			return iter(self.rows)

	class Session:
		def __init__(self) -> None:
			self.results = [Result([row("both"), row("vector-only")]), Result([row("both"), row("keyword-only")])]

		async def execute(self, statement, params):
			return self.results.pop(0)

	user = SimpleNamespace(id="owner")
	hits = await search_knowledge(Session(), user, "shared phrase", KeywordEmbeddingProvider(64))
	assert {hit.chunk_id for hit in hits} == {"both", "vector-only", "keyword-only"}
	assert hits[0].chunk_id == "both"
