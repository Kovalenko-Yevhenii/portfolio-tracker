"""Synthetic covered-call research, never a historical option-quote backtest.

Prices use a business-time European BSM approximation. Stock observations,
pricing assumptions, accounting and option quote-provider contracts stay separate.
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

from backtesting import BacktestRequest, prepare_history, summarize, symbol
from options_pricing import bsm
from tracker import PortfolioError


class CoveredCallRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    source: Literal['market', 'demo'] = 'market'
    ticker: str = Field(default='AAPL', min_length=1, max_length=40)
    start: date
    end: date
    capital: float = Field(default=25000, ge=100, le=1e9)
    contracts: int = Field(default=1, ge=1, le=10000)
    tenor_sessions: int = Field(default=20, ge=2, le=126)
    otm_percent: float = Field(default=5, ge=0, le=50)
    strike_increment: float = Field(default=1, ge=.01, le=100)
    roll_before: int = Field(default=0, ge=0, le=30)
    volatility_mode: Literal['fixed', 'trailing'] = 'fixed'
    volatility_percent: float = Field(default=25, ge=0, le=200)
    volatility_window: int = Field(default=30, ge=2, le=250)
    volatility_premium: float = Field(default=5, ge=-50, le=100)
    rate_percent: float = Field(default=0, ge=-10, le=25)
    dividend_yield_percent: float = Field(default=0, ge=0, le=25)
    stock_fee_bps: float = Field(default=1, ge=0, le=100)
    stock_slippage_bps: float = Field(default=5, ge=0, le=500)
    option_fee: float = Field(default=.65, ge=0, le=100)
    option_half_spread_percent: float = Field(default=5, ge=0, le=25)
    assignment_fee: float = Field(default=0, ge=0, le=100)
    refresh: bool = False
    _ticker = field_validator('ticker')(symbol)

    @model_validator(mode='after')
    def validate_dates(self):
        if self.start < date(1990, 1, 1) or not 0 < (self.end-self.start).days <= 1827:
            raise ValueError('Choose a start from 1990 onward and an end after it, within five years.')
        if self.end >= datetime.now(ZoneInfo('America/New_York')).date():
            raise ValueError('Use an end date before today for completed stock sessions.')
        if self.roll_before >= self.tenor_sessions-1:
            raise ValueError('Early roll must leave at least one full session after opening; use 0 to hold to expiry.')
        if self.source == 'demo' and (self.ticker != 'DEMO-CC' or self.start < date(2024, 1, 2) or self.end > date(2025, 12, 31)):
            raise ValueError('The invented DEMO-CC example supports 2024-01-02 through 2025-12-31.')
        return self

    @property
    def risk_free_percent(self):
        # Reuse close-to-close performance metrics, with a disclosed 0% reference.
        return 0.


def demo_covered_history():
    dates = pd.bdate_range('2022-01-03', '2025-12-31')
    t = np.arange(len(dates), dtype=float)
    returns = .00025+.0035*np.sin(t/28)+.012*np.sin(t*1.73)+.005*np.cos(t*.37)
    close = 85*np.exp(np.cumsum(returns))
    opening = np.r_[85, close[:-1]]*np.exp(.004*np.sin(t*.79))
    return pd.DataFrame({'open': opening, 'close': close, 'distribution': 0., 'split': 0.}, index=dates)


def fetch_covered_history(req):
    import yfinance as yf
    start = req.start-timedelta(days=max(365, (req.volatility_window+1)*3+30))
    try:
        frame = yf.Ticker(req.ticker).history(start=start.isoformat(), end=(req.end+timedelta(days=1)).isoformat(),
            interval='1d', auto_adjust=False, back_adjust=False, actions=True, repair=False, keepna=True, timeout=20, raise_errors=True)
    except Exception as exc:
        raise PortfolioError('Stock history download failed. Check the ticker, dates and connection.') from exc
    if frame.empty or not {'Open', 'Close', 'Dividends', 'Stock Splits'} <= set(frame.columns):
        raise PortfolioError('Opening/closing prices and corporate-action history are required for this simulation.')
    return pd.DataFrame({'open': frame.Open, 'close': frame.Close,
        'distribution': frame.Dividends+frame.get('Capital Gains', 0), 'split': frame['Stock Splits']})


def prepare_covered_history(req, frame):
    if frame is None or not {'open', 'close', 'distribution', 'split'} <= set(frame.columns):
        raise PortfolioError('Stock history must include open, close, distribution and split observations.')
    warmup = req.volatility_window+1 if req.volatility_mode == 'trailing' else 2
    config = BacktestRequest(start=req.start, end=req.end, capital=req.capital,
        assets=[{'ticker': req.ticker, 'weight': 100}], benchmark=req.ticker, window=warmup)
    aligned, dates, count = prepare_history(config, {req.ticker: frame})
    if not aligned[req.ticker].ge(1e-6).all().all() or not aligned[req.ticker].le(1e7).all().all():
        raise PortfolioError('Use stock prices between 0.000001 and 10,000,000 on a consistent price scale.')
    extras = frame[['distribution', 'split']].copy()
    extras.index = pd.to_datetime(extras.index).tz_localize(None).normalize()
    extras = extras.reindex(aligned[req.ticker].index).apply(pd.to_numeric, errors='coerce')
    if not (np.isfinite(extras) & extras.ge(0)).all().all():
        raise PortfolioError('Missing or invalid corporate-action observations. No distributions were guessed.')
    if extras.loc[dates, 'split'].ne(0).any():
        raise PortfolioError('A stock split occurs in this period. Choose a split-free range; adjusted option deliverables are not modeled.')
    return aligned[req.ticker].join(extras), dates, count


def simulate_covered(req, frame, dates, covered=True, vol_shift=0., cost_scale=1.):
    units = req.contracts*100
    cash, shares, current = req.capital, 0, None
    daily, events, cycles = [], [], []
    total_fees = slippage_cost = premiums = dividends = 0.
    assignments = rolls = skipped = 0
    pending_stock = True
    vol_series = np.log(frame.close).diff().rolling(req.volatility_window).std(ddof=1).shift(1)*math.sqrt(252)*100
    spread = req.option_half_spread_percent/100*cost_scale
    stock_slip = req.stock_slippage_bps/10000*cost_scale
    stock_comm = req.stock_fee_bps/10000*cost_scale
    option_fee = req.option_fee*req.contracts*cost_scale

    def event(dt, kind, delta=0., fee=0., **details):
        events.append({'date': str(dt.date()), 'event': kind, 'cash_change': delta,
                       'fee': fee, 'cash_after': cash, 'shares_after': shares, **details})

    for i, dt in enumerate(dates):
        spot, opening = float(frame.close.loc[dt]), float(frame.open.loc[dt])
        loc = frame.index.get_loc(dt)
        previous_close = float(frame.close.iloc[loc-1])
        # Ex-date entitlement belongs to the previous holder, before today's orders.
        distribution = shares*float(frame.distribution.loc[dt])
        if distribution:
            cash += distribution;dividends += distribution
            event(dt, 'DISTRIBUTION', distribution, per_unit=float(frame.distribution.loc[dt]))
        if pending_stock:
            fill = opening*(1+stock_slip)
            fee = units*fill*stock_comm
            required = units*fill+fee
            if cash+1e-9 >= required:
                cash -= required;cash = max(cash, 0.);shares = units;pending_stock = False
                total_fees += fee;slippage_cost += units*(fill-opening)
                event(dt, 'BUY_STOCK', -required, fee, units=units, reference_price=opening, fill_price=fill)
            elif i == 0:
                raise PortfolioError(f'Starting capital must cover {units} stock units before option premium: at least ${required:,.2f} under these costs.')
            else:
                skipped += 1;event(dt, 'SKIP_STOCK', reason='Cash cannot fund the fixed stock position; no borrowing assumed.')
        if covered and shares == units and current is None:
            raw_vol = req.volatility_percent if req.volatility_mode == 'fixed' else float(vol_series.loc[dt])+req.volatility_premium
            if not math.isfinite(raw_vol):
                raise PortfolioError('Not enough prior closing returns to estimate the volatility proxy.')
            iv = min(300., max(0., raw_vol+vol_shift))
            # Strike is selected from the prior close, not from a future price.
            strike = math.ceil(previous_close*(1+req.otm_percent/100)/req.strike_increment-1e-12)*req.strike_increment
            expiry_i = i+req.tenor_sessions-1
            years = (req.tenor_sessions-.5)/252
            model = bsm('call', opening, strike, years, iv/100, req.rate_percent/100, req.dividend_yield_percent/100)
            bid = model*(1-spread)
            premium = units*bid
            if premium <= option_fee:
                skipped += 1;event(dt, 'SKIP_CALL', reason='Modeled premium does not cover the option fee.', model_price=model, assumed_iv=iv)
            else:
                cash += premium-option_fee;premiums += premium;total_fees += option_fee
                slippage_cost += units*(model-bid)
                current = {'cycle': len(cycles)+1, 'entry_date': str(dt.date()),
                    'expiry_date': str(dates[expiry_i].date()) if expiry_i < len(dates) else None,
                    'expiry_session': expiry_i, 'signal_date': str(frame.index[loc-1].date()),
                    'reference_close': previous_close, 'strike': strike, 'contracts': req.contracts,
                    'assumed_iv': iv, 'model_entry': model, 'fill_entry': bid,
                    'premium_received': premium, 'entry_fee': option_fee, 'status': 'OPEN', 'exit_date': None,
                    'exit_value': None, 'exit_fee': None, 'option_pnl': None}
                cycles.append(current)
                event(dt, 'SELL_CALL', premium-option_fee, option_fee, cycle=current['cycle'],
                      units=units, strike=strike, model_price=model, fill_price=bid, assumed_iv=iv)
        liability = 0.
        if covered and current is not None:
            remaining = current['expiry_session']-i
            model = bsm('call', spot, current['strike'], remaining/252, current['assumed_iv']/100,
                        req.rate_percent/100, req.dividend_yield_percent/100)
            if remaining == 0:
                intrinsic = max(spot-current['strike'], 0.)*units
                fee = req.assignment_fee*req.contracts*cost_scale if spot > current['strike'] else 0.
                if spot > current['strike']:
                    proceeds = units*current['strike']-fee
                    if cash+proceeds < 0:
                        raise PortfolioError('Assignment fees exceed available funds.')
                    cash += proceeds;shares = 0;pending_stock = True;assignments += 1;total_fees += fee
                    event(dt, 'ASSIGN', proceeds, fee, cycle=current['cycle'], units=units, strike=current['strike'], intrinsic_value=intrinsic)
                    current['status'] = 'ASSIGNED'
                else:
                    event(dt, 'EXPIRE', cycle=current['cycle'], strike=current['strike'])
                    current['status'] = 'EXPIRED'
                current.update(exit_date=str(dt.date()), exit_value=intrinsic, exit_fee=fee,
                    option_pnl=current['premium_received']-current['entry_fee']-intrinsic-fee)
                current = None
            elif req.roll_before and remaining == req.roll_before:
                ask = model*(1+spread)
                required = units*ask+option_fee
                if required <= cash:
                    cash -= required;total_fees += option_fee;slippage_cost += units*(ask-model);rolls += 1
                    event(dt, 'BUY_CALL_TO_ROLL', -required, option_fee, cycle=current['cycle'], model_price=model, fill_price=ask, units=units)
                    current.update(status='ROLLED', exit_date=str(dt.date()), exit_value=units*ask, exit_fee=option_fee,
                        option_pnl=current['premium_received']-current['entry_fee']-units*ask-option_fee)
                    current = None  # Replacement is written at the following session's open.
                else:
                    skipped += 1;event(dt, 'SKIP_ROLL', cycle=current['cycle'], reason='Insufficient cash to buy back the call; hold to expiry.')
                    liability = units*model
            else:
                liability = units*model
        value = cash+shares*spot-liability
        if cash < -1e-7 or not math.isfinite(value) or value <= 0 or shares not in (0, units):
            raise PortfolioError('The scenario exceeds the supported cash-account or numeric limits.')
        daily.append({'date': str(dt.date()), 'value': value, 'cash': cash, 'shares': shares,
            'stock_value': shares*spot, 'call_liability': liability,
            'exposure': shares*spot/value, 'spot': spot})
    # Keep the already shared backtest metric definitions; options accounting is separate.
    run = {'daily': daily, 'trades': []}
    metrics = summarize(req, run)
    metrics = {k:metrics[k] for k in ['ending_value','pnl','total_return','cagr','max_drawdown','volatility','sharpe']}
    metrics.update(premium_received=premiums, distributions=dividends, fees=total_fees,
        slippage_cost=slippage_cost, assignments=assignments, rolls=rolls, calls_written=len(cycles)*req.contracts,
        skipped_actions=skipped, ending_cash=cash, ending_shares=shares, ending_liability=daily[-1]['call_liability'])
    return {'summary': metrics, 'daily': daily, 'events': events, 'cycles': cycles}


def run_covered_simulation(req, history):
    frame, dates, warmup = prepare_covered_history(req, history)
    covered = simulate_covered(req, frame, dates)
    stock = simulate_covered(req, frame, dates, covered=False)
    sensitivity = []
    for shift in [-5., 0., 5.]:
        row = {'iv_shift_pp': shift, 'values': []}
        for scale in [0., 1., 2.]:
            try:
                result = covered if shift == 0 and scale == 1 else simulate_covered(req, frame, dates, vol_shift=shift, cost_scale=scale)
                row['values'].append({'cost_multiplier': scale, **result['summary'], 'error': None})
            except PortfolioError as exc:
                row['values'].append({'cost_multiplier': scale, 'ending_value': None, 'total_return': None, 'error': str(exc)})
        sensitivity.append(row)
    observations = [{'date': str(dt.date()), **{k:float(row[k]) for k in ['open','close','distribution','split']}} for dt,row in frame.iterrows()]
    digest = hashlib.sha256(json.dumps(observations,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return {'engine_version':1, 'result_type':'MODELED_OPTIONS_SIMULATION', 'option_price_source':'European BSM assumptions; no historical option quotes',
        'stock_price_basis':'Split-adjusted price scale; distributions credited separately',
        'settings':req.model_dump(mode='json',exclude={'refresh'}), 'start':str(dates[0].date()),'end':str(dates[-1].date()),
        'sessions':len(dates),'warmup_sessions':warmup,'observations':observations,'data_sha256':digest,
        'covered_call':covered,'stock_only':stock,'sensitivity':sensitivity,
        'warnings':[
            'MODELED OPTIONS: premiums, bid/ask fills, strikes, expirations and assignment are hypothetical. These are not actual expired contracts or proof of historical profitability.',
            'European BSM pricing with expiry-only assignment. Actual U.S. equity options can be assigned early, particularly around ex-dividend dates; that behavior is excluded.',
            'Each call covers 100 stock units on the provider price scale. Splits inside the test are rejected. A strike grid is assumed, not verified against listed contracts.',
            'Pricing uses a 252-session business-time clock: each open is half a session before its close. Weekends, holidays and overnight calendar interest are not modeled separately.',
            'Volatility is assumed at entry and frozen per call. A trailing estimate uses only returns ending before entry; it is a realized-volatility proxy, not observed implied volatility. Assumed volatility is bounded at 0–300%.',
            'Stock distributions are credited on ex-date to the previous holder, not on payment date. Pricing dividend yield is a separate constant user assumption, not inferred from future payments.',
            'Assignment delivers stock at strike; there is no second intrinsic cash debit. Rebuy the fixed stock position at the next open if cash permits. An early roll buys back at a modeled ask; its replacement opens next session.',
            'Ending stock and open calls are marked, not liquidated. Gross premium is not net profit: the short-call liability, stock losses and costs remain part of portfolio value.',
            'No leverage, cash interest, tax, liquidity limits, corporate-action deliverables or actual assignment lottery. Sharpe uses a 0% reference. Provider revisions, survivorship and dates missing from all observations remain limitations.',
            'Sensitivity shifts assumed volatility by −5/0/+5 percentage points and all cost settings by 0×/1×/2×. Paths can differ after assignment or cash constraints; cells are scenarios, not confidence intervals.',
        ] + (['OFFLINE EXAMPLE: DEMO-CC prices are invented weekday observations, including some market holidays.'] if req.source=='demo' else [])}
