"""Incomplete user assumptions are saved verbatim, separately from stock backtests."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class CoveredCallDraft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal[1] = 1
    source: Literal['market','demo'] = 'market'
    ticker: str = Field(default='AAPL',max_length=40)
    start: str = Field(default='',max_length=100)
    end: str = Field(default='',max_length=100)
    capital: str = Field(default='25000',max_length=100)
    contracts: str = Field(default='1',max_length=100)
    tenor_sessions: str = Field(default='20',max_length=100)
    otm_percent: str = Field(default='5',max_length=100)
    strike_increment: str = Field(default='1',max_length=100)
    roll_before: str = Field(default='0',max_length=100)
    volatility_mode: Literal['fixed','trailing'] = 'fixed'
    volatility_percent: str = Field(default='25',max_length=100)
    volatility_window: str = Field(default='30',max_length=100)
    volatility_premium: str = Field(default='5',max_length=100)
    rate_percent: str = Field(default='0',max_length=100)
    dividend_yield_percent: str = Field(default='0',max_length=100)
    stock_fee_bps: str = Field(default='1',max_length=100)
    stock_slippage_bps: str = Field(default='5',max_length=100)
    option_fee: str = Field(default='.65',max_length=100)
    option_half_spread_percent: str = Field(default='5',max_length=100)
    assignment_fee: str = Field(default='0',max_length=100)
    hypothesis: str = Field(default='',max_length=3000)
