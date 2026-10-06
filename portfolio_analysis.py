"""Allocation entry, current weights, and historical covariance risk estimates."""
import math
import numpy as np
import pandas as pd
from tracker import (PortfolioError, normalize_positions, prepare_prices, validate_interval,
                     validate_cash, PERIODS_PER_YEAR)

CASH_LABEL = 'Uninvested cash (USD)'


def allocations_to_positions(total_invested, entries, unit='percent'):
    """Convert initial dollar/percentage budgets into fractional holdings and cash."""
    total = validate_cash(total_invested)
    if total <= 0:
        raise PortfolioError('Total amount invested must be greater than zero.')
    if unit not in {'percent', 'dollars'}:
        raise PortfolioError('Choose percentage or dollar allocations.')
    required = {'ticker', 'allocation', 'purchase_price'}
    if not required.issubset(entries.columns):
        raise PortfolioError('Allocation entries need ticker, allocation, and purchase_price.')
    df = entries.copy()
    df['ticker'] = df.ticker.astype('string').str.strip().str.upper()
    df['allocation'] = pd.to_numeric(df.allocation, errors='coerce')
    df['purchase_price'] = pd.to_numeric(df.purchase_price, errors='coerce')
    if (~np.isfinite(df.allocation) | df.allocation.lt(0)).any():
        raise PortfolioError('Every allocation must be a finite, non-negative number; use 0 for an unallocated selection.')
    allocated = float(df.allocation.sum())
    limit = 100. if unit == 'percent' else total
    tolerance = max(1e-10, limit * 1e-12)
    if not math.isfinite(allocated) or allocated > limit + tolerance:
        raise PortfolioError('Allocations exceed 100% of the invested amount.' if unit == 'percent' else 'Dollar allocations exceed the total amount invested.')
    df['invested_amount'] = df.allocation * total / 100 if unit == 'percent' else df.allocation
    active = df.invested_amount.gt(0)
    if (df.loc[active, 'ticker'].isna() | df.loc[active, 'ticker'].eq('')).any():
        raise PortfolioError('Every positive allocation needs a ticker.')
    if (~np.isfinite(df.loc[active, 'purchase_price']) | df.loc[active, 'purchase_price'].le(0)).any():
        raise PortfolioError('Every positive allocation needs a finite purchase price greater than zero.')
    funded = df.loc[active].copy()
    funded['qty'] = funded.invested_amount / funded.purchase_price
    positions = funded.rename(columns={'purchase_price':'avg_cost'})[['ticker','qty','avg_cost']]
    if len(positions):
        positions = normalize_positions(positions)
    else:
        positions = pd.DataFrame(columns=['ticker','qty','avg_cost','currency'])
    used = float(funded.invested_amount.sum())
    cash = max(0., total-used)
    preview = positions.copy()
    preview['invested_amount'] = preview.qty * preview.avg_cost
    return positions, cash, preview


def diversification_analysis(positions, prices, performance_prices, interval='1d', cash_balance=0.):
    """Current Close-based weights and Euler contributions to annualized volatility.

    A static-weight covariance estimate, not historical buy-and-hold volatility.
    Cash earns zero and contributes no covariance. Correlations use securities only.
    """
    validate_interval(interval)
    cash = validate_cash(cash_balance)
    warnings = []
    if positions.empty:
        if cash <= 0:
            raise PortfolioError('Add a holding or a positive cash balance.')
        if prices.empty:
            raise PortfolioError('No history is available for this analysis.')
        allocation = pd.DataFrame({'market_value':[cash], 'weight':[1.],
            'volatility_contribution':[0.], 'risk_share':[np.nan]}, index=[CASH_LABEL])
        return {'allocation':allocation, 'correlation':pd.DataFrame(), 'covariance':pd.DataFrame(),
                'annualized_volatility':0., 'valuation_date':str(prices.index.max()),
                'sample_start':None, 'sample_end':None, 'observations':0, 'interval':interval,
                'warnings':['Cash-only allocation has zero modeled market volatility. Risk percentages and cash correlation are undefined.']}
    pos = normalize_positions(positions)
    raw = prepare_prices(pos, prices)
    complete = raw.notna().all(axis=1)
    valuation_date = raw.index[complete][-1]
    market_values = raw.loc[valuation_date] * pos.set_index('ticker').qty
    total = float(market_values.sum()) + cash
    if not math.isfinite(total) or total <= 0:
        raise PortfolioError('Current portfolio value must be positive and finite.')
    allocation = pd.DataFrame({'market_value':market_values, 'weight':market_values/total})
    weights = allocation.weight.copy()
    if cash > 0:
        allocation.loc[CASH_LABEL] = [cash, cash/total]
    allocation['volatility_contribution'] = np.nan
    allocation['risk_share'] = np.nan
    if cash > 0:
        allocation.loc[CASH_LABEL,'volatility_contribution'] = 0.
    history = prepare_prices(pos, performance_prices).reindex(raw.index).where(raw.notna()).loc[:valuation_date]
    returns = history.pct_change(fill_method=None).replace([np.inf,-np.inf],np.nan).dropna(how='any')
    n = len(returns)
    correlation = pd.DataFrame(np.nan,index=weights.index,columns=weights.index)
    covariance = correlation.copy()
    annual_vol = None
    start = end = None
    if n:
        first = history.index.get_loc(returns.index[0])
        start, end = str(history.index[first-1]), str(returns.index[-1])
    if n < 2:
        warnings.append('Correlation and risk contributions need at least 2 matched returns. Try a longer history.')
    else:
        if n < 30:
            warnings.append(f'Only {n} matched returns are available; correlation and risk contributions may be unstable.')
        covariance = returns.cov() * PERIODS_PER_YEAR[interval]
        correlation = returns.corr().clip(-1,1)
        constant = returns.std(ddof=1) <= 1e-12
        correlation.loc[constant, :] = np.nan
        correlation.loc[:, constant] = np.nan
        # Remove floating-point noise for constant securities.
        covariance.loc[constant, :] = 0.
        covariance.loc[:, constant] = 0.
        weighted_covariance = covariance.dot(weights)
        variance = float(weights.dot(weighted_covariance))
        annual_vol = math.sqrt(max(0.,variance))
        if annual_vol <= 1e-12:
            allocation['volatility_contribution'] = 0.
            warnings.append('Modeled portfolio volatility is zero. Percentage risk contributions are undefined.')
        else:
            contributions = weights * weighted_covariance / annual_vol
            allocation.loc[weights.index,'volatility_contribution'] = contributions
            allocation['risk_share'] = allocation.volatility_contribution / annual_vol
        if constant.any():
            warnings.append('Correlation is undefined for securities with constant returns; those cells remain blank.')
    if history.isna().any().any():
        warnings.append('Missing quotes and returns immediately after a gap are excluded from the shared estimation sample.')
    return {'allocation':allocation, 'correlation':correlation, 'covariance':covariance,
            'annualized_volatility':annual_vol, 'valuation_date':str(valuation_date),
            'sample_start':start,'sample_end':end,'observations':n,'interval':interval,'warnings':warnings}
