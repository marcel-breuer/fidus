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


@lru_cache(maxsize=1)
def get_model_config() -> ModelConfig:
    path = Path(__file__).with_name("models.toml")
    with path.open("rb") as file:
        return ModelConfig(**tomllib.load(file))
