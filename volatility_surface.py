"""Observed strike/expiry IV grid. No interpolation or executable-price claims."""
from datetime import date, datetime, timezone
import math
from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from derivatives_pricing import quote_iv
from options_pricing import bsm
from tracker import PortfolioError


class SurfaceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    source: Literal['demo', 'market'] = 'demo'
    symbol: str = Field(default='', max_length=40)
    expirations: list[date] = Field(default_factory=list, max_length=4)
    kind: Literal['otm', 'call', 'put'] = 'otm'
    rate: float = Field(default=0, ge=-20, le=100)
    dividend_yield: float = Field(default=0, ge=0, le=100)
    min_open_interest: int = Field(default=0, ge=0, le=100000000)
    max_spread_percent: float = Field(default=50, gt=0, le=200)
    refresh: bool = False


def demo_chains():
    chains = []
    for exp, term in [('2025-02-01', 0), ('2025-04-01', 1), ('2025-07-01', 2)]:
        years = (date.fromisoformat(exp)-date(2025, 1, 1)).days/365
        rows = []
        for kind in ('call', 'put'):
            for strike in (80, 90, 100, 110, 120):
                sigma = .23 + .0015*(100-strike) + .012*term + .00003*(100-strike)**2
                mid = bsm(kind, 100, strike, years, sigma, 0, 0)
                rows.append(dict(kind=kind, strike=strike, expiration=exp, bid=mid*.98,
                                 ask=mid*1.02, open_interest=500, volume=20, multiplier=100,
                                 currency='USD', contract_symbol=f'DEMO-{exp}-{kind}-{strike}',
                                 iv=sigma*100, last_trade=None))
        # Deliberately bad quotes demonstrate holes in the observed grid.
        if not term:
            next(r for r in rows if r['kind']=='put' and r['strike']==80)['bid'] = 0
            next(r for r in rows if r['kind']=='call' and r['strike']==120)['ask'] = 50
        chains.append(dict(symbol='DEMO-IV', currency='USD', spot=100, expiration=exp,
                           contracts=rows, fetched_at=None, underlying_time=None,
                           source='Invented offline quotes'))
    return chains


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def build_surface(req, chains, as_of=None):
    as_of = as_of or (date(2025, 1, 1) if req.source=='demo' else datetime.now(timezone.utc).date())
    if not chains or len(chains)>4:
        raise PortfolioError('Choose one to four expirations.')
    currencies = {c.get('currency') for c in chains}
    if len(currencies)!=1 or not currencies.issubset({'USD', 'CAD'}):
        raise PortfolioError('All surface quotes must use the same supported currency.')
    expected_symbol = 'DEMO-IV' if req.source=='demo' else req.symbol.strip().upper()
    if any(c.get('symbol') != expected_symbol for c in chains):
        raise PortfolioError('All chains must belong to the selected underlying.')
    if sum(len(c.get('contracts', [])) for c in chains)>6000:
        raise PortfolioError('Too many quotes. Select fewer expirations.')
    audit, points, seen = [], [], set()
    for chain in chains:
        spot = chain.get('spot')
        if not finite(spot) or not 1e-8 <= spot <= 1e8:
            raise PortfolioError('The chain has no valid underlying price.')
        for raw in chain.get('contracts', []):
            row = {**raw, 'spot': spot, 'iv_percent': None, 'spread_percent': None,
                   'status': 'excluded', 'reason': ''}
            reason = ''
            kind, strike, bid, ask = (raw.get(k) for k in ('kind', 'strike', 'bid', 'ask'))
            try:
                maturity = date.fromisoformat(raw.get('expiration', ''))
                days = (maturity-as_of).days
            except (ValueError, TypeError):
                days = 0
            key = (raw.get('expiration'), kind, strike)
            if kind not in ('call','put') or not finite(strike) or not 1e-8<=strike<=1e8:
                reason = 'Invalid option type or strike.'
            elif key in seen:
                raise PortfolioError('Duplicate strike/type/expiry quotes; resolve the contract deliverables first.')
            elif raw.get('expiration') != chain.get('expiration') or not 1 <= days <= 3653:
                reason = 'Expired, inconsistent expiry, or beyond the ten-year model horizon.'
            elif req.kind!='otm' and kind!=req.kind or req.kind=='otm' and (kind=='call' and strike<spot or kind=='put' and strike>=spot):
                reason = 'Outside the selected option side.'
            elif raw.get('currency') != chain['currency'] or raw.get('multiplier') not in (10,100):
                reason = 'Unverified currency or contract size.'
            elif not finite(bid) or not finite(ask) or bid<=0 or ask<bid:
                reason = 'Missing, zero-bid or crossed market.'
            elif req.min_open_interest>0 and (not finite(raw.get('open_interest')) or raw['open_interest']<req.min_open_interest):
                reason = 'Open interest is missing or below the filter.'
            else:
                mid=(bid+ask)/2
                spread=(ask-bid)/mid*100
                row.update(mid=mid, spread_percent=spread)
                if spread>req.max_spread_percent:
                    reason = 'Bid/ask spread exceeds the filter.'
                else:
                    pricing = SimpleNamespace(market_price=mid, exercise='european', kind=kind,
                                              spot=spot, strike=strike, rate=req.rate,
                                              dividend_yield=req.dividend_yield)
                    iv, reason = quote_iv(pricing, days/365)
                    if not reason:
                        row.update(iv_percent=iv, status='included', days=days)
                        points.append(row)
            seen.add(key)
            row['reason'] = reason or 'European midpoint-equivalent IV; quote age unknown.'
            audit.append(row)
    return dict(model_version=1, result_type='observed_iv_grid', as_of=as_of.isoformat(),
                symbol=expected_symbol, currency=next(iter(currencies)), settings=req.model_dump(mode='json'),
                points=points, audit=audit, observations=chains,
                expirations=sorted({c['expiration'] for c in chains}),
                strikes=sorted({p['strike'] for p in points}),
                included=len(points), excluded=len(audit)-len(points),
                notes=['Offline quotes are invented.' if req.source=='demo' else 'Yahoo quotes are delayed snapshots, not synchronized executable markets.',
                       'IV is inverted from bid/ask midpoint with European BSM, ACT/365, and your constant rates. American early exercise and discrete dividends are not modeled.',
                       'Retrieval time and last-trade time are not bid/ask timestamps. Quote freshness cannot be verified.',
                       'No interpolation, extrapolation, fitted surface or arbitrage-free calibration. Blank cells remain unavailable. IV is not a forecast.',
                       'Each expiry uses its own retrieved underlying spot. Snapshots can differ across expirations.'])
