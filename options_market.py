"""Read-only Yahoo option chains and bounded scenario-based option screening."""
from datetime import date, datetime, timezone
import math
import re
from typing import Literal
import yfinance as yf
from pydantic import Field
from tracker import PortfolioError
from options_pricing import Model, ScenarioRequest, OptionLeg, prepare, probability_profit


def symbol_key(symbol):
    value=symbol.strip().upper()
    if not re.fullmatch(r'[A-Z0-9^][A-Z0-9.^=-]{0,39}',value):raise PortfolioError('Enter a valid underlying ticker, such as AAPL or SPY.')
    return value


def finite(value, minimum=0):
    try:
        value=float(value)
        return value if math.isfinite(value) and value>=minimum else None
    except (ValueError,TypeError):return None


def expirations(symbol):
    symbol=symbol_key(symbol)
    try:values=list(yf.Ticker(symbol).options)
    except Exception:raise PortfolioError('Option expirations are unavailable from Yahoo right now. Retry or use manual legs.') from None
    if not values:raise PortfolioError('No option expirations were returned for this symbol. Check the ticker or use manual legs.')
    return {'symbol':symbol,'expirations':values,'fetched_at':datetime.now(timezone.utc).isoformat(),'source':'Yahoo Finance · delayed'}


def option_chain(symbol, expiration):
    symbol=symbol_key(symbol)
    try:
        result=yf.Ticker(symbol).option_chain(expiration)
        underlying=result.underlying or {}
        if str(underlying.get('symbol','')).upper()!=symbol:raise PortfolioError('The provider did not confirm the requested underlying. Use manual entry or retry.')
        currency=underlying.get('currency')
        if currency not in {'USD','CAD'}:raise PortfolioError('Option chains currently support underlying quotes in USD or CAD. No currency conversion is applied.')
        spot=finite(underlying.get('regularMarketPrice'))
        if spot is not None and spot<=0:spot=None
        rows=[]
        for kind,frame in [('call',result.calls),('put',result.puts)]:
            for raw in frame.to_dict('records'):
                strike=finite(raw.get('strike'));bid=finite(raw.get('bid'));ask=finite(raw.get('ask'))
                if not strike or not raw.get('contractSymbol'):continue
                valid=bid is not None and ask is not None and ask>=bid and ask>0
                size={'REGULAR':100,'MINI':10}.get(raw.get('contractSize'))
                traded=raw.get('lastTradeDate')
                rows.append({'kind':kind,'strike':strike,'expiration':expiration,'contract_symbol':str(raw['contractSymbol']),
                             'bid':bid,'ask':ask,'mid':(bid+ask)/2 if valid else None,'last':finite(raw.get('lastPrice')),
                             'iv':(finite(raw.get('impliedVolatility'))*100) if finite(raw.get('impliedVolatility')) is not None else None,
                             'volume':finite(raw.get('volume')),'open_interest':finite(raw.get('openInterest')),
                             'last_trade':traded.isoformat() if traded is not None and hasattr(traded,'isoformat') and str(traded)!='NaT' else None,
                             'multiplier':size,'currency':str(raw.get('currency') or currency),'valid_market':valid})
        if not rows:raise PortfolioError('No usable option contracts were returned for this expiration.')
        stamp=underlying.get('regularMarketTime')
        return {'symbol':symbol,'name':underlying.get('longName') or underlying.get('shortName') or symbol,'currency':currency,'spot':spot,
                'underlying_time':datetime.fromtimestamp(stamp,timezone.utc).isoformat() if stamp else None,
                'expiration':expiration,'contracts':rows,'fetched_at':datetime.now(timezone.utc).isoformat(),'source':'Yahoo Finance · delayed',
                'note':'Bid/ask and last trades may be stale. Retrieval time is not a quote timestamp. Midpoints are estimates, not executable prices. Verify adjusted contract deliverables before using a multiplier.'}
    except PortfolioError:raise
    except Exception:raise PortfolioError('The option chain could not be retrieved from Yahoo. Retry or enter contract details manually.') from None


class FinderRequest(Model):
    symbol: str = Field(min_length=1,max_length=40)
    expirations: list[date] = Field(min_length=1,max_length=4)
    target_date: date
    target_price: float = Field(ge=0,le=1_000_000)
    spot: float | None = Field(default=None,gt=0,le=1_000_000)
    types: list[Literal['long','short','debit_spread','credit_spread']] = Field(default_factory=lambda:['long'],min_length=1,max_length=4)
    option_type: Literal['both','call','put'] = 'both'
    max_risk: float | None = Field(default=None,gt=0,le=1e12)
    min_open_interest: int = Field(default=0,ge=0,le=1000000000)
    pricing: Literal['natural','mid'] = 'natural'
    rank: Literal['pnl','return'] = 'pnl'
    rate: float = Field(default=0,ge=-20,le=100)
    dividend_yield: float = Field(default=0,ge=0,le=100)
    iv_shift: float = Field(default=0,ge=-500,le=500)
    probability_iv: float = Field(default=30,gt=0,le=500)
    fee_per_contract: float = Field(default=0,ge=0,le=10000)


def find_options(req, chains):
    today=date.today()
    if req.target_date<today:raise PortfolioError('Choose a target date today or later.')
    candidates=[];examined=0;skipped=0;contract_count=0
    if not chains:raise PortfolioError('Load at least one option chain.')
    currency=chains[0]['currency']
    if any(c['currency']!=currency or c['symbol']!=symbol_key(req.symbol) for c in chains):raise PortfolioError('Finder chains must have the same underlying and currency.')
    spot=req.spot or chains[0]['spot']
    if not spot:raise PortfolioError('Enter the current underlying price before running the finder.')
    def price(row,side):return row['mid'] if req.pricing=='mid' else row['ask' if side=='buy' else 'bid']
    def leg(row,side):
        return OptionLeg(kind=row['kind'],side=side,strike=row['strike'],premium=price(row,side),expiration=row['expiration'],
                         multiplier=row['multiplier'],iv=row['iv'] if row['iv'] is not None and 0<row['iv']<=500 else None,contract_symbol=row['contract_symbol'])
    def consider(legs,kind):
        nonlocal examined,skipped
        examined+=1
        if any(l.premium<=0 for l in legs):skipped+=1;return
        model=ScenarioRequest(strategy=kind,symbol=req.symbol,currency=currency,mode='dated',legs=legs,spot=spot,as_of=today,target_date=req.target_date,
                              scenario_price=req.target_price,rate=req.rate,dividend_yield=req.dividend_yield,iv_shift=req.iv_shift,
                              probability_iv=req.probability_iv,fee_per_contract=req.fee_per_contract)
        try:p=prepare(model)
        except PortfolioError:skipped+=1;return
        if kind=='debit_spread' and p['initial']<=0:return
        if kind=='credit_spread' and p['initial']>=0:return
        summary=p['summary'];risk=summary['maximum_loss']
        if req.max_risk is not None and (risk is None or risk>req.max_risk):return
        pnl=p['evaluate'](req.target_price,req.target_date)
        percent=pnl/p['basis']*100 if p['basis'] else None
        if req.rank=='return' and percent is None:return
        pop=probability_profit(spot,(p['horizon']-today).days/365,req.probability_iv/100,p['rate'],p['dividend'],summary,p['exact'])
        candidates.append({'type':kind,'option_type':legs[0].kind,'expiration':str(legs[0].expiration),'legs':[l.model_dump(mode='json') for l in legs],
                           'pnl':pnl,'return_percent':percent,'capital_basis':p['basis'],'maximum_loss':risk,'maximum_profit':summary['maximum_profit'],
                           'probability_of_profit':pop,'initial_debit':p['initial'],'break_evens':summary['break_evens']})
    for chain in chains:
        if date.fromisoformat(chain['expiration'])<req.target_date:continue
        for kind in ['call','put']:
            if req.option_type not in {'both',kind}:continue
            eligible=[r for r in chain['contracts'] if r['kind']==kind and r['valid_market'] and r['multiplier'] is not None and r['currency']==currency
                      and (req.min_open_interest==0 or (r['open_interest'] is not None and r['open_interest']>=req.min_open_interest))]
            # Keep the local request bounded and report this restriction to the user.
            pool=sorted(eligible,key=lambda r:abs(r['strike']-(spot+req.target_price)/2))[:32]
            contract_count+=len(pool)
            for row in pool:
                if 'long' in req.types:consider([leg(row,'buy')],'long')
                if 'short' in req.types:consider([leg(row,'sell')],'short')
            spreads=set(req.types)&{'debit_spread','credit_spread'}
            if spreads:
                for buy in pool:
                    for sell in pool:
                        if buy['strike']==sell['strike'] or buy['multiplier']!=sell['multiplier']:continue
                        a,b=leg(buy,'buy'),leg(sell,'sell')
                        kind_spread='debit_spread' if a.premium>b.premium else 'credit_spread'
                        if kind_spread in spreads:consider([a,b],kind_spread)
    candidates.sort(key=lambda r:r['pnl'] if req.rank=='pnl' else r['return_percent'],reverse=True)
    return {'symbol':symbol_key(req.symbol),'currency':currency,'spot':spot,'target_date':str(req.target_date),'target_price':req.target_price,
            'results':candidates[:30],'eligible_results':len(candidates),'examined':examined,'skipped':skipped,'contracts_screened':contract_count,
            'pricing':req.pricing,'as_of':str(today),'fetched_at':[c['fetched_at'] for c in chains],
            'note':'Ranks one-contract positions only within the selected expirations and the nearest 32 usable strikes per option type to the midpoint of current and target prices. Results assume the entered target price/date and volatility; they are not forecasts. Maximum risk is the full expiration loss, not broker margin. Probability is a risk-neutral model estimate at expiration.'}
