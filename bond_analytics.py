"""Regular, non-callable fixed-rate bullet bonds. All inputs are user supplied."""
from calendar import monthrange
from datetime import date
import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from tracker import PortfolioError


class BondRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    name: str = Field(default='', max_length=100)
    hypothesis: str = Field(default='', max_length=3000)
    issuer_type: Literal['government', 'corporate'] = 'government'
    currency: Literal['USD','CAD','EUR','GBP'] = 'USD'
    settlement: date
    maturity: date
    face_amount: float = Field(gt=0, le=1e12)
    coupon_rate: float = Field(ge=0, le=100)
    frequency: Literal[1,2,4] = 2
    day_count: Literal['actual_actual','30u360'] = 'actual_actual'
    date_roll: Literal['maturity_day','month_end'] = 'maturity_day'
    discounting: Literal['compound','simple_final'] = 'compound'
    mode: Literal['price','yield','spread'] = 'price'
    yield_percent: float | None = Field(default=None, ge=-20, le=100)
    benchmark_yield: float | None = Field(default=None, ge=-20, le=100)
    spread_bps: float | None = Field(default=None, ge=-2000, le=10000)
    market_clean: float | None = Field(default=None, gt=0, le=10000)

    @model_validator(mode='after')
    def conventions(self):
        if self.settlement.year < 1901 or not 0 < (self.maturity-self.settlement).days <= 36525:
            raise ValueError('Settlement must be from 1901 onward, before maturity, and within 100 years of maturity.')
        if self.date_roll == 'month_end' and self.maturity.day != monthrange(self.maturity.year,self.maturity.month)[1]:
            raise ValueError('End-of-month schedules require a maturity date at month end.')
        if self.mode == 'price' and self.yield_percent is None:
            raise ValueError('Enter the annual yield to calculate a price.')
        if self.mode == 'yield' and self.market_clean is None:
            raise ValueError('Enter a clean market price per 100 to solve for yield.')
        if self.mode == 'spread':
            if self.benchmark_yield is None or self.spread_bps is None:
                raise ValueError('Enter both a benchmark yield and a spread in basis points.')
            if not -20 <= self.benchmark_yield+self.spread_bps/100 <= 100:
                raise ValueError('The combined benchmark plus spread yield must be between −20% and 100%.')
        return self


def coupon_date(maturity, months_back, roll):
    """Anchor every date to maturity, avoiding drift after February clipping."""
    month_number=maturity.year*12+maturity.month-1-months_back
    year,month=divmod(month_number,12);month+=1
    last=monthrange(year,month)[1]
    return date(year,month,last if roll=='month_end' else min(maturity.day,last))


def us_30_360(start, end):
    """US 30/360 including the February-end adjustments (QuantLib USA basis)."""
    d1,d2=start.day,end.day
    feb1=start.month==2 and d1==monthrange(start.year,2)[1]
    feb2=end.month==2 and d2==monthrange(end.year,2)[1]
    if feb1:
        if feb2:d2=30
        d1=30
    if d1==31:d1=30
    if d2==31 and d1>=30:d2=30
    return 360*(end.year-start.year)+30*(end.month-start.month)+d2-d1


def schedule(req):
    remaining=[];months=12//req.frequency
    for i in range(405):
        payment=coupon_date(req.maturity,i*months,req.date_roll)
        if payment<=req.settlement:
            previous=payment;break
        remaining.append(payment)
    else:raise PortfolioError('The coupon schedule exceeds the supported horizon.')
    remaining.reverse();next_coupon=remaining[0]
    if req.day_count=='actual_actual':
        elapsed=(req.settlement-previous).days;period=(next_coupon-previous).days
    else:
        elapsed=us_30_360(previous,req.settlement);period=360/req.frequency
    accrued_fraction=elapsed/period
    if not 0 <= accrued_fraction <= 1:
        raise PortfolioError('These dates do not form a supported regular coupon period under the selected day count.')
    return dict(previous=previous,next=next_coupon,dates=remaining,elapsed_days=elapsed,
                period_days=period,accrued_fraction=accrued_fraction,remaining_fraction=1-accrued_fraction)


def cashflows(req, sched):
    coupon=req.coupon_rate/req.frequency
    return [dict(date=d.isoformat(),periods=sched['remaining_fraction']+i,coupon=coupon,
                 principal=100. if d==req.maturity else 0.,amount=coupon+(100. if d==req.maturity else 0.))
            for i,d in enumerate(sched['dates'])]


def present_value(flows, y, frequency, simple_final=False):
    """y is annual decimal yield; return dirty price and exact yield derivatives."""
    if y <= -frequency:raise PortfolioError('Yield must keep the periodic discount base positive.')
    simple=simple_final and len(flows)==1
    base=1+y/frequency;rows=[]
    for row in flows:
        periods=row['periods'];years=periods/frequency
        factor=1/(1+y*years) if simple else math.exp(-periods*math.log1p(y/frequency))
        pv=row['amount']*factor
        d1=-years*factor*pv if simple else -years/base*pv
        d2=2*years*years*factor*factor*pv if simple else years*(years+1/frequency)/(base*base)*pv
        rows.append({**row,'years':years,'discount_factor':factor,'pv':pv,'d1':d1,'d2':d2})
    dirty=math.fsum(row['pv'] for row in rows)
    return dict(dirty=dirty,modified_duration=-math.fsum(row['d1'] for row in rows)/dirty,
                macaulay_duration=math.fsum(row['years']*row['pv'] for row in rows)/dirty,
                convexity=math.fsum(row['d2'] for row in rows)/dirty,rows=rows,simple_final_used=simple)


def solve_yield(flows, dirty, frequency, simple):
    # A bounded, monotonic root; preserve a failure as unavailable, never a guessed yield.
    if flows[-1]['periods']<=0:
        raise PortfolioError('The selected day count leaves zero discount time. A unique yield cannot be inferred from this price.')
    lo,hi=-.20,1.
    fn=lambda y:present_value(flows,y,frequency,simple)['dirty']
    if not fn(hi)<=dirty<=fn(lo):
        raise PortfolioError('No yield solution within the supported −20% to 100% annual range. Check the clean price, dates and conventions.')
    for _ in range(90):
        mid=(lo+hi)/2
        if fn(mid)>dirty:lo=mid
        else:hi=mid
    y=(lo+hi)/2;residual=fn(y)-dirty
    if abs(residual)>1e-8*max(1,dirty):raise PortfolioError('Yield solver could not reproduce the entered price accurately.')
    return y,residual


def analyze_bond(req):
    sched=schedule(req);flows=cashflows(req,sched);simple=req.discounting=='simple_final'
    accrued=req.coupon_rate/req.frequency*sched['accrued_fraction'];scale=req.face_amount/100
    warnings=[];market_yield=None;residual=None
    if flows[-1]['periods']<=0:
        warnings.append('The selected 30/360 convention leaves zero discount time before the final payment. Its value is undiscounted and a unique market yield is unavailable.')
    if req.market_clean is not None:
        try:market_yield,residual=solve_yield(flows,req.market_clean+accrued,req.frequency,simple)
        except PortfolioError as exc:
            if req.mode=='yield':raise
            warnings.append(str(exc))
    y=market_yield if req.mode=='yield' else (req.benchmark_yield+req.spread_bps/100)/100 if req.mode=='spread' else req.yield_percent/100
    priced=present_value(flows,y,req.frequency,simple);dirty=priced['dirty'];clean=dirty-accrued
    dv01=priced['modified_duration']*dirty*.0001*scale
    shocks=[]
    for bps in [-200,-100,-50,0,50,100,200]:
        shift=bps/10000;p=present_value(flows,y+shift,req.frequency,simple)
        change=(p['dirty']-dirty)*scale
        approx=dirty*scale*(-priced['modified_duration']*shift+.5*priced['convexity']*shift*shift)
        shocks.append(dict(shift_bps=bps,yield_percent=(y+shift)*100,clean_price=p['dirty']-accrued,
                           dirty_price=p['dirty'],position_value=p['dirty']*scale,change=change,
                           change_percent=(p['dirty']/dirty-1)*100,approx_change=approx))
    spread_grid=None
    if req.mode=='spread':
        cols=[req.spread_bps+s for s in [-100,-50,0,50,100]]
        spread_grid=dict(columns=cols,rows=[dict(benchmark=b,values=[
            present_value(flows,(b+s/100)/100,req.frequency,simple)['dirty']-accrued for s in cols])
            for b in [req.benchmark_yield+s for s in [-1,-.5,0,.5,1]]])
    if req.coupon_rate==0:warnings.append('Zero coupon: no accrued coupon interest. Yield still uses the selected payment frequency and fractional-period convention, not a Treasury-bill discount quote.')
    if req.issuer_type=='corporate':warnings.append('Cash flows assume every payment is made. A spread adjusts the discount yield; this is not a default-probability, recovery or liquidity model.')
    if len(flows)==1 and not simple:warnings.append('Only one payment remains. Fractional compounding is selected; some bond markets instead use simple interest in the final coupon period.')
    if any(s<0 for s in (spread_grid or {}).get('columns',[])):warnings.append('The spread grid includes negative spreads as hypothetical shocks, not a claim about market quotes.')
    annual_coupon=req.face_amount*req.coupon_rate/100
    return dict(model='Regular fixed-rate bullet bond',model_version=1,name=req.name,currency=req.currency,
                issuer_type=req.issuer_type,settlement=req.settlement.isoformat(),maturity=req.maturity.isoformat(),
                clean_price=clean,dirty_price=dirty,accrued_per_100=accrued,yield_percent=y*100,
                effective_annual_yield=((1+y/req.frequency)**req.frequency-1)*100,
                clean_value=clean*scale,settlement_value=dirty*scale,accrued_amount=accrued*scale,
                annual_coupon=annual_coupon,coupon_payment=annual_coupon/req.frequency,
                current_yield=req.coupon_rate/clean*100 if clean>0 else None,
                macaulay_duration=priced['macaulay_duration'],modified_duration=priced['modified_duration'],
                convexity=priced['convexity'],dv01=dv01,
                market_yield_percent=None if market_yield is None else market_yield*100,
                market_gap=None if req.market_clean is None else req.market_clean-clean,
                market_settlement_value=None if req.market_clean is None else (req.market_clean+accrued)*scale,
                yield_solver_residual=residual,
                audit=dict(previous_coupon=sched['previous'].isoformat(),next_coupon=sched['next'].isoformat(),
                           remaining_payments=len(flows),elapsed_days=sched['elapsed_days'],period_days=sched['period_days'],
                           accrued_fraction=sched['accrued_fraction'],remaining_fraction=sched['remaining_fraction'],
                           frequency=req.frequency,day_count=req.day_count,date_roll=req.date_roll,
                           discounting=req.discounting,simple_final_used=priced['simple_final_used'],
                           periodic_yield_percent=y/req.frequency*100,redemption_per_100=100),
                cashflows=[dict(date=row['date'],periods=row['periods'],years=row['years'],coupon_per_100=row['coupon'],
                               principal_per_100=row['principal'],position_cashflow=row['amount']*scale,
                               discount_factor=row['discount_factor'],present_value=row['pv']*scale) for row in priced['rows']],
                shocks=shocks,spread_grid=spread_grid,warnings=warnings)
