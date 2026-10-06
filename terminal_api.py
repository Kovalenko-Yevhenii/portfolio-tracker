"""Local React dashboard adapter. All financial math stays in the shared engine."""
from collections import OrderedDict
from copy import deepcopy
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Literal
import json
import logging
import math
from uuid import UUID

import numpy as np
import pandas as pd
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from tracker import (PortfolioError, normalize_positions, load_positions, fetch_price_history,
                     get_instrument, search_instruments, compute_metrics, compare_history,
                     validate_adjusted_prices, validate_cash)
from portfolio_analysis import allocations_to_positions, diversification_analysis
from portfolio_store import store as portfolio_store, SavePortfolio, StoreError
from options_analysis import analyze_options
from options_pricing import ScenarioRequest, analyze_scenario
from options_market import FinderRequest, expirations, option_chain, find_options, symbol_key
from analytics_valuation import ValuationRequest, analyze_valuation
from derivatives_pricing import OptionPricingRequest, FuturesPricingRequest, price_option, price_futures
from bond_analytics import BondRequest, analyze_bond
from backtesting import BacktestRequest, run_backtest, fetch_backtest_history, demo_history
from covered_call_simulation import CoveredCallRequest, run_covered_simulation, fetch_covered_history, demo_covered_history
from volatility_surface import SurfaceRequest, build_surface, demo_chains
from crypto_portfolio import CryptoRequest, crypto_analysis, fetch_crypto, demo_crypto


class InputModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class AllocationRequest(InputModel):
    total_invested: float = Field(default=10000, gt=0)
    allocation_unit: Literal['percent', 'dollars'] = 'percent'
    allocations: list[dict] = Field(default_factory=list, max_length=200)


class AnalysisRequest(AllocationRequest):
    mode: Literal['holdings', 'research'] = 'holdings'
    source: Literal['quantity', 'allocation', 'csv'] = 'quantity'
    positions: list[dict] = Field(default_factory=list, max_length=200)
    tickers: list[str] = Field(default_factory=list, max_length=200)
    cash_balance: float = Field(default=0, ge=0)
    benchmark: str = Field(default='SPY', min_length=1, max_length=40)
    period: Literal['6mo', '1y', '2y', '5y', 'max'] = '1y'
    interval: Literal['1d', '1wk', '1mo'] = '1d'
    window: int = Field(default=30, ge=2, le=252)
    return_basis: Literal['price', 'total'] = 'price'
    annual_risk_free_rate: float = Field(default=0, gt=-1)
    refresh: bool = False


class CsvRequest(InputModel):
    text: str = Field(max_length=2_000_000)


class OptionsRequest(InputModel):
    strategy: Literal['long_call','long_put','covered_call','protective_put','vertical']
    symbol: str = Field(default='',max_length=40)
    expiration: str = Field(default='',max_length=100)
    contracts: int = Field(default=1,gt=0,le=1_000_000)
    multiplier: int = Field(default=100,gt=0,le=1_000_000)
    strike: float | None = None
    premium: float | None = None
    stock_entry: float | None = None
    option_type: Literal['call','put'] = 'call'
    long_strike: float | None = None
    long_premium: float | None = None
    short_strike: float | None = None
    short_premium: float | None = None
    range_min: float = 0
    range_max: float | None = None
    scenario_price: float | None = None


class MarketCache:
    """Bounded TTL cache; copies prevent callers changing cached pandas frames.

    Serialize provider calls because yfinance download uses shared process state.
    Cache market data only, never portfolio inputs or calculated account results.
    """
    def __init__(self):
        self.entries = OrderedDict()
        self.lock = RLock()

    def get(self, key, ttl, fetch):
        with self.lock:
            now = monotonic()
            cached = self.entries.get(key)
            if cached and now - cached[0] < ttl:
                self.entries.move_to_end(key)
                return deepcopy(cached[1])
            value = fetch()
            self.entries[key] = (monotonic(), deepcopy(value))
            self.entries.move_to_end(key)
            while len(self.entries) > 128:
                self.entries.popitem(last=False)
            return value

    def clear(self):
        with self.lock:
            self.entries.clear()


market_cache = MarketCache()


def instrument(symbol):
    return market_cache.get(('identity', symbol), 3600, lambda: get_instrument(symbol))


def table(frame):
    # pandas writes missing/undefined values as JSON null, not zero or NaN tokens.
    result = json.loads(frame.to_json(orient='split', date_format='iso', double_precision=15))
    result['index'] = [str(i) for i in frame.index]
    return result


def clean(value):
    if isinstance(value, pd.DataFrame):
        return table(value)
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def allocation_preview(req):
    entries = pd.DataFrame(req.allocations, columns=['ticker', 'allocation', 'purchase_price'])
    return allocations_to_positions(req.total_invested, entries, req.allocation_unit)


def build_analysis(req):
    cash = validate_cash(req.cash_balance)
    positions = pd.DataFrame(columns=['ticker', 'qty', 'avg_cost', 'currency'])
    preview = None
    if req.mode == 'holdings':
        if req.source == 'allocation':
            positions, cash, preview = allocation_preview(req)
        elif req.positions:
            positions = normalize_positions(pd.DataFrame(req.positions))
        if positions.empty and cash <= 0:
            raise PortfolioError('Add a holding or a positive cash balance.')
        tickers = positions.ticker.tolist()
    else:
        tickers = list(dict.fromkeys(t.strip().upper() for t in req.tickers))
        if not tickers or any(not t for t in tickers):
            raise PortfolioError('Select at least one ticker to research.')
    benchmark = req.benchmark.strip().upper()
    if not benchmark:
        raise PortfolioError('Enter a benchmark ticker, such as SPY.')
    unique = list(dict.fromkeys([*tickers, benchmark]))
    if req.refresh:
        market_cache.clear()
    identities = [instrument(t) for t in unique]
    adjusted = req.return_basis == 'total'
    def fetch():
        frames = fetch_price_history(unique, req.period, req.interval, include_adjusted=adjusted)
        return frames, datetime.now(timezone.utc).isoformat()
    frames, fetched_at = market_cache.get(('history', tuple(unique), req.period, req.interval, adjusted), 900, fetch)
    prices, dividends = frames[:2]
    adjusted_prices = frames[2] if adjusted else None
    performance = (validate_adjusted_prices(pd.DataFrame({'ticker': unique}), adjusted_prices)
                   .reindex(prices.index).where(prices.notna())) if adjusted else prices
    metrics = history = diversification = enriched = None
    if req.mode == 'holdings':
        enriched, history, metrics = compute_metrics(positions, prices, dividends, req.window,
            req.interval, adjusted_prices=adjusted_prices, return_basis=req.return_basis, cash_balance=cash)
        diversification = diversification_analysis(positions, prices, performance, req.interval, cash)
        series = history[['performance_value']].rename(columns={'performance_value': 'My portfolio'})
    else:
        series = performance.reindex(columns=tickers)
    comparison = compare_history(series, performance[benchmark], benchmark, interval=req.interval,
                                 annual_risk_free_rate=req.annual_risk_free_rate)
    comparison['return_basis'] = req.return_basis
    comparison['return_basis_label'] = 'Total return (dividends reinvested)' if adjusted else 'Price return'
    warnings = [*comparison['warnings'], *comparison['risk']['warnings']]
    if metrics:
        warnings.extend(metrics['warnings'])
        warnings.extend(diversification['warnings'])

    exports = []
    def csv(name, frame, index=True):
        exports.append({'name': name, 'mime': 'text/csv', 'content': frame.to_csv(index=index)})
    if enriched is not None:
        csv('positions_with_prices.csv', enriched, False)
        csv('portfolio_timeseries.csv', history)
        exports.append({'name': 'holdings_settings.json', 'mime': 'application/json', 'content': json.dumps({
            'cash_balance': cash, 'return_basis': req.return_basis, 'positions': positions.to_dict('records')}, indent=2)})
        allocation = diversification['allocation'].copy()
        for key in ['valuation_date', 'sample_start', 'sample_end', 'observations', 'interval']:
            allocation[key] = diversification[key]
        allocation['return_basis'] = req.return_basis
        allocation['modeled_annualized_volatility'] = diversification['annualized_volatility']
        csv(f'allocation_risk_{req.return_basis}.csv', allocation)
        csv(f'correlation_{req.return_basis}.csv', diversification['correlation'])
    for key in ['normalized', 'drawdowns', 'summary']:
        csv(f'comparison_{key}_{req.return_basis}.csv', comparison[key])
    risk = comparison['risk']
    risk_export = risk['summary'].copy()
    for key in ['annual_risk_free_rate', 'period_risk_free_rate', 'interval', 'sample_start', 'sample_end']:
        risk_export[key] = risk[key]
    risk_export['benchmark'] = comparison['benchmark_label']
    risk_export['return_basis'] = req.return_basis
    csv(f'comparison_risk_{req.return_basis}.csv', risk_export)
    performance_normalized = None
    if history is not None:
        first = history['performance_value'].dropna().iloc[0]
        performance_normalized = (history[['performance_value']] / first * 100).rename(columns={'performance_value':'My portfolio'})
    return clean({'mode': req.mode, 'metrics': metrics, 'positions': enriched, 'history': history,
                  'performance_normalized': performance_normalized,
                  'comparison': comparison, 'diversification': diversification, 'allocation_preview': preview,
                  'identities': identities, 'warnings': list(dict.fromkeys(warnings)), 'exports': exports,
                  'settings': req.model_dump(exclude={'positions', 'allocations', 'refresh'}),
                  'market_data_fetched_at': fetched_at, 'calculated_at': datetime.now(timezone.utc).isoformat()})


app = FastAPI(title='Portfolio Tracker', docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])


@app.middleware('http')
async def local_requests(request: Request, call_next):
    origin = request.headers.get('origin')
    if request.url.path.startswith('/api'):
        if origin and origin not in {f'http://{request.headers.get("host")}', 'http://127.0.0.1:5173', 'http://localhost:5173'}:
            return JSONResponse({'error': 'Open the tracker from its local address.'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api') else 'no-cache'
    return response


@app.exception_handler(PortfolioError)
async def portfolio_error(request, exc):
    return JSONResponse({'error': str(exc)}, status_code=400)


@app.exception_handler(StoreError)
async def storage_error(request, exc):
    return JSONResponse({'error': str(exc)}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    errors = ['.'.join(str(p) for p in e['loc'][1:]) + ': ' + e['msg'] for e in exc.errors()]
    return JSONResponse({'error': 'Check your inputs. ' + '; '.join(errors)}, status_code=422)


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    logging.getLogger(__name__).exception('Analysis request failed')
    return JSONResponse({'error': 'The calculation could not finish. Retry or check the local tracker log.'}, status_code=500)


@app.get('/api/health')
def health():
    return {'status': 'ok', 'service': 'portfolio-terminal', 'version': 1}


@app.get('/api/portfolios')
def list_portfolios():
    return {'portfolios': portfolio_store.list()}


@app.get('/api/portfolios/{portfolio_id}')
def load_portfolio(portfolio_id: UUID):
    return portfolio_store.get(portfolio_id)


@app.post('/api/portfolios/save')
def save_portfolio(request: SavePortfolio):
    return portfolio_store.save(request)


@app.get('/api/search')
def search(q: str = Query(min_length=1, max_length=150)):
    query = q.strip()
    return {'matches': market_cache.get(('search', query), 3600, lambda: search_instruments(query))}


@app.get('/api/instrument')
def verify(symbol: str = Query(min_length=1, max_length=40)):
    return instrument(symbol.strip().upper())


@app.post('/api/import')
def import_csv(req: CsvRequest):
    positions = load_positions(StringIO(req.text))
    if len(positions) > 200:
        raise PortfolioError('Use at most 200 distinct holdings in one analysis.')
    return {'positions': positions.to_dict('records')}


@app.post('/api/allocation')
def preview_allocation(req: AllocationRequest):
    positions, cash, preview = allocation_preview(req)
    return clean({'positions': positions.to_dict('records'), 'cash_balance': cash, 'preview': preview})


@app.post('/api/analyze')
def analyze(req: AnalysisRequest):
    return build_analysis(req)


@app.post('/api/options/analyze')
def calculate_options(req: OptionsRequest):
    return analyze_options(req.model_dump())


@app.post('/api/options/model')
def model_options(req: ScenarioRequest):
    return analyze_scenario(req)


@app.post('/api/analytics/valuation')
def value_company(req: ValuationRequest):
    return analyze_valuation(req)


@app.post('/api/analytics/option')
def value_option(req: OptionPricingRequest):
    return price_option(req)


@app.post('/api/analytics/futures')
def value_futures(req: FuturesPricingRequest):
    return price_futures(req)


@app.post('/api/analytics/bond')
def value_bond(req: BondRequest):
    return analyze_bond(req)


@app.post('/api/backtest')
def backtest(req: BacktestRequest):
    if req.source == 'demo':
        history, fetched_at, identities = demo_history(), None, []
    else:
        if req.refresh:
            market_cache.clear()
        symbols = tuple(dict.fromkeys([a.ticker for a in req.assets]+[req.benchmark]))
        identities = [instrument(t) for t in symbols]
        def fetch():
            return fetch_backtest_history(req), datetime.now(timezone.utc).isoformat()
        history, fetched_at = market_cache.get(('backtest-history', symbols, req.start, req.end, req.window), 900, fetch)
    result = run_backtest(req, history)
    return {**result, 'identities': identities, 'market_data_fetched_at': fetched_at,
            'calculated_at': datetime.now(timezone.utc).isoformat()}


@app.post('/api/simulation/covered-call')
def covered_call_simulation(req: CoveredCallRequest):
    if req.source == 'demo':
        history, fetched_at, identity = demo_covered_history(), None, None
    else:
        if req.refresh:
            market_cache.clear()
        identity = instrument(req.ticker)
        def fetch():
            return fetch_covered_history(req), datetime.now(timezone.utc).isoformat()
        history, fetched_at = market_cache.get(('covered-stock-history',req.ticker,req.start,req.end,req.volatility_window),900,fetch)
    return {**run_covered_simulation(req,history),'identity':identity,'market_data_fetched_at':fetched_at,
            'calculated_at':datetime.now(timezone.utc).isoformat()}


@app.get('/api/options/expirations')
def option_expirations(symbol: str = Query(min_length=1,max_length=40), refresh: bool = False):
    key=symbol_key(symbol)
    if refresh:market_cache.clear()
    return market_cache.get(('option-expirations',key),300,lambda:expirations(key))


def cached_chain(symbol, expiration):
    key=symbol_key(symbol)
    return market_cache.get(('option-chain',key,expiration),300,lambda:option_chain(key,expiration))


@app.get('/api/options/chain')
def get_option_chain(symbol: str = Query(min_length=1,max_length=40), expiration: date = Query(), refresh: bool = False):
    if refresh:market_cache.clear()
    return cached_chain(symbol,expiration.isoformat())


@app.post('/api/options/finder')
def option_finder(req: FinderRequest):
    if req.target_date<date.today():raise PortfolioError('Choose a target date today or later.')
    if any(exp<req.target_date for exp in req.expirations):raise PortfolioError('Selected expirations must be on or after the finder target date.')
    chains=[cached_chain(req.symbol,exp.isoformat()) for exp in sorted(set(req.expirations))]
    return find_options(req,chains)


@app.post('/api/volatility')
def volatility(req: SurfaceRequest):
    if req.source == 'demo':
        chains = demo_chains()
    else:
        key = symbol_key(req.symbol)
        if not req.expirations or len(set(req.expirations)) != len(req.expirations):
            raise PortfolioError('Choose one to four distinct expirations.')
        if req.refresh:
            market_cache.clear()
        chains = [cached_chain(key, exp.isoformat()) for exp in sorted(req.expirations)]
    return build_surface(req, chains)


@app.post('/api/crypto')
def crypto(req: CryptoRequest):
    if req.source == 'demo':
        history, identities, fetched = demo_crypto(), [], None
    else:
        if req.refresh:
            market_cache.clear()
        symbols = tuple(dict.fromkeys([h.ticker for h in req.holdings]+[req.benchmark]))
        def fetch():
            history, identities = fetch_crypto(req)
            return history, identities, datetime.now(timezone.utc).isoformat()
        history, identities, fetched = market_cache.get(('crypto',symbols,req.start,req.end),900,fetch)
    return {**crypto_analysis(req,history),'identities':identities,'market_data_fetched_at':fetched}


dist = Path(__file__).parent / 'terminal' / 'dist'
if dist.exists():
    app.mount('/', StaticFiles(directory=dist, html=True), name='terminal')
