from typing import Literal

from fastapi_users import schemas
from pydantic import computed_field


class UserRead(schemas.BaseUser[str]):
    @computed_field  # type: ignore[prop-decorator]
    @property
    def role(self) -> Literal["admin", "member"]:
        return "admin" if self.is_superuser else "member"


class UserCreate(schemas.BaseUserCreate):
    pass
