"""Pydantic models describing extraction requests (control-plane contract)."""

from datetime import date

from pydantic import BaseModel, field_validator, model_validator


class ExtractSpec(BaseModel):
    """A validated Databento batch extraction request.

    `end` is exclusive, matching the Databento API.
    """

    model_config = {"frozen": True}

    dataset: str = "XNAS.ITCH"
    data_schema: str = "mbo"
    symbols: list[str]
    start: date
    end: date

    @field_validator("symbols")
    @classmethod
    def symbols_not_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one symbol is required")
        return value

    @model_validator(mode="after")
    def range_is_positive(self) -> "ExtractSpec":
        if self.start >= self.end:
            raise ValueError("start must be before end (end is exclusive)")
        return self
