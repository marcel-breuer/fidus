import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class ModelConfig:
    chat: str
    embedding: str
    embedding_dimensions: int
    transcription: str
    web_search: bool
    retrieval: "RetrievalConfig"


@dataclass(frozen=True)
class RetrievalConfig:
    chunk_size_chars: int = 1200
    chunk_overlap_chars: int = 200
    top_k: int = 8


@lru_cache(maxsize=1)
def get_model_config() -> ModelConfig:
    path = Path(__file__).with_name("models.toml")
    with path.open("rb") as file:
        values = tomllib.load(file)
    return ModelConfig(**{**values, "retrieval": RetrievalConfig(**values.get("retrieval", {}))})
