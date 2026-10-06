"""Fixed-unit USD crypto spot research on complete UTC daily closes."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import yfinance as yf
from tracker import PortfolioError
from options_market import symbol_key


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class CryptoHolding(Model):
    ticker: str = Field(min_length=1, max_length=40)
    quantity: float = Field(gt=0, le=1e12)
    avg_cost: float | None = Field(default=None, ge=0, le=1e10)

    @field_validator('ticker')
    @classmethod
    def ticker_key(cls, value):
        return symbol_key(value)


class CryptoRequest(Model):
    source: Literal['demo','market'] = 'demo'
    holdings: list[CryptoHolding] = Field(min_length=1, max_length=10)
    cash: float = Field(default=0, ge=0, le=1e12)
    benchmark: str = Field(default='BTC-USD', min_length=1, max_length=40)
    start: date
    end: date
    risk_free_percent: float = Field(default=0, gt=-100, le=100)
    refresh: bool = False

    @field_validator('benchmark')
    @classmethod
    def benchmark_key(cls, value):
        return symbol_key(value)

    @model_validator(mode='after')
    def dates_and_holdings(self):
        if not date(1990,1,1)<=self.start<self.end<datetime.now(timezone.utc).date() or (self.end-self.start).days>1827:
            raise ValueError('Choose at least two completed UTC dates, within a five-year period.')
        if len({h.ticker for h in self.holdings})!=len(self.holdings):
            raise ValueError('Combine duplicate crypto holdings into one row.')
        return self


def demo_crypto():
    dates=pd.date_range('2024-01-01','2025-12-31')
    n=np.arange(len(dates))
    return {ticker:pd.Series(base*np.exp(.0004*n+.08*np.sin(n/frequency)),index=dates)
            for ticker,base,frequency in [('DEMO-BTC',40000,23),('DEMO-ETH',2200,17)]}


def fetch_crypto(req):
    history, identities = {}, []
    for symbol in dict.fromkeys([h.ticker for h in req.holdings]+[req.benchmark]):
        ticker=yf.Ticker(symbol)
        try:
            info=ticker.get_info()
            if info.get('quoteType')!='CRYPTOCURRENCY' or info.get('currency')!='USD' or info.get('symbol','').upper()!=symbol:
                raise PortfolioError(f'{symbol}: choose a verified USD cryptocurrency spot ticker, such as BTC-USD.')
            frame=ticker.history(start=req.start.isoformat(),end=(req.end+timedelta(days=1)).isoformat(),
                                 interval='1d',auto_adjust=False,back_adjust=False,repair=False,actions=False,keepna=True)
            if frame.empty or 'Close' not in frame:
                raise PortfolioError(f'{symbol}: no daily closing prices returned.')
            series=frame['Close'].copy()
            index=pd.DatetimeIndex(series.index)
            if index.tz is not None:
                index=index.tz_convert('UTC').tz_localize(None)
            if not index.equals(index.normalize()):
                raise PortfolioError(f'{symbol}: provider candles are not dated at UTC midnight.')
            series.index=index
            history[symbol]=series
            identities.append(dict(ticker=symbol,name=info.get('shortName',symbol),currency='USD',type='CRYPTOCURRENCY'))
        except PortfolioError:
            raise
        except Exception as exc:
            raise PortfolioError(f'{symbol}: crypto data is unavailable. Try again or use the offline example.') from exc
    return history,identities


def crypto_analysis(req, history):
    expected=pd.date_range(req.start,req.end,freq='D')
    prices={}
    for ticker in dict.fromkeys([h.ticker for h in req.holdings]+[req.benchmark]):
        if ticker not in history:
            raise PortfolioError(f'Missing history for {ticker}.')
        series=history[ticker].copy()
        try:
            series.index=pd.to_datetime(series.index)
            if series.index.tz is not None or series.index.has_duplicates or not series.index.equals(series.index.normalize()):
                raise ValueError('ambiguous dates')
            series=series.reindex(expected).astype(float)
        except (ValueError,TypeError) as exc:
            raise PortfolioError(f'{ticker}: invalid or duplicate daily dates.') from exc
        if not np.isfinite(series).all() or (series<=0).any() or (series>1e10).any():
            raise PortfolioError(f'{ticker}: missing or invalid UTC daily close. No days are filled or dropped.')
        prices[ticker]=series
    value=sum((prices[h.ticker]*h.quantity for h in req.holdings),start=pd.Series(req.cash,index=expected))
    benchmark=value.iloc[0]*prices[req.benchmark]/prices[req.benchmark].iloc[0]
    returns=value.pct_change(fill_method=None).iloc[1:]
    std=float(returns.std(ddof=1)) if len(returns)>1 else None
    annual_rf=(1+req.risk_free_percent/100)**(1/365)-1
    days=(req.end-req.start).days
    holdings=[]
    for h in req.holdings:
        last=float(prices[h.ticker].iloc[-1]); amount=last*h.quantity
        holdings.append(dict(ticker=h.ticker,quantity=h.quantity,price=last,value=amount,weight=amount/value.iloc[-1],
                             cost_basis=None if h.avg_cost is None else h.quantity*h.avg_cost,
                             unrealized_pnl=None if h.avg_cost is None else h.quantity*(last-h.avg_cost)))
    observations={ticker:[dict(date=d.date().isoformat(),close=float(p)) for d,p in s.items()] for ticker,s in prices.items()}
    fingerprint=hashlib.sha256(json.dumps(observations,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return dict(model_version=1,result_type='fixed_unit_crypto_history',settings=req.model_dump(mode='json'),
                summary=dict(initial_value=float(value.iloc[0]),ending_value=float(value.iloc[-1]),
                             period_pnl=float(value.iloc[-1]-value.iloc[0]),total_return=float(value.iloc[-1]/value.iloc[0]-1),
                             max_drawdown=float((value/value.cummax()-1).min()),
                             annual_volatility=None if std is None else std*math.sqrt(365),
                             sharpe=None if std is None or std<=1e-15 else float((returns.mean()-annual_rf)/std*math.sqrt(365)),
                             cagr=float((value.iloc[-1]/value.iloc[0])**(365/days)-1) if days>=365 else None,
                             cash=req.cash,annualization=365),holdings=holdings,
                daily=[dict(date=d.date().isoformat(),value=float(value[d]),benchmark=float(benchmark[d]),
                            drawdown=float(value[d]/value.loc[:d].max()-1)) for d in expected],
                observations=observations,data_sha256=fingerprint,
                notes=['Invented offline prices.' if req.source=='demo' else 'Yahoo Finance daily candles, completed UTC dates; data can be revised.',
                       'The same quantities and cash are held throughout the selected history. This is a hypothetical fixed-holdings view, not your transaction history.',
                       'Average purchase cost affects unrealized P&L only. Period return starts at the first selected close; no purchase date is inferred.',
                       'Volatility and Sharpe use sample daily returns and 365 days/year. Cash earns zero. The benchmark starts at the same value, fully invested.',
                       'Spot only: no fees, staking, lending, forks, airdrops, perpetual funding, derivatives, borrowing or tax accounting. USD pairs only.'])
