"""Save incomplete backtest assumptions; execution validates numeric inputs."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Draft(BaseModel):
    model_config = ConfigDict(extra='forbid')


class BacktestAllocationDraft(Draft):
    ticker: str = Field(default='', max_length=40)
    weight: str = Field(default='', max_length=100)


class BacktestDraft(Draft):
    version: Literal[1] = 1
    source: Literal['market', 'demo'] = 'market'
    strategy: Literal['sma', 'buy_hold'] = 'sma'
    start: str = Field(default='', max_length=100)
    end: str = Field(default='', max_length=100)
    capital: str = Field(default='10000', max_length=100)
    assets: list[BacktestAllocationDraft] = Field(default_factory=lambda: [BacktestAllocationDraft(ticker='SPY', weight='100')], min_length=1, max_length=10)
    benchmark: str = Field(default='SPY', max_length=40)
    window: str = Field(default='50', max_length=100)
    commission_bps: str = Field(default='0', max_length=100)
    fee_per_order: str = Field(default='0', max_length=100)
    slippage_bps: str = Field(default='5', max_length=100)
    risk_free_percent: str = Field(default='0', max_length=100)
    hypothesis: str = Field(default='', max_length=3000)
