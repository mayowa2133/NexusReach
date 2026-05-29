from pydantic import BaseModel, Field


class AccountDeleteRequest(BaseModel):
    confirm: bool = Field(
        default=False,
        description="Must be true to confirm irreversible account deletion.",
    )


class AccountDeleteResponse(BaseModel):
    deleted: bool
    auth_identity_deleted: bool
    deleted_tables: dict[str, int]
