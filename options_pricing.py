"""Multi-leg vanilla option scenarios. European Black–Scholes with continuous yield.

Same-expiry payoff extrema/roots are exact Decimal results, independent of plotting.
Dated scenarios stop at the first expiry; later-expiring legs retain time value.
"""
from datetime import date, timedelta
from decimal import Decimal, localcontext
import math
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal
from tracker import PortfolioError
from options_analysis import _zeros


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class OptionLeg(Model):
    kind: Literal['call','put','stock'] = 'call'
    side: Literal['buy','sell'] = 'buy'
    quantity: float = Field(default=1, gt=0, le=1_000_000)
    multiplier: int = Field(default=100, gt=0, le=10000)
    strike: float | None = Field(default=None, gt=0, le=1_000_000)
    premium: float = Field(ge=0, le=1_000_000)
    expiration: date | None = None
    iv: float | None = Field(default=None, ge=0, le=500)
    contract_symbol: str = Field(default='', max_length=100)

    @model_validator(mode='after')
    def validate_option(self):
        if self.kind != 'stock' and (self.strike is None or not float(self.quantity).is_integer()):
            raise ValueError('Options require a strike and a whole number of contracts.')
        return self


class ScenarioRequest(Model):
    strategy: str = Field(default='custom', max_length=80)
    symbol: str = Field(default='', max_length=40)
    currency: Literal['USD','CAD'] = 'USD'
    mode: Literal['expiry','dated'] = 'dated'
    legs: list[OptionLeg] = Field(min_length=1, max_length=9)
    spot: float | None = Field(default=None, gt=0, le=1_000_000)
    as_of: date = Field(default_factory=date.today)
    target_date: date | None = None
    rate: float = Field(default=0, ge=-20, le=100)
    dividend_yield: float = Field(default=0, ge=0, le=100)
    iv_shift: float = Field(default=0, ge=-500, le=500)
    probability_iv: float = Field(default=30, gt=0, le=500)
    fee_per_contract: float = Field(default=0, ge=0, le=10000)
    range_min: float | None = Field(default=None, ge=0, le=1_000_000)
    range_max: float | None = Field(default=None, gt=0, le=1_000_000)
    scenario_price: float | None = Field(default=None, ge=0, le=1_000_000)
    capital_basis: float | None = Field(default=None, gt=0, le=1e12)
    include_stock_cost: bool = True
    comparison_budget: float | None = Field(default=None, gt=0, le=1e12)
    financing_enabled: bool = False
    borrowed_amount: float = Field(default=0, ge=0, le=1e12)
    borrowing_rate: float = Field(default=0, ge=0, le=100)
    financing_days: int | None = Field(default=None, ge=0, le=3653)


def cdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


def bsm(kind, spot, strike, years, sigma, rate=0., dividend=0.):
    """Per-unit value; zero spot/vol/time use the corresponding analytic limit."""
    if years <= 0:
        return max(0., spot-strike if kind=='call' else strike-spot)
    a, b = spot*math.exp(-dividend*years), strike*math.exp(-rate*years)
    if spot == 0 or sigma == 0:
        return max(0., a-b if kind=='call' else b-a)
    v = sigma*math.sqrt(years)
    d1 = (math.log(spot/strike)+(rate-dividend+sigma*sigma/2)*years)/v
    d2 = d1-v
    return max(0., a*cdf(d1)-b*cdf(d2) if kind=='call' else b*cdf(-d2)-a*cdf(-d1))


def implied_vol(kind, premium, spot, strike, years, rate, dividend):
    if years <= 0: return None
    floor=bsm(kind,spot,strike,years,0,rate,dividend)
    ceiling=bsm(kind,spot,strike,years,5,rate,dividend)
    tolerance=1e-8*max(1.,spot,strike)
    if premium < floor-tolerance or premium > ceiling+tolerance:
        raise PortfolioError('Cannot infer IV from this premium under the model. Enter IV manually or check the price, stock price, rate, and dates.')
    if abs(premium-floor)<=tolerance: return 0.
    lo,hi=0.,5.
    for _ in range(70):
        mid=(lo+hi)/2
        if bsm(kind,spot,strike,years,mid,rate,dividend)<premium:lo=mid
        else:hi=mid
    return (lo+hi)/2


def greeks(kind,spot,strike,years,sigma,rate,dividend):
    keys=['delta','gamma','theta','vega','rho']
    if years<=0 or sigma<=0 or spot<=0:return dict.fromkeys(keys)
    root=math.sqrt(years); d1=(math.log(spot/strike)+(rate-dividend+sigma*sigma/2)*years)/(sigma*root);d2=d1-sigma*root
    density=math.exp(-d1*d1/2)/math.sqrt(2*math.pi)
    discount=math.exp(-dividend*years);strike_pv=strike*math.exp(-rate*years)
    sign=1 if kind=='call' else -1
    delta=sign*discount*cdf(sign*d1)
    theta=-spot*discount*density*sigma/(2*root)-sign*rate*strike_pv*cdf(sign*d2)+sign*dividend*spot*discount*cdf(sign*d1)
    return {'delta':delta,'gamma':discount*density/(spot*sigma*root),'theta':theta/365,
            'vega':spot*discount*density*root/100,'rho':sign*years*strike_pv*cdf(sign*d2)/100}


def units(leg):
    return leg.quantity*(leg.multiplier if leg.kind!='stock' else 1)*(1 if leg.side=='buy' else -1)


def expiry_summary(legs, fees):
    with localcontext() as ctx:
        ctx.prec=50
        dec=Decimal
        def pnl(s):
            total=-dec(str(fees))
            for leg in legs:
                value=s if leg.kind=='stock' else max(dec(0),s-dec(str(leg.strike)) if leg.kind=='call' else dec(str(leg.strike))-s)
                total+=dec(str(units(leg)))*(value-dec(str(leg.premium)))
            return total
        knots=sorted({dec(0),*[dec(str(l.strike)) for l in legs if l.kind!='stock']})
        tail=sum((dec(str(units(l))) for l in legs if l.kind in {'stock','call'}),dec(0))
        values=[pnl(s) for s in knots]
        roots,ranges=_zeros(knots,pnl,tail)
        return {'maximum_profit':None if tail>0 else float(max(dec(0),max(values))),
                'maximum_loss':None if tail<0 else float(max(dec(0),-min(values))),
                'best_case_pnl':None if tail>0 else float(max(values)),
                'worst_case_pnl':None if tail<0 else float(min(values)),
                'profit_unlimited':tail>0,'loss_unlimited':tail<0,
                'break_evens':[float(v) for v in roots],
                'break_even_ranges':[{'from':float(a),'to':None if b is None else float(b)} for a,b in ranges]},pnl


def probability_profit(spot,years,sigma,rate,dividend,summary,pnl):
    """Risk-neutral lognormal probability of nonnegative expiration P&L."""
    if years<=0:return float(pnl(Decimal(str(spot)))>=0)
    points=sorted({0.,*summary['break_evens'],*[v for r in summary['break_even_ranges'] for v in r.values() if v is not None]})
    def distribution(x):
        if x<=0:return 0.
        return cdf((math.log(x/spot)-(rate-dividend-sigma*sigma/2)*years)/(sigma*math.sqrt(years)))
    probability=0.
    for i,a in enumerate(points):
        b=points[i+1] if i+1<len(points) else None
        probe=(a+b)/2 if b is not None else max(a*2,a+spot+1)
        if pnl(Decimal(str(probe)))>=0:probability+=(1. if b is None else distribution(b))-distribution(a)
    return min(1.,max(0.,probability))


def prepare(req):
    option_legs=[l for l in req.legs if l.kind!='stock']
    if not option_legs:raise PortfolioError('Add at least one option leg.')
    if len(option_legs)>8 or len(req.legs)-len(option_legs)>1:raise PortfolioError('Use up to eight option legs and one stock position.')
    expirations={l.expiration for l in option_legs if l.expiration}
    if req.mode=='dated':
        if req.spot is None:raise PortfolioError('Enter the current underlying price for date-based estimates.')
        if any(l.expiration is None for l in option_legs):raise PortfolioError('Every option leg needs an expiration date for date-based estimates.')
        if any(l.expiration<req.as_of for l in option_legs):raise PortfolioError('Calculation date must be on or before every option expiration.')
        if any((l.expiration-req.as_of).days>3653 for l in option_legs):raise PortfolioError('Use expirations within ten years of the calculation date.')
        horizon=min(expirations)
        target=req.target_date or horizon
        if not req.as_of<=target<=horizon:raise PortfolioError('Scenario date must be between the calculation date and the earliest expiration. Later legs retain time value at the first expiration.')
    else:
        if len(expirations)>1:raise PortfolioError('Use date-based estimates for strategies with different expiration dates.')
        horizon=next(iter(expirations),None);target=horizon
    rate,dividend=req.rate/100,req.dividend_yield/100
    vols=[]; iv_sources=[]
    for l in req.legs:
        if l.kind=='stock' or req.mode=='expiry':vols.append(None);iv_sources.append(None);continue
        years=(l.expiration-req.as_of).days/365
        sigma=l.iv/100 if l.iv is not None else implied_vol(l.kind,l.premium,req.spot,l.strike,years,rate,dividend)
        effective=(sigma or 0)+req.iv_shift/100
        if effective<0 or effective>5:raise PortfolioError('Each leg’s IV after the shift must be between 0% and 500%.')
        vols.append(effective);iv_sources.append('Entered / selected IV' if l.iv is not None else 'Inferred from entry premium')
    fees=sum(l.quantity*req.fee_per_contract for l in option_legs)
    initial=sum(units(l)*l.premium for l in req.legs)+fees
    principal=req.borrowed_amount if req.financing_enabled else 0.
    if req.financing_enabled:
        if initial<=0 or principal>=initial:
            raise PortfolioError('Borrowing requires a positive net entry debit and a loan smaller than that debit, leaving positive own capital. Credit positions need a separate capital basis.')
        if req.capital_basis is not None or not req.include_stock_cost:
            raise PortfolioError('With borrowing enabled, use the full entry debit less the loan as own capital. Disable a custom return basis and include stock cost.')
        if req.mode=='expiry' and req.financing_days is None:
            raise PortfolioError('Enter holding days for borrowing costs in expiration-only mode.')
    def elapsed_days(day):
        return req.financing_days if req.mode=='expiry' else (day-req.as_of).days
    def interest(day):
        if not req.financing_enabled:return 0.
        return float(Decimal(str(principal))*Decimal(str(req.borrowing_rate))/100*Decimal(elapsed_days(day))/365)
    def values(spot,day):
        return [spot if l.kind=='stock' else bsm(l.kind,spot,l.strike,0 if req.mode=='expiry' else max(0,(l.expiration-day).days/365),vols[i] or 0,rate,dividend) for i,l in enumerate(req.legs)]
    def position_value(spot,day):return sum(units(l)*v for l,v in zip(req.legs,values(spot,day)))
    def evaluate(spot,day):return position_value(spot,day)-initial-interest(day)
    # Principal funds part of the entry debit; only interest is an extra expense.
    summary,exact=expiry_summary(req.legs,float(Decimal(str(fees))+Decimal(str(interest(horizon)))))
    common_expiry=len(expirations)<=1
    if req.mode=='dated' and not common_expiry:summary=None
    stock_cost=sum(units(l)*l.premium for l in req.legs if l.kind=='stock')
    if req.financing_enabled:basis=initial-principal;basis_label='Own capital (entry debit less loan)'
    elif req.capital_basis is not None:basis=req.capital_basis;basis_label='Entered capital basis'
    elif req.strategy=='cash_secured_put':
        basis=sum(l.strike*abs(units(l)) for l in option_legs if l.side=='sell' and l.kind=='put');basis=basis if basis>0 else None;basis_label='Cash collateral at strike'
    elif initial-(0 if req.include_stock_cost else stock_cost)>0:
        basis=initial-(0 if req.include_stock_cost else stock_cost);basis_label='Net debit including fees'+('' if req.include_stock_cost else ', stock cost excluded')
    elif summary and summary['maximum_loss'] and not summary['loss_unlimited']:
        basis=summary['maximum_loss'];basis_label='Maximum expiration loss'
    else:basis=None;basis_label='Enter capital basis to show percentage returns'
    return locals()


def leverage_metrics(req, prepared, details, delta):
    """Signed local price sensitivity divided by explicitly identified capital.

    Gross figures retain offsetting legs. Maximum loss is not inferred to be
    deposited capital for a credit position.
    """
    p=prepared
    if req.financing_enabled:
        capital=p['basis'];label='Own capital after borrowing'
    elif req.capital_basis is not None:
        capital=req.capital_basis;label='Entered capital basis'
    elif req.strategy=='cash_secured_put' and p['basis']:
        capital=p['basis'];label='Assumed cash collateral at strike'
    elif p['initial']>0:
        capital=p['initial'];label='Full net entry debit, including stock and fees'
    else:
        capital=None;label='Enter capital committed for credit positions'
    gross=req.spot*sum(abs(units(l)) for l in req.legs) if req.spot else None
    delta_notional=req.spot*delta if req.spot and delta is not None else None
    deltas=[l['greeks']['delta'] for l in details]
    gross_delta=req.spot*sum(abs(v) for v in deltas) if req.spot and all(v is not None for v in deltas) else None
    return {'capital':capital,'capital_label':label,'gross_notional':gross,
            'net_delta_notional':delta_notional,'gross_delta_notional':gross_delta,
            'effective_leverage':delta_notional/capital if delta_notional is not None and capital else None,
            'gross_delta_leverage':gross_delta/capital if gross_delta is not None and capital else None,
            'one_percent_move_pnl':delta_notional*.01 if delta_notional is not None else None}


def analyze_scenario(req):
    p=prepare(req);evaluate=p['evaluate'];summary=p['summary'];horizon=p['horizon'];target=p['target'];basis=p['basis']
    reference=req.spot or max(l.strike for l in p['option_legs'])
    lo=req.range_min if req.range_min is not None else max(0,reference*.7)
    hi=req.range_max if req.range_max is not None else reference*1.3
    if hi<=lo:raise PortfolioError('Chart maximum must exceed chart minimum.')
    scenario=req.scenario_price if req.scenario_price is not None else reference
    if req.mode=='dated':
        days=(horizon-req.as_of).days
        dates=sorted({req.as_of+timedelta(days=round(days*i/10)) for i in range(11)}|{target})
    else:dates=[horizon]
    prices=sorted({lo+(hi-lo)*i/120 for i in range(121)}|{s for s in [*[l.strike for l in p['option_legs']],scenario,*(summary['break_evens'] if summary else [])] if lo<=s<=hi})
    grid_prices=sorted({lo+(hi-lo)*i/20 for i in range(21)}|({scenario} if lo<=scenario<=hi else set()),reverse=True)
    date_key=lambda d:d.isoformat() if d else 'expiration'
    budget=req.comparison_budget or basis
    comparison_shares=budget/req.spot if budget and req.spot else None
    chart=[{'price':s,'pnl':evaluate(s,target),'horizon_pnl':evaluate(s,horizon),'start_pnl':evaluate(s,req.as_of) if req.mode=='dated' else evaluate(s,target),
            'position_value':p['position_value'](s,target),'horizon_position_value':p['position_value'](s,horizon),
            'start_position_value':p['position_value'](s,req.as_of) if req.mode=='dated' else p['position_value'](s,target),
            'return_percent':evaluate(s,target)/basis*100 if basis else None,
            'stock_pnl':comparison_shares*(s-req.spot) if comparison_shares else None} for s in prices]
    grid=[{'price':s,'values':[{'date':date_key(d),'pnl':evaluate(s,d),'position_value':p['position_value'](s,d),
                              'interest_cost':p['interest'](d),'equity_value':p['position_value'](s,d)-p['principal']-p['interest'](d) if req.financing_enabled else None,
                              'return_percent':evaluate(s,d)/basis*100 if basis else None} for d in dates]} for s in grid_prices]
    details=[]; totals=dict.fromkeys(['delta','gamma','theta','vega','rho'],0.)
    for i,l in enumerate(req.legs):
        value=p['values'](scenario,target)[i]
        g=({'delta':1.,'gamma':0.,'theta':0.,'vega':0.,'rho':0.} if l.kind=='stock' else
           greeks(l.kind,req.spot,l.strike,(l.expiration-req.as_of).days/365,p['vols'][i],p['rate'],p['dividend']) if req.mode=='dated' else dict.fromkeys(totals))
        scaled={k:v*units(l) if v is not None else None for k,v in g.items()}
        for k,v in scaled.items():totals[k]=totals[k]+v if totals[k] is not None and v is not None else None
        legfee=l.quantity*req.fee_per_contract if l.kind!='stock' else 0
        details.append({**l.model_dump(mode='json'),'units':units(l),'value_per_unit':value,'position_value':value*units(l),
                        'initial_cash_flow':-l.premium*units(l)-legfee,'pnl':(value-l.premium)*units(l)-legfee,
                        'effective_iv':p['vols'][i]*100 if p['vols'][i] is not None else None,'iv_source':p['iv_sources'][i],'greeks':scaled})
    pop=None
    if summary and req.mode=='dated':pop=probability_profit(req.spot,(horizon-req.as_of).days/365,req.probability_iv/100,p['rate'],p['dividend'],summary,p['exact'])
    warnings=[]
    if not summary:warnings.append('Different expirations: estimates stop at the first expiry and value remaining legs with the model. A single final payoff, maximum gain/loss, and probability of profit are not reported because later outcomes depend on the price path and settlement.')
    if summary and summary['loss_unlimited']:warnings.append('This position has unlimited potential loss as the underlying price rises.')
    if summary and summary['worst_case_pnl'] is not None and summary['worst_case_pnl']>0:warnings.append('The entered prices imply profit at every expiration price. Verify quotes and contract details; this does not establish an executable opportunity.')
    if summary and summary['best_case_pnl'] is not None and summary['best_case_pnl']<0:warnings.append('The entered prices imply a loss at every expiration price.')
    if req.mode=='dated':warnings.append('European Black–Scholes estimates assume constant volatility and continuous dividend yield. American exercise, discrete dividends, assignment, slippage and taxes are excluded. Only the optional fixed borrowing cost is modeled; no margin calls or forced liquidation.')
    financing={'enabled':req.financing_enabled,'principal':p['principal'],'annual_rate':req.borrowing_rate if req.financing_enabled else 0,
               'own_capital':p['initial']-p['principal'] if req.financing_enabled else None,
               'scenario_days':p['elapsed_days'](target) if req.financing_enabled else 0,
               'scenario_interest':p['interest'](target),'horizon_interest':p['interest'](horizon),
               'scenario_gross_pnl':evaluate(scenario,target)+p['interest'](target),
               'scenario_equity':p['position_value'](scenario,target)-p['principal']-p['interest'](target) if req.financing_enabled else None,
               'daily_interest':p['principal']*req.borrowing_rate/100/365 if req.financing_enabled else 0}
    return {'strategy':req.strategy,'symbol':req.symbol.upper(),'currency':req.currency,'mode':req.mode,'as_of':req.as_of.isoformat(),
            'target_date':date_key(target),'horizon':date_key(horizon),'summary':summary,'scenario_price':scenario,'scenario_pnl':evaluate(scenario,target),
            'scenario_return_percent':evaluate(scenario,target)/basis*100 if basis else None,'initial_debit':p['initial'],'fees':p['fees'],
            'capital_basis':basis,'basis_label':p['basis_label'],'comparison_budget':budget if comparison_shares else None,
            'probability_of_profit':pop,'probability_iv':req.probability_iv,'greeks':totals,'legs':details,'chart':chart,'grid':grid,
            'dates':[date_key(d) for d in dates],'range_min':lo,'range_max':hi,'warnings':warnings,
            'leverage':leverage_metrics(req,p,details,totals['delta']),'financing':financing}
