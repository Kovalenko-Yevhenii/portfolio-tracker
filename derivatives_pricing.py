"""Manual vanilla option and cost-of-carry pricing. No market data or execution."""
from datetime import date
import math
from typing import Annotated, Literal
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from options_pricing import bsm, greeks
from tracker import PortfolioError

Positive = Annotated[float, Field(ge=1e-8, le=1e8)]
Rate = Annotated[float, Field(ge=-20, le=100)]
Yield = Annotated[float, Field(ge=0, le=100)]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class DatedRequest(Model):
    symbol: str = Field(default='', max_length=80)
    hypothesis: str = Field(default='', max_length=3000)
    currency: Literal['USD','CAD','EUR','GBP'] = 'USD'
    as_of: date
    maturity: date
    spot: Positive
    rate: Rate
    contracts: int = Field(default=1, gt=0, le=1_000_000)
    contract_size: Positive

    @model_validator(mode='after')
    def dates(self):
        days = (self.maturity-self.as_of).days
        if not 0 <= days <= 3653:
            raise ValueError('Maturity must be on or after the valuation date and within 10 years.')
        return self


class OptionPricingRequest(DatedRequest):
    exercise: Literal['european','american'] = 'european'
    kind: Literal['call','put'] = 'call'
    strike: Positive
    volatility: float = Field(ge=0, le=300)
    dividend_yield: Yield
    market_price: float | None = Field(default=None, ge=0, le=1e8)
    tree_steps: Literal[250,500,1000] = 500

    @model_validator(mode='after')
    def numerical_resolution(self):
        if 0 < self.volatility < .0001:
            raise ValueError('Use zero volatility or at least 0.0001% volatility.')
        return self


class FuturesPricingRequest(DatedRequest):
    asset: Literal['equity','fx','commodity'] = 'equity'
    income_yield: Yield = 0
    foreign_rate: Rate = 0
    storage_rate: Yield = 0
    convenience_yield: Yield = 0
    market_price: Positive | None = None

    @model_validator(mode='after')
    def relevant_carry(self):
        if self.asset != 'equity' and self.income_yield != 0:
            raise ValueError('Income yield applies only to equity/index futures.')
        if self.asset != 'fx' and self.foreign_rate != 0:
            raise ValueError('Foreign interest rate applies only to FX futures.')
        if self.asset != 'commodity' and (self.storage_rate != 0 or self.convenience_yield != 0):
            raise ValueError('Storage and convenience yields apply only to commodity futures.')
        return self


def intrinsic(kind, spot, strike):
    return max(0., spot-strike if kind=='call' else strike-spot)


def deterministic_american(kind, spot, strike, years, rate, dividend):
    """Zero-volatility optimal stopping, including a possible interior optimum."""
    times = [0., years]
    if rate != dividend and dividend != 0 and rate*strike/(dividend*spot) > 0:
        critical = math.log(rate*strike/(dividend*spot))/(rate-dividend)
        if 0 < critical < years:
            times.append(critical)
    return max(max(0., (spot*math.exp(-dividend*t)-strike*math.exp(-rate*t))*(1 if kind=='call' else -1)) for t in times)


def crr(kind, spot, strike, years, sigma, rate, dividend, steps):
    """Cox–Ross–Rubinstein rollback; continuous yield, exercise at each node."""
    if years == 0:
        value=intrinsic(kind,spot,strike)
        return dict(price=value,european=value,up=None,down=None,probability=None,discount=None)
    if sigma == 0:
        return dict(price=deterministic_american(kind,spot,strike,years,rate,dividend),
                    european=bsm(kind,spot,strike,years,0,rate,dividend),up=None,down=None,probability=None,discount=None)
    dt=years/steps;logup=sigma*math.sqrt(dt);up=math.exp(logup);down=1/up
    # expm1 avoids cancellation when volatility and the time step are small.
    probability=math.expm1((rate-dividend)*dt+logup)/math.expm1(2*logup)
    if not 0 <= probability <= 1:
        raise PortfolioError('The binomial tree cannot represent these rates and volatility at this resolution. Increase tree steps or review the assumptions.')
    discount=math.exp(-rate*dt)
    stock=spot*np.exp((2*np.arange(steps+1)-steps)*logup)
    sign=1 if kind=='call' else -1
    american=np.maximum(sign*(stock-strike),0.);european=american.copy()
    for _ in range(steps,0,-1):
        american=discount*((1-probability)*american[:-1]+probability*american[1:])
        european=discount*((1-probability)*european[:-1]+probability*european[1:])
        stock=stock[:-1]*up
        american=np.maximum(american,np.maximum(sign*(stock-strike),0.))
    # Repeated node updates can drift slightly from the exact input spot at root.
    # Immediate exercise must always retain its exact input-based lower bound.
    return dict(price=max(float(american[0]),intrinsic(kind,spot,strike)),european=float(european[0]),up=up,down=down,probability=probability,discount=discount)


def quote_iv(req, years):
    if req.market_price is None:
        return None, None
    if req.exercise != 'european':
        return None, 'Implied volatility is available for European pricing only.'
    if years == 0:
        return None, 'Implied volatility is undefined at expiry.'
    r,q=req.rate/100,req.dividend_yield/100
    lower=bsm(req.kind,req.spot,req.strike,years,0,r,q)
    upper=req.spot*math.exp(-q*years) if req.kind=='call' else req.strike*math.exp(-r*years)
    if req.market_price < lower or req.market_price >= upper:
        return None, 'The entered quote is outside the finite-volatility European model bounds.'
    if req.market_price == lower:
        return 0., None
    if req.market_price > bsm(req.kind,req.spot,req.strike,years,3,r,q):
        return None, 'Implied volatility exceeds this calculator’s 300% search limit.'
    lo,hi=0.,3.
    for _ in range(75):
        mid=(lo+hi)/2
        if bsm(req.kind,req.spot,req.strike,years,mid,r,q) < req.market_price:lo=mid
        else:hi=mid
    return (lo+hi)*50, None


def price_option(req):
    days=(req.maturity-req.as_of).days;years=days/365
    r,q,sigma=req.rate/100,req.dividend_yield/100,req.volatility/100
    euro=bsm(req.kind,req.spot,req.strike,years,sigma,r,q)
    convergence=None;warnings=[]
    def price(spot,vol):
        if req.exercise=='european':return bsm(req.kind,spot,req.strike,years,vol/100,r,q)
        return crr(req.kind,spot,req.strike,years,vol/100,r,q,req.tree_steps*2)['price']
    if req.exercise=='american':
        fine=crr(req.kind,req.spot,req.strike,years,sigma,r,q,req.tree_steps*2)
        try:
            coarse=crr(req.kind,req.spot,req.strike,years,sigma,r,q,req.tree_steps)['price']
        except PortfolioError:
            coarse=None
        value=fine['price'];difference=None if coarse is None else abs(value-coarse)
        convergence=dict(coarse_steps=req.tree_steps,fine_steps=req.tree_steps*2,coarse_price=coarse,fine_price=value,
                         difference=difference,european_tree=fine['european'],european_closed=euro,
                         european_tree_error=fine['european']-euro,early_exercise_premium=max(0.,value-fine['european']),
                         up=fine['up'],down=fine['down'],probability=fine['probability'],discount=fine['discount'])
        if difference is None or difference > max(.001,abs(value)*.001):
            warnings.append('The two tree resolutions differ materially, or the coarse tree is invalid. Review the convergence table and try more steps; the difference is not an error bound.')
    else:value=euro
    if days == 0:warnings.append('At expiry the model returns intrinsic value; volatility sensitivities and Greeks are not informative.')
    if req.volatility==0:warnings.append('Zero volatility uses the deterministic limit. Greeks are unavailable at this boundary.')
    iv,iv_note=quote_iv(req,years)
    if iv_note:warnings.append(iv_note)
    spots=[req.spot*f for f in [.8,.9,1,1.1,1.2]]
    vols=sorted({max(0.,min(300.,req.volatility+shift)) for shift in [-10,-5,0,5,10]})
    grid=[];invalid=False
    for spot in spots:
        values=[]
        for vol in vols:
            try:values.append(price(spot,vol))
            except PortfolioError:values.append(None);invalid=True
        grid.append(dict(spot=spot,values=values))
    if invalid:warnings.append('Some sensitivity cells have invalid tree probabilities and are shown as unavailable.')
    v=sigma*math.sqrt(years)
    d1=(math.log(req.spot/req.strike)+(r-q+sigma*sigma/2)*years)/v if v>0 else None
    return dict(model='Black–Scholes–Merton' if req.exercise=='european' else 'American CRR binomial',
                currency=req.currency,days=days,years=years,unit_price=value,
                per_contract=value*req.contract_size,total_premium=value*req.contract_size*req.contracts,
                intrinsic=intrinsic(req.kind,req.spot,req.strike),european_price=euro,
                market_gap=None if req.market_price is None else req.market_price-value,
                implied_volatility=iv,convergence=convergence,
                greeks=greeks(req.kind,req.spot,req.strike,years,sigma,r,q) if req.exercise=='european' else None,
                audit=dict(spot_discount=math.exp(-q*years),strike_discount=math.exp(-r*years),
                           discounted_spot=req.spot*math.exp(-q*years),discounted_strike=req.strike*math.exp(-r*years),
                           d1=d1,d2=d1-v if d1 is not None else None,day_basis='ACT/365',rate_compounding='continuous'),
                sensitivity=dict(columns=vols,rows=grid),warnings=warnings,model_version=1)


def price_futures(req):
    days=(req.maturity-req.as_of).days;years=days/365
    adjustment=-req.income_yield if req.asset=='equity' else -req.foreign_rate if req.asset=='fx' else req.storage_rate-req.convenience_yield
    carry=(req.rate+adjustment)/100;factor=math.exp(carry*years);fair=req.spot*factor
    rates=[req.rate+shift for shift in [-1,-.5,0,.5,1]]
    rows=[dict(spot=req.spot*f,values=[req.spot*f*math.exp((rate+adjustment)/100*years) for rate in rates]) for f in [.8,.9,1,1.1,1.2]]
    gap=None if req.market_price is None else req.market_price-fair
    return dict(model='Cost of carry',asset=req.asset,currency=req.currency,days=days,years=years,
                unit_price=fair,basis=fair-req.spot,carry_percent=carry*100,carry_factor=factor,
                per_contract_notional=fair*req.contract_size,total_notional=fair*req.contract_size*req.contracts,
                market_gap=gap,market_gap_percent=None if gap is None else gap/fair*100,
                spot_sensitivity=factor,rate_sensitivity=fair*years/100,
                audit=dict(formula='F = S × exp((r − q) × T)' if req.asset=='equity' else 'F = S × exp((r_domestic − r_foreign) × T)' if req.asset=='fx' else 'F = S × exp((r + storage − convenience) × T)',
                           rate_percent=req.rate,carry_adjustment_percent=adjustment,exponent=carry*years,
                           day_basis='ACT/365',rate_compounding='continuous'),
                sensitivity=dict(columns=rates,rows=rows),warnings=[],model_version=1)
