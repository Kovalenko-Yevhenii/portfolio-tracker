"""Daily, long/cash backtests on adjusted-price units, with auditable execution.

The engine consumes supplied observations only. Market acquisition is separate;
the same engine runs deterministic fixtures without network access.
"""
from datetime import date, datetime, timedelta
import hashlib
import json
import math
from typing import Literal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tracker import PortfolioError


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


def symbol(value):
    value = value.strip().upper()
    if not value or not all(c.isascii() and (c.isalnum() or c in '.-^=') for c in value):
        raise ValueError('Enter an exact ticker using letters, numbers, dots or dashes.')
    return value


class Allocation(Input):
    ticker: str = Field(min_length=1, max_length=40)
    weight: float = Field(gt=0, le=100)
    _symbol = field_validator('ticker')(symbol)


class BacktestRequest(Input):
    source: Literal['market', 'demo'] = 'market'
    strategy: Literal['sma', 'buy_hold'] = 'sma'
    start: date
    end: date
    capital: float = Field(default=10000, ge=100, le=1e9)
    assets: list[Allocation] = Field(min_length=1, max_length=10)
    benchmark: str = Field(default='SPY', min_length=1, max_length=40)
    window: int = Field(default=50, ge=2, le=252)
    commission_bps: float = Field(default=0, ge=0, le=100)
    fee_per_order: float = Field(default=0, ge=0, le=1000)
    slippage_bps: float = Field(default=5, ge=0, le=500)
    risk_free_percent: float = Field(default=0, gt=-100, le=100)
    refresh: bool = False
    _benchmark = field_validator('benchmark')(symbol)

    @model_validator(mode='after')
    def check(self):
        if self.start < date(1990, 1, 1) or self.end <= self.start or (self.end-self.start).days > 3653:
            raise ValueError('Use dates from 1990 onward, with end after start and at most ten years per run.')
        if self.end >= datetime.now(ZoneInfo('America/New_York')).date():
            raise ValueError('End the test before today so it uses completed daily sessions.')
        if len({a.ticker for a in self.assets}) != len(self.assets):
            raise ValueError('Use each ticker only once.')
        if not math.isclose(sum(a.weight for a in self.assets), 100, abs_tol=1e-7, rel_tol=0):
            raise ValueError('Initial allocations must add to 100%.')
        if any(self.capital*a.weight/100 <= self.fee_per_order for a in self.assets):
            raise ValueError('Each initial allocation must exceed the fixed order fee.')
        if self.source == 'demo':
            if any(a.ticker not in {'DEMO-A', 'DEMO-B'} for a in self.assets) or self.benchmark != 'DEMO-MKT':
                raise ValueError('The offline example supports DEMO-A, DEMO-B and benchmark DEMO-MKT only.')
            if self.start < date(2024, 1, 2) or self.end > date(2025, 12, 31):
                raise ValueError('The offline example covers 2024-01-02 through 2025-12-31.')
        return self


def demo_history():
    """Invented, deterministic weekday observations; never labeled market data."""
    dates = pd.bdate_range('2022-01-03', '2025-12-31')
    t = np.arange(len(dates), dtype=float)
    result = {}
    for ticker, phase, drift, cycle in [('DEMO-A', 0, .00035, .0028), ('DEMO-B', 2, .00018, .0022), ('DEMO-MKT', 1, .00028, .0015)]:
        returns = drift + cycle*np.sin(t/24+phase) + .004*np.sin(t*1.73+phase)
        close = 100*np.exp(np.cumsum(returns))
        previous = np.r_[100, close[:-1]]
        opening = previous*np.exp(.0015*np.sin(t*.79+phase))
        result[ticker] = pd.DataFrame({'open': opening, 'close': close}, index=dates)
    return result


def prepare_history(req, history):
    """Reject incomplete rows instead of silently filling or compressing time."""
    symbols = list(dict.fromkeys([a.ticker for a in req.assets]+[req.benchmark]))
    frames = {}
    for ticker in symbols:
        frame = history.get(ticker)
        if frame is None or frame.empty or not {'open', 'close'} <= set(frame.columns):
            raise PortfolioError(f'No usable opening/closing history for {ticker}.')
        frame = frame[['open', 'close']].copy()
        try:
            frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
        except (ValueError, TypeError) as exc:
            raise PortfolioError(f'Invalid history dates for {ticker}.') from exc
        if frame.index.has_duplicates or frame.index.hasnans:
            raise PortfolioError(f'Duplicate or invalid history dates for {ticker}.')
        frames[ticker] = frame.sort_index().loc[:str(req.end)]
    all_dates = frames[symbols[0]].index
    for frame in frames.values():
        all_dates = all_dates.union(frame.index)
    dates = all_dates.sort_values()
    test = dates[(dates >= pd.Timestamp(req.start)) & (dates <= pd.Timestamp(req.end))]
    if len(test) < 2:
        raise PortfolioError('At least two completed sessions are required in the selected range.')
    # A weekend/holiday boundary is normal; larger truncations require a new range.
    if (test[0].date()-req.start).days > 7 or (req.end-test[-1].date()).days > 7:
        raise PortfolioError('History does not cover the requested date range. Choose dates with complete data.')
    warmup = dates[dates < test[0]][-req.window:] if req.strategy == 'sma' else dates[:0]
    if req.strategy == 'sma' and len(warmup) < req.window:
        raise PortfolioError(f'Need {req.window} prior sessions before the start date for the moving average.')
    needed = warmup.append(test)
    aligned = {}
    for ticker, frame in frames.items():
        values = frame.reindex(needed).apply(pd.to_numeric, errors='coerce')
        valid = (np.isfinite(values) & values.gt(0)).all(axis=1)
        if not valid.all():
            bad = values.index[~valid][0].date()
            raise PortfolioError(f'Missing or invalid opening/closing quote for {ticker} on {bad}. No prices were filled. Choose a common history or retry.')
        aligned[ticker] = values
    return aligned, test, len(warmup)


def simulate(req, frames, dates, assets, strategy):
    """Each initial allocation has its own cash account; profits stay in it."""
    sleeves = {a.ticker: {'cash': req.capital*a.weight/100, 'units': 0., 'entry_cost': 0.} for a in assets}
    averages = {a.ticker: frames[a.ticker].close.rolling(req.window).mean() for a in assets}
    fee_rate, slip = req.commission_bps/10000, req.slippage_bps/10000
    ledger, snapshots, skipped = [], [], []
    for day_number, dt in enumerate(dates):
        invested = cash = 0.
        for a in assets:
            ticker, account = a.ticker, sleeves[a.ticker]
            frame = frames[ticker]
            loc = frame.index.get_loc(dt)
            signal_date = frame.index[loc-1] if strategy == 'sma' else None
            prior_close = float(frame.close.iloc[loc-1]) if strategy == 'sma' else None
            average = float(averages[ticker].iloc[loc-1]) if strategy == 'sma' else None
            # Equality means cash. Today's close can never influence today's order.
            target = prior_close > average if strategy == 'sma' else True
            side = 'BUY' if target and account['units'] == 0 else 'SELL' if not target and account['units'] > 0 else None
            if side:
                opening = float(frame.open.loc[dt])
                fill = opening*(1+slip if side == 'BUY' else 1-slip)
                if side == 'BUY':
                    if account['cash'] <= req.fee_per_order:
                        skipped.append({'date': str(dt.date()), 'ticker': ticker, 'reason': 'Cash does not cover fixed order fee.'})
                        cash += account['cash']
                        continue
                    units = (account['cash']-req.fee_per_order)/(fill*(1+fee_rate))
                    notional = units*fill
                    commission = req.fee_per_order+notional*fee_rate
                    account['entry_cost'] = notional+commission
                    account['units'] = units
                    account['cash'] = 0.
                    closed_pnl = None
                else:
                    units = account['units']
                    notional = units*fill
                    commission = req.fee_per_order+notional*fee_rate
                    if notional < commission:
                        raise PortfolioError(f'The order fee exceeds sale proceeds for {ticker} on {dt.date()}. Reduce costs or increase capital.')
                    account['cash'] += notional-commission
                    account['units'] = 0.
                    closed_pnl = notional-commission-account['entry_cost']
                    account['entry_cost'] = 0.
                ledger.append({'date': str(dt.date()), 'ticker': ticker, 'side': side,
                    'signal_date': str(signal_date.date()) if signal_date is not None else None,
                    'signal_close': prior_close, 'signal_average': average,
                    'reason': 'Close above average' if strategy == 'sma' and target else 'Close at or below average' if strategy == 'sma' else 'Initial allocation',
                    'reference_open': opening, 'fill_price': fill, 'adjusted_units': units,
                    'notional': notional, 'commission': commission,
                    'slippage_cost': units*abs(fill-opening), 'cash_after': account['cash'], 'closed_pnl': closed_pnl})
            invested += account['units']*float(frame.close.loc[dt])
            cash += account['cash']
        value = cash+invested
        if not math.isfinite(value) or value <= 0:
            raise PortfolioError('Portfolio values exceed the reliable numeric range. Check prices and inputs.')
        snapshots.append({'date': str(dt.date()), 'value': value, 'cash': cash, 'exposure': invested/value})
    ending = [{'ticker': a.ticker, 'initial_weight': a.weight, **sleeves[a.ticker],
               'market_value': sleeves[a.ticker]['units']*float(frames[a.ticker].close.loc[dates[-1]])} for a in assets]
    return {'daily': snapshots, 'trades': ledger, 'ending_positions': ending, 'skipped_orders': skipped}


def summarize(req, run):
    values = np.array([d['value'] for d in run['daily']])
    # Initial opening capital is part of the high-water mark, including entry costs.
    peaks = np.maximum.accumulate(np.r_[req.capital, values])[1:]
    drawdowns = values/peaks-1
    for row, dd in zip(run['daily'], drawdowns):
        row['drawdown'] = float(dd)
    returns = values[1:]/values[:-1]-1
    sd = float(np.std(returns, ddof=1)) if len(returns) >= 2 else None
    rf = (1+req.risk_free_percent/100)**(1/252)-1
    days = (date.fromisoformat(run['daily'][-1]['date'])-date.fromisoformat(run['daily'][0]['date'])).days+1
    closed = [t['closed_pnl'] for t in run['trades'] if t['closed_pnl'] is not None]
    result = {'ending_value': float(values[-1]), 'pnl': float(values[-1]-req.capital),
        'total_return': float(values[-1]/req.capital-1),
        'cagr': float((values[-1]/req.capital)**(365.25/days)-1) if days >= 365 else None,
        'max_drawdown': float(drawdowns.min()), 'volatility': sd*math.sqrt(252) if sd is not None else None,
        'sharpe': float((np.mean(returns)-rf)/sd*math.sqrt(252)) if sd is not None and sd > 1e-12 else None,
        'orders': len(run['trades']), 'closed_trades': len(closed),
        'win_rate': sum(p > 0 for p in closed)/len(closed) if closed else None,
        'commissions': sum(t['commission'] for t in run['trades']),
        'slippage_cost': sum(t['slippage_cost'] for t in run['trades']),
        'average_exposure': float(np.mean([d['exposure'] for d in run['daily']]))}
    if any(isinstance(v, float) and not math.isfinite(v) for v in result.values() if v is not None):
        raise PortfolioError('Risk statistics exceed the reliable numeric range. Check the price history.')
    return result


def run_backtest(req, history):
    frames, dates, warmup = prepare_history(req, history)
    runs = {
        'strategy': simulate(req, frames, dates, req.assets, req.strategy),
        'buy_hold': simulate(req, frames, dates, req.assets, 'buy_hold'),
        'benchmark': simulate(req, frames, dates, [Allocation(ticker=req.benchmark, weight=100)], 'buy_hold')}
    for run in runs.values():
        run['summary'] = summarize(req, run)
    # Export the exact observations used, including warm-up, for reproducibility.
    observations = {ticker: [{'date': str(dt.date()), 'open': float(row.open), 'close': float(row.close)} for dt, row in f.iterrows()] for ticker, f in frames.items()}
    digest = hashlib.sha256(json.dumps(observations, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    warnings = ['Historical results are hypothetical. Repeatedly selecting the best rule on the same period can overfit; test a separate date range.',
        'Each ticker keeps its own initial allocation and profits. No transfers or rebalancing between tickers; idle cash earns 0%.',
        'Adjusted opening and closing prices model reinvested distributions. Quantities are synthetic adjusted units, not historical share counts or executable quotes.',
        'Positions still open on the final date are marked at closing value, without a closing sale or exit costs. Drawdowns use daily closes, not intraday lows.']
    if req.source == 'demo':
        warnings.insert(0, 'OFFLINE EXAMPLE: invented weekday prices, including some market holidays. These are not historical securities or investment evidence.')
    else:
        warnings.append('Yahoo history can be revised and is not point-in-time or survivorship-free. A chosen ticker basket can introduce selection bias; delisted securities may be unavailable. Missing quotes within the observed date union stop the test; sessions missing from every series cannot be detected.')
    if any(run['summary']['cagr'] is None for run in runs.values()):
        warnings.append('CAGR is shown only for periods of at least one calendar year. Risk statistics use close-to-close returns, excluding the first partial session, with 252 sessions/year.')
    if runs['strategy']['skipped_orders']:
        warnings.append(f"{len(runs['strategy']['skipped_orders'])} entry orders were skipped because cash could not cover the fixed fee.")
    return {'engine_version': 1, 'currency': 'USD', 'settings': req.model_dump(mode='json', exclude={'refresh'}),
        'start': str(dates[0].date()), 'end': str(dates[-1].date()), 'sessions': len(dates), 'warmup_sessions': warmup,
        'price_basis': 'Adjusted OHLC total-return proxy', 'execution': 'Previous close signal → next observed session open',
        'data_sha256': digest, 'observations': observations, 'runs': runs, 'warnings': warnings}


def fetch_backtest_history(req):
    """Fetch an inclusive date range plus warm-up. API layer serializes/cache calls."""
    import yfinance as yf
    start = req.start-timedelta(days=max(365, req.window*3+30))
    result = {}
    for ticker in dict.fromkeys([a.ticker for a in req.assets]+[req.benchmark]):
        try:
            frame = yf.Ticker(ticker).history(start=start.isoformat(), end=(req.end+timedelta(days=1)).isoformat(),
                interval='1d', auto_adjust=True, back_adjust=False, actions=False, repair=False, keepna=True, timeout=20, raise_errors=True)
        except Exception as exc:
            raise PortfolioError(f'Could not download history for {ticker}. Check the ticker, dates and connection, then retry.') from exc
        result[ticker] = frame.rename(columns={'Open': 'open', 'Close': 'close'})
    return result
