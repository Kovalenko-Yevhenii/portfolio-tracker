"""Lossless drafts for manually entered valuations, including incomplete inputs."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field

Text = Annotated[str, Field(max_length=100)]


class Draft(BaseModel):
    model_config = ConfigDict(extra='forbid')


class YearDraft(Draft):
    ebit: Text = ''
    tax_rate: Text = ''
    depreciation: Text = ''
    capex: Text = ''
    change_nwc: Text = ''


class CaseDraft(Draft):
    name: Literal['Bear', 'Base', 'Bull']
    enabled: bool = False
    wacc: Text = ''
    growth: Text = ''
    exit_multiple: Text = ''
    years: list[YearDraft] = Field(default_factory=lambda:[YearDraft() for _ in range(5)], min_length=1, max_length=10)


class PeerDraft(Draft):
    name: Annotated[str, Field(max_length=80)] = ''
    enterprise_value: Text = ''
    equity_value: Text = ''
    revenue: Text = ''
    ebitda: Text = ''
    net_income: Text = ''


class OptionPricingDraft(Draft):
    symbol: Annotated[str, Field(max_length=80)] = ''
    hypothesis: Annotated[str, Field(max_length=3000)] = ''
    currency: Literal['USD','CAD','EUR','GBP'] = 'USD'
    as_of: Text = ''
    maturity: Text = ''
    spot: Text = ''
    rate: Text = '0'
    contracts: Text = '1'
    contract_size: Text = '100'
    exercise: Literal['european','american'] = 'european'
    kind: Literal['call','put'] = 'call'
    strike: Text = ''
    volatility: Text = ''
    dividend_yield: Text = '0'
    market_price: Text = ''
    tree_steps: Literal['250','500','1000'] = '500'


class FuturesPricingDraft(Draft):
    symbol: Annotated[str, Field(max_length=80)] = ''
    hypothesis: Annotated[str, Field(max_length=3000)] = ''
    currency: Literal['USD','CAD','EUR','GBP'] = 'USD'
    as_of: Text = ''
    maturity: Text = ''
    spot: Text = ''
    rate: Text = '0'
    contracts: Text = '1'
    contract_size: Text = ''
    asset: Literal['equity','fx','commodity'] = 'equity'
    income_yield: Text = '0'
    foreign_rate: Text = '0'
    storage_rate: Text = '0'
    convenience_yield: Text = '0'
    market_price: Text = ''


class BondDraft(Draft):
    name: Text = ''
    hypothesis: Annotated[str, Field(max_length=3000)] = ''
    issuer_type: Literal['government','corporate'] = 'government'
    currency: Literal['USD','CAD','EUR','GBP'] = 'USD'
    settlement: Text = ''
    maturity: Text = ''
    face_amount: Text = '10000'
    coupon_rate: Text = ''
    frequency: Literal['1','2','4'] = '2'
    day_count: Literal['actual_actual','30u360'] = 'actual_actual'
    date_roll: Literal['maturity_day','month_end'] = 'maturity_day'
    discounting: Literal['compound','simple_final'] = 'compound'
    mode: Literal['price','yield','spread'] = 'price'
    yield_percent: Text = ''
    benchmark_yield: Text = ''
    spread_bps: Text = ''
    market_clean: Text = ''


class AnalyticsDraft(Draft):
    version: Literal[1,2,3] = 1
    tool: Literal['equity','option','futures','bond'] = 'equity'
    bond_pricing: BondDraft = Field(default_factory=BondDraft)
    option_pricing: OptionPricingDraft = Field(default_factory=OptionPricingDraft)
    futures_pricing: FuturesPricingDraft = Field(default_factory=FuturesPricingDraft)
    company: Text = ''
    hypothesis: Annotated[str, Field(max_length=3000)] = ''
    valuation_date: Text = ''
    currency: Literal['USD', 'CAD', 'EUR', 'GBP'] = 'USD'
    units: Literal['units', 'thousands', 'millions', 'billions'] = 'millions'
    shares: Text = ''
    current_price: Text = ''
    cash: Text = '0'
    debt: Text = '0'
    preferred: Text = '0'
    minority: Text = '0'
    nonoperating: Text = '0'
    dcf_enabled: bool = True
    comps_enabled: bool = False
    tax_benefit: bool = False
    terminal_method: Literal['growth', 'multiple', 'both'] = 'growth'
    cases: list[CaseDraft] = Field(default_factory=lambda:[CaseDraft(name=n,enabled=n=='Base') for n in ['Bear','Base','Bull']], min_length=3, max_length=3)
    period: Annotated[str, Field(max_length=80)] = ''
    revenue: Text = ''
    ebitda: Text = ''
    net_income: Text = ''
    peers: list[PeerDraft] = Field(default_factory=lambda:[PeerDraft(),PeerDraft(),PeerDraft()], min_length=1, max_length=30)
