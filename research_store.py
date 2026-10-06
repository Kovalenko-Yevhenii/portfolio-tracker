"""Incomplete research inputs are saved as text, validated on calculation."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Draft(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class SurfaceDraft(Draft):
    version: Literal[1] = 1
    source: Literal['demo','market'] = 'demo'
    symbol: str = Field(default='',max_length=40)
    expirations: list[str] = Field(default_factory=list,max_length=4)
    kind: Literal['otm','call','put'] = 'otm'
    rate: str = Field(default='0',max_length=100)
    dividend_yield: str = Field(default='0',max_length=100)
    min_open_interest: str = Field(default='0',max_length=100)
    max_spread_percent: str = Field(default='50',max_length=100)


class CryptoRow(Draft):
    ticker: str = Field(default='',max_length=40)
    quantity: str = Field(default='',max_length=100)
    avg_cost: str = Field(default='',max_length=100)


class CryptoDraft(Draft):
    version: Literal[1] = 1
    source: Literal['demo','market'] = 'market'
    holdings: list[CryptoRow] = Field(default_factory=lambda:[CryptoRow()],min_length=1,max_length=10)
    cash: str = Field(default='0',max_length=100)
    benchmark: str = Field(default='BTC-USD',max_length=40)
    start: str = Field(default='',max_length=100)
    end: str = Field(default='',max_length=100)
    risk_free_percent: str = Field(default='0',max_length=100)
