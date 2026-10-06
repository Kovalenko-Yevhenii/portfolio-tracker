"""Shared equity portfolio engine for the CLI and Streamlit dashboard.

Author: Yevhenii Kovalenko
History models current holdings, with optional dividend-reinvested performance
from adjusted prices. Actual account trades are not modeled. Missing quotes remain unknown.
"""
import argparse
import json
import math
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt

PERIODS_PER_YEAR = {"1d": 252, "1wk": 52, "1mo": 12}


class PortfolioError(ValueError):
    """An actionable input or market-data problem."""


def validate_interval(interval):
    if interval not in PERIODS_PER_YEAR:
        raise PortfolioError("Choose a daily (1d), weekly (1wk), or monthly (1mo) interval.")


def annualized_volatility(returns, window=30, interval="1d"):
    """Sample volatility of the latest complete window of return observations."""
    validate_interval(interval)
    if not isinstance(window, (int, np.integer)) or window < 2:
        raise PortfolioError("Volatility window must be an integer of at least 2 observations.")
    recent = returns.tail(window)
    if len(recent) < window or not np.isfinite(recent).all():
        return float("nan")
    return float(recent.std(ddof=1) * math.sqrt(PERIODS_PER_YEAR[interval]))


def normalize_positions(positions):
    """Validate every row and combine lots using quantity-weighted average cost."""
    df = positions.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    if df.columns.duplicated().any():
        raise PortfolioError("Positions contain duplicate column names.")
    required = {"ticker", "qty", "avg_cost"}
    if not required.issubset(df.columns):
        raise PortfolioError("Positions must contain ticker, qty, and avg_cost columns.")
    if df.empty:
        raise PortfolioError("The positions file contains no holdings.")
    df["ticker"] = df["ticker"].astype("string").str.strip().str.upper()
    for col in ("qty", "avg_cost"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    invalid = (df["ticker"].isna() | df["ticker"].eq("") |
               ~np.isfinite(df["qty"]) | ~np.isfinite(df["avg_cost"]) |
               df["qty"].le(0) | df["avg_cost"].lt(0))
    if invalid.any():
        rows = ", ".join(str(i + 2) for i, bad in enumerate(invalid) if bad)
        raise PortfolioError(
            f"Invalid holdings on CSV row(s) {rows}. Supply a ticker, positive finite "
            "quantity, and non-negative finite average cost. Short positions require a trade ledger.")
    if "currency" not in df:
        df["currency"] = "USD"
    df["currency"] = df["currency"].astype("string").str.strip().str.upper()
    if not df["currency"].eq("USD").fillna(False).all():
        raise PortfolioError("This equity version supports USD-quoted holdings only; FX conversion is not implemented.")
    # Reject overflow rather than writing invalid totals to a report.
    df["cost_value"] = df["qty"] * df["avg_cost"]
    if not np.isfinite(df["cost_value"]).all():
        raise PortfolioError("Holding values are too large to calculate reliably.")
    result = df.groupby("ticker", sort=False, as_index=False).agg(
        qty=("qty", "sum"), cost_value=("cost_value", "sum"))
    result["avg_cost"] = result["cost_value"] / result["qty"]
    result["currency"] = "USD"
    if not np.isfinite(result[["qty", "cost_value", "avg_cost"]]).all().all():
        raise PortfolioError("Combined holding values are too large to calculate reliably.")
    return result[["ticker", "qty", "avg_cost", "currency"]]


def load_positions(csv_path):
    try:
        df = pd.read_csv(csv_path)
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        raise PortfolioError(f"Cannot read positions CSV: {exc}") from exc
    return normalize_positions(df)


def prepare_prices(positions, prices):
    """Keep gaps as NaN; never replace missing holdings with zero or future prices."""
    if prices.empty:
        raise PortfolioError("No price history returned. Check tickers, history period, and your connection.")
    if prices.columns.duplicated().any() or prices.index.has_duplicates:
        raise PortfolioError("Price history contains duplicate tickers or dates.")
    aligned = prices.reindex(columns=positions["ticker"]).sort_index().copy()
    aligned = aligned.apply(pd.to_numeric, errors="coerce")
    aligned = aligned.where(np.isfinite(aligned) & aligned.gt(0))
    unavailable = aligned.columns[aligned.isna().all()].tolist()
    if unavailable:
        raise PortfolioError("No usable prices for: " + ", ".join(unavailable) + ". Check these tickers or retry.")
    if not aligned.notna().all(axis=1).any():
        raise PortfolioError("No date has valid prices for every holding. Choose a longer history or review the tickers.")
    return aligned


def fetch_price_history(tickers, period="1y", interval="1d", include_adjusted=False):
    validate_interval(interval)
    tickers = list(dict.fromkeys(str(t).strip().upper() for t in tickers))
    if not tickers or any(not t for t in tickers):
        raise PortfolioError("Supply at least one valid ticker.")
    try:
        data = yf.download(tickers=tickers, period=period, interval=interval,
                           auto_adjust=False, actions=True, group_by="ticker", progress=False)
    except Exception as exc:
        raise PortfolioError("Price download failed. Check your connection and retry.") from exc
    if data is None or data.empty:
        raise PortfolioError("No price history returned. Check tickers, history period, and your connection.")
    close, dividends, adjusted = {}, {}, {}
    for ticker in tickers:
        if isinstance(data.columns, pd.MultiIndex):
            fields = data[ticker] if ticker in data.columns.get_level_values(0) else pd.DataFrame(index=data.index)
        elif len(tickers) == 1:
            fields = data
        else:
            raise PortfolioError("Unexpected price download format. Please retry.")
        close[ticker] = fields.get("Close", pd.Series(index=data.index, dtype=float))
        adjusted[ticker] = fields.get("Adj Close", pd.Series(index=data.index, dtype=float))
        if "Dividends" in fields:
            dividends[ticker] = fields["Dividends"]
    prices = pd.DataFrame(close)
    divs = pd.DataFrame(dividends, index=data.index)
    adjusted_prices = pd.DataFrame(adjusted, index=data.index)
    for frame in (prices, divs, adjusted_prices):
        frame.index = pd.to_datetime(frame.index).tz_localize(None)
        frame.sort_index(inplace=True)
    # Stop a partial download before it becomes a partial portfolio valuation.
    prices = prepare_prices(pd.DataFrame({"ticker": tickers}), prices)
    if include_adjusted:
        adjusted_prices = validate_adjusted_prices(pd.DataFrame({"ticker": tickers}), adjusted_prices)
        return prices, divs, adjusted_prices
    return prices, divs


def search_instruments(query):
    """Find equities/ETFs by company name or ticker; never silently choose a match."""
    query = str(query).strip()
    if not query:
        raise PortfolioError("Enter a ticker or company name to search.")
    try:
        quotes = yf.Search(query, max_results=12, news_count=0, lists_count=0,
                           timeout=10).quotes
    except Exception as exc:
        raise PortfolioError("Ticker search is unavailable. Check your connection and try again.") from exc
    matches, seen = [], set()
    for quote in quotes:
        symbol = quote.get("symbol")
        if not symbol or symbol in seen or quote.get("quoteType") not in {"EQUITY", "ETF"}:
            continue
        seen.add(symbol)
        matches.append({"ticker": symbol, "name": quote.get("longname") or quote.get("shortname") or symbol,
                        "exchange": quote.get("exchDisp") or quote.get("exchange") or "Unknown exchange"})
    if not matches:
        raise PortfolioError("No equity or ETF matches found. Try the exact ticker or another company name.")
    return matches


def get_instrument(symbol):
    """Validate the exact symbol and quote currency before using a selection."""
    symbol = str(symbol).strip().upper()
    if not symbol:
        raise PortfolioError("Enter a benchmark ticker.")
    try:
        info = yf.Ticker(symbol).get_info()
    except Exception as exc:
        raise PortfolioError(f"Cannot verify {symbol}. Check the ticker and connection, then retry.") from exc
    if not info or str(info.get("symbol", "")).upper() != symbol:
        raise PortfolioError(f"Cannot verify the exact ticker {symbol}. Use ticker search to select it.")
    if info.get("quoteType") not in {"EQUITY", "ETF"}:
        raise PortfolioError(f"{symbol} is not a supported equity or ETF.")
    if info.get("currency") != "USD":
        raise PortfolioError(f"{symbol} is not confirmed as USD-quoted. FX conversion is not available yet.")
    return {"ticker": symbol, "name": info.get("longName") or info.get("shortName") or symbol,
            "exchange": info.get("fullExchangeName") or info.get("exchange") or "Unknown exchange",
            "currency": "USD"}


def drawdown_series(values):
    """Observed decline from the running peak; preserve missing observations."""
    clean = pd.to_numeric(values, errors="coerce")
    clean = clean.where(np.isfinite(clean) & clean.gt(0))
    return clean / clean.cummax() - 1.0


def risk_statistics(values, benchmark_label, interval="1d", annual_risk_free_rate=0.0):
    """Annualized historical Sharpe and OLS beta on identical return observations.

    Compute returns before dropping missing observations, so no change across a
    missing quote is mistaken for a single-period return. All series use the same
    complete sample. The constant annual rate is an effective-rate assumption.
    """
    validate_interval(interval)
    try:
        rate = float(annual_risk_free_rate)
    except (TypeError, ValueError) as exc:
        raise PortfolioError("Annual risk-free rate must be a finite number greater than -100%.") from exc
    if not math.isfinite(rate) or rate <= -1:
        raise PortfolioError("Annual risk-free rate must be a finite number greater than -100%.")
    if benchmark_label not in values.columns:
        raise PortfolioError("Benchmark is missing from the risk comparison.")
    if values.columns.duplicated().any() or values.index.has_duplicates:
        raise PortfolioError("Risk history contains duplicate dates or names.")
    clean = values.sort_index().apply(pd.to_numeric, errors="coerce")
    clean = clean.where(np.isfinite(clean) & clean.gt(0))
    returns = clean.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).dropna(how="any")
    count = len(returns)
    periods = PERIODS_PER_YEAR[interval]
    per_period_rate = math.expm1(math.log1p(rate) / periods)
    warnings, rows = [], {}
    sample_start = sample_end = None
    if count:
        first_position = clean.index.get_loc(returns.index[0])
        sample_start = str(clean.index[first_position - 1])
        sample_end = str(returns.index[-1])
    if count < 2:
        warnings.append("Sharpe and beta need at least 2 matched one-period returns. Try a longer history; gaps and the returns immediately after them are excluded.")
    elif count < 30:
        warnings.append(f"Risk estimates use only {count} matched returns and may be unstable. A longer history provides more evidence.")
    market_std = float(returns[benchmark_label].std(ddof=1)) if count >= 2 else None
    zero_tolerance = 1e-12
    if market_std is not None and market_std <= zero_tolerance:
        warnings.append("Beta is unavailable because benchmark returns have zero or numerically negligible variance.")
    for column in clean.columns:
        sharpe = beta = None
        if count >= 2:
            excess = returns[column] - per_period_rate
            std = float(excess.std(ddof=1))
            if std > zero_tolerance:
                candidate = float(excess.mean()) / std * math.sqrt(periods)
                sharpe = candidate if math.isfinite(candidate) else None
            else:
                warnings.append(f"Sharpe is unavailable for {column}: excess returns have zero or numerically negligible volatility.")
            if market_std > zero_tolerance:
                candidate = float(returns[column].cov(returns[benchmark_label])) / market_std**2
                beta = candidate if math.isfinite(candidate) else None
        rows[column] = {"sharpe_ratio": sharpe, "beta": beta, "matched_return_observations": count}
    return {"summary": pd.DataFrame.from_dict(rows, orient="index"),
            "annual_risk_free_rate": rate, "period_risk_free_rate": per_period_rate,
            "interval": interval, "periods_per_year": periods,
            "sample_start": sample_start, "sample_end": sample_end,
            "matched_return_observations": count, "warnings": warnings}


def compare_history(series, benchmark, benchmark_symbol="SPY", interval="1d", annual_risk_free_rate=0.0):
    """Rebase all series to 100 over the same endpoints, preserving interior gaps.

    Columns identify distinct investments; research mode does not invent a basket.
    Drawdowns use the common observed dates, so gaps may hide deeper losses.
    """
    if series.empty or benchmark.empty:
        raise PortfolioError("Not enough history for benchmark comparison.")
    if series.columns.duplicated().any() or series.index.has_duplicates or benchmark.index.has_duplicates:
        raise PortfolioError("Comparison history contains duplicate dates or names.")
    label = f"Benchmark: {benchmark_symbol}"
    if label in series.columns:
        raise PortfolioError("An investment name conflicts with the benchmark label.")
    combined = series.join(benchmark.rename(label), how="outer").sort_index()
    combined = combined.apply(pd.to_numeric, errors="coerce")
    combined = combined.where(np.isfinite(combined) & combined.gt(0))
    common = combined.notna().all(axis=1)
    if common.sum() < 2:
        raise PortfolioError("Comparison needs at least two dates with prices for all selections and the benchmark. Try a longer history.")
    start, end = combined.index[common][[0, -1]]
    combined = combined.loc[start:end]
    common = combined.notna().all(axis=1)
    aligned = combined.where(common, axis=0)
    normalized = aligned.div(aligned.iloc[0]).mul(100)
    drawdowns = aligned.apply(drawdown_series)
    summary = pd.DataFrame({"period_return": normalized.iloc[-1] / 100 - 1,
                            "maximum_drawdown": drawdowns.min()})
    summary["excess_return_vs_benchmark"] = summary["period_return"] - summary.loc[label, "period_return"]
    warnings = []
    if (~common).any():
        warnings.append(f"{int((~common).sum())} comparison observation(s) lack complete quotes. Charts retain gaps; observed drawdown may understate losses during missing periods.")
    risk = risk_statistics(aligned, label, interval, annual_risk_free_rate)
    return {"normalized": normalized, "drawdowns": drawdowns, "summary": summary, "risk": risk,
            "start": str(start), "end": str(end), "benchmark_label": label,
            "warnings": warnings}


def _value_history(positions, prices):
    values = prices.mul(positions.set_index("ticker")["qty"], axis="columns")
    if np.isinf(values.to_numpy()).any():
        raise PortfolioError("Market values are too large to calculate reliably.")
    values["portfolio_value"] = values.sum(axis=1, min_count=len(positions))
    return values


def compute_portfolio_timeseries(positions, prices):
    positions = normalize_positions(positions)
    return _value_history(positions, prepare_prices(positions, prices))


def validate_return_basis(return_basis):
    if return_basis not in {"price", "total"}:
        raise PortfolioError("Return basis must be price or total.")


def validate_adjusted_prices(positions, adjusted_prices):
    if adjusted_prices is None:
        raise PortfolioError("Dividend-adjusted prices are required for total return. Refresh market data or select Price return.")
    try:
        return prepare_prices(positions, adjusted_prices)
    except PortfolioError as exc:
        raise PortfolioError(f"Dividend-adjusted history is unavailable or incomplete: {exc} Select Price return or retry.") from exc


def portfolio_performance(positions, prices, adjusted_prices=None, return_basis="price"):
    """Modeled buy-and-hold wealth; only performance uses adjusted prices.

    Initial dollars are quantity * actual Close at the first complete raw and
    adjusted observation. Each asset's dollars then grow by AdjClose[t]/AdjClose[0].
    This preserves real starting weights regardless of provider adjustment scales,
    and models reinvestment within each asset, without portfolio rebalancing.
    """
    validate_return_basis(return_basis)
    pos = normalize_positions(positions)
    prices = prepare_prices(pos, prices)
    if return_basis == "price":
        return _value_history(pos, prices)["portfolio_value"].rename("performance_value")
    adjusted = validate_adjusted_prices(pos, adjusted_prices).reindex(prices.index)
    adjusted = adjusted.where(prices.notna())
    complete = adjusted.notna().all(axis=1) & prices.notna().all(axis=1)
    if not complete.any():
        raise PortfolioError("No common starting date for closing and dividend-adjusted prices.")
    start = prices.index[complete][0]
    initial_dollars = prices.loc[start] * pos.set_index("ticker")["qty"]
    growth = adjusted.loc[start:].div(adjusted.loc[start])
    wealth = growth.mul(initial_dollars).sum(axis=1, min_count=len(pos))
    if np.isinf(wealth.to_numpy()).any():
        raise PortfolioError("Performance values are too large to calculate reliably.")
    return wealth.reindex(prices.index).rename("performance_value")


def validate_cash(cash_balance):
    try:
        cash = float(cash_balance)
    except (TypeError, ValueError) as exc:
        raise PortfolioError("Cash balance must be a finite, non-negative amount.") from exc
    if not math.isfinite(cash) or cash < 0:
        raise PortfolioError("Cash balance must be a finite, non-negative amount.")
    return cash


def compute_metrics(positions, prices, dividends=None, window_vol=30, interval="1d",
                    adjusted_prices=None, return_basis="price", cash_balance=0.0):
    cash = validate_cash(cash_balance)
    if positions.empty and cash > 0:
        # Use observed market dates, but never request a cash ticker from Yahoo.
        if prices.empty or prices.index.has_duplicates:
            raise PortfolioError("No valid history dates are available for the cash balance.")
        cash_prices = pd.DataFrame({"_INTERNAL_CASH": 1.}, index=prices.index.sort_values())
        synthetic = pd.DataFrame({"ticker":["_INTERNAL_CASH"], "qty":[cash], "avg_cost":[1.]})
        _, ts, metrics = compute_metrics(synthetic, cash_prices, window_vol=window_vol,
            interval=interval, adjusted_prices=cash_prices, return_basis=return_basis)
        ts = ts.drop(columns=["_INTERNAL_CASH"])
        ts["cash_balance"] = cash
        metrics.update(cash_balance=cash, securities_value=0., invested_cost=0.)
        empty = pd.DataFrame(columns=["ticker","qty","avg_cost","currency","last_price","market_value","cost_value","unrealized_pnl"])
        return empty, ts, metrics
    pos = normalize_positions(positions)
    prices = prepare_prices(pos, prices)
    ts = _value_history(pos, prices)
    ts["portfolio_value"] = ts["portfolio_value"] + cash
    ts["cash_balance"] = cash
    # Preserve gaps so the next observed change is not mislabeled a one-period return.
    ts["performance_value"] = portfolio_performance(pos, prices, adjusted_prices, return_basis) + cash
    ts["price_returns"] = ts["portfolio_value"].pct_change(fill_method=None)
    ts["returns"] = ts["performance_value"].pct_change(fill_method=None)
    ts["drawdown"] = drawdown_series(ts["performance_value"])
    vol = annualized_volatility(ts["returns"], window_vol, interval)
    complete = prices.notna().all(axis=1)
    valuation_date = prices.index[complete][-1]
    latest = prices.loc[valuation_date]
    pos["last_price"] = pos["ticker"].map(latest.to_dict())
    pos["market_value"] = pos["qty"] * pos["last_price"]
    pos["cost_value"] = pos["qty"] * pos["avg_cost"]
    pos["unrealized_pnl"] = pos["market_value"] - pos["cost_value"]
    warnings = []
    gaps = int((~complete).sum())
    if gaps:
        warnings.append(f"{gaps} history observation(s) have missing quotes. Portfolio values and affected returns are left blank; observed drawdown may understate losses during gaps.")
    if valuation_date != prices.index[-1]:
        warnings.append(f"Latest quotes are incomplete; snapshot uses the last complete observation: {valuation_date}.")
    performance_gaps = int(ts["performance_value"].isna().sum())
    if return_basis == "total" and performance_gaps:
        warnings.append(f"{performance_gaps} performance observation(s) lack complete raw/adjusted quotes, including any dates before the common start. Total-return history retains these gaps.")
    if not math.isfinite(vol):
        warnings.append(f"Volatility needs {window_vol} consecutive valid returns at the end of the selected history. Try a longer history or smaller window.")
    metrics = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "valuation_date": str(valuation_date),
        "currency": "USD",
        "total_cost": float(pos["cost_value"].sum()) + cash,
        "invested_cost": float(pos["cost_value"].sum()),
        "cash_balance": cash,
        "securities_value": float(pos["market_value"].sum()),
        "total_value": float(pos["market_value"].sum()) + cash,
        "total_unrealized_pnl": float(pos["unrealized_pnl"].sum()),
        "interval": interval,
        "return_basis": return_basis,
        "performance_start": str(ts["performance_value"].first_valid_index()),
        "performance_end": str(ts["performance_value"].last_valid_index()),
        "missing_performance_observations": performance_gaps,
        "annualized_volatility_window_observations": int(window_vol),
        "annualized_volatility_window_days": int(window_vol) if interval == "1d" else None,
        "annualized_volatility": vol if math.isfinite(vol) else None,
        "maximum_drawdown": float(ts["drawdown"].min()),
        "missing_price_observations": gaps,
        "warnings": warnings,
    }
    # Informational per-share dividends are not added again: adjusted prices already
    # account for distributions in total-return mode.
    div_summary = {}
    if dividends is not None and not dividends.empty and isinstance(prices.index, pd.DatetimeIndex):
        divs = dividends.copy()
        divs.index = pd.to_datetime(divs.index).tz_localize(None)
        end = prices.index[-1]
        divs = divs.loc[(divs.index > end - pd.DateOffset(years=1)) & (divs.index <= end)]
        for ticker in pos["ticker"]:
            if ticker in divs and divs[ticker].notna().any():
                value = float(divs[ticker].sum())
                if math.isfinite(value):
                    div_summary[ticker] = value
    metrics["dividends_last_year_by_ticker"] = div_summary
    ts["return_basis"] = return_basis
    return pos, ts, metrics


def export_outputs(pos_df, ts_df, metrics, out_dir="outputs"):
    os.makedirs(out_dir, exist_ok=True)
    pos_path = os.path.join(out_dir, "positions_with_prices.csv")
    ts_path = os.path.join(out_dir, "portfolio_timeseries.csv")
    metrics_path = os.path.join(out_dir, "portfolio_metrics.json")
    xlsx_path = os.path.join(out_dir, "portfolio_report.xlsx")
    chart_path = os.path.join(out_dir, "portfolio_value_chart.png")

    pos_df.to_csv(pos_path, index=False)
    ts_df.to_csv(ts_path)
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2, allow_nan=False)

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        pos_df.to_excel(writer, index=False, sheet_name="Positions")
        ts_df.to_excel(writer, sheet_name="TimeSeries")
        pd.DataFrame([metrics]).to_excel(writer, index=False, sheet_name="Metrics")

    if "portfolio_value" in ts_df.columns and not ts_df["portfolio_value"].dropna().empty:
        plt.figure()
        ts_df["portfolio_value"].plot(title="Portfolio Value Over Time")
        plt.xlabel("Date")
        plt.ylabel("Value")
        plt.tight_layout()
        plt.savefig(chart_path)
        plt.close()

    return {
        "positions_with_prices.csv": pos_path,
        "portfolio_timeseries.csv": ts_path,
        "portfolio_metrics.json": metrics_path,
        "portfolio_report.xlsx": xlsx_path,
        "portfolio_value_chart.png": chart_path,
    }

def main():
    parser = argparse.ArgumentParser(description="USD equity portfolio tracker")
    parser.add_argument("--positions", required=True, help="Positions CSV path")
    parser.add_argument("--period", default="1y", help="History period (e.g. 6mo, 1y, 5y)")
    parser.add_argument("--interval", default="1d", choices=list(PERIODS_PER_YEAR))
    parser.add_argument("--vol_window", type=int, default=30, help="Volatility window in return observations (minimum 2)")
    parser.add_argument("--out", default="outputs", help="Output directory")
    parser.add_argument("--cash", type=float, default=0.0, help="Uninvested USD cash, modeled without interest")
    parser.add_argument("--return_basis", choices=["price", "total"], default="price", help="Performance basis; total uses dividend-adjusted history")
    args = parser.parse_args()
    try:
        if args.vol_window < 2:
            raise PortfolioError("Volatility window must be at least 2 observations.")
        positions = load_positions(args.positions)
        if args.return_basis == "total":
            prices, dividends, adjusted = fetch_price_history(positions["ticker"].tolist(), args.period, args.interval, include_adjusted=True)
        else:
            prices, dividends = fetch_price_history(positions["ticker"].tolist(), args.period, args.interval)
            adjusted = None
        pos, ts, metrics = compute_metrics(positions, prices, dividends, args.vol_window, args.interval,
                                          adjusted_prices=adjusted, return_basis=args.return_basis, cash_balance=args.cash)
        files = export_outputs(pos, ts, metrics, args.out)
    except (PortfolioError, OSError) as exc:
        parser.exit(2, f"Error: {exc}\n")
    for warning in metrics["warnings"]:
        print(f"Note: {warning}")
    print(f"Snapshot date: {metrics['valuation_date']}")
    print("Done. Outputs written to:", args.out)
    for name, path in files.items():
        print(f"- {name}: {path}")


if __name__ == "__main__":
    main()
