"""Contract for future licensed historical option data adapters.

Not connected to the modeled simulator: real-quote testing also needs actual
contract selection, exchange calendars and exercise handling. No fallback to BSM.
Implementations obtain credentials from their environment, never from snapshots.
"""
from dataclasses import dataclass
from datetime import date, datetime
import math
from typing import Literal, Protocol, Sequence


@dataclass(frozen=True)
class HistoricalContract:
    symbol: str
    underlying: str
    expiration: date
    strike: float
    kind: Literal['call', 'put']
    exercise: Literal['american', 'european']
    multiplier: int
    standard_deliverable: bool

    def __post_init__(self):
        if not self.symbol.strip() or not self.underlying.strip() or not isinstance(self.expiration,date):
            raise ValueError('A contract needs its identifier, underlying and expiration date.')
        if not math.isfinite(self.strike) or self.strike <= 0 or type(self.multiplier) is not int or self.multiplier <= 0:
            raise ValueError('Contract strike and integer multiplier must be positive.')
        if self.kind not in {'call','put'} or self.exercise not in {'american','european'} or type(self.standard_deliverable) is not bool:
            raise ValueError('Record option kind, exercise style and deliverable status explicitly.')


@dataclass(frozen=True)
class HistoricalQuote:
    contract: HistoricalContract
    observed_at: datetime
    available_at: datetime
    bid: float
    ask: float
    provider: str

    def validate_for(self, as_of: datetime, max_age_seconds: float):
        if any(t.tzinfo is None or t.utcoffset() is None for t in [as_of,self.observed_at,self.available_at]):
            raise ValueError('Quotes and requests need timezone-aware timestamps.')
        if not math.isfinite(max_age_seconds) or max_age_seconds < 0:
            raise ValueError('Specify a finite non-negative quote age limit.')
        if not self.observed_at <= self.available_at <= as_of:
            raise ValueError('The quote was not available at the requested decision time.')
        if (as_of-self.observed_at).total_seconds() > max_age_seconds:
            raise ValueError('The historical quote is stale.')
        if not all(math.isfinite(v) for v in [self.bid,self.ask]) or not 0 <= self.bid <= self.ask:
            raise ValueError('Historical bid/ask quotes must be finite, non-negative and uncrossed.')
        if not self.provider.strip():
            raise ValueError('Record the data provider explicitly.')
        return self


class HistoricalOptionsProvider(Protocol):
    """Adapters must expose only contracts/quotes available at the given time.

Return None for missing quotes; never silently manufacture a price. Licensing,
entitlements and redistribution rights belong to each provider implementation.
"""
    def contracts(self, underlying: str, as_of: datetime) -> Sequence[HistoricalContract]: ...
    def quote(self, contract: HistoricalContract, as_of: datetime) -> HistoricalQuote | None: ...
