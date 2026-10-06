"""Direct-entry equity tracker and research comparison dashboard."""
import json
import pandas as pd
import streamlit as st
from portfolio_analysis import allocations_to_positions, diversification_analysis
from tracker import (PortfolioError, load_positions, normalize_positions, fetch_price_history,
                     compute_metrics, search_instruments, get_instrument, compare_history, validate_adjusted_prices)

st.set_page_config(page_title="Portfolio Tracker", layout="wide")
st.title("📈 Portfolio Tracker")
st.caption("Track your holdings or research equities and ETFs. Historical prices are retrieved from Yahoo Finance.")


@st.cache_data(ttl=900, show_spinner=True)
def cached_history(tickers, period, interval, include_adjusted=False):
    if include_adjusted:
        return fetch_price_history(tickers, period, interval, include_adjusted=True)
    return fetch_price_history(tickers, period, interval)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_search(query):
    return search_instruments(query)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_instrument(symbol):
    return get_instrument(symbol)


def show_portfolio(positions, prices, dividends, window, interval, adjusted_prices=None, return_basis="price", cash_balance=0.0):
    """Render shared engine results without duplicating financial calculations."""
    positions, history, metrics = compute_metrics(positions, prices, dividends, window, interval, adjusted_prices=adjusted_prices, return_basis=return_basis, cash_balance=cash_balance)
    for warning in metrics["warnings"]:
        st.warning(warning)
    st.subheader("Snapshot")
    basis_label = "Total return (dividends reinvested)" if return_basis == "total" else "Price return"
    st.caption(f"Prices as of {metrics['valuation_date']} · USD. Holdings value and unrealized P&L use actual closing prices.")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Value", f"${metrics['total_value']:,.2f}")
    c2.metric("Unrealized P&L", f"${metrics['total_unrealized_pnl']:,.2f}")
    c3.metric("Total Cost", f"${metrics['total_cost']:,.2f}")
    vol = metrics["annualized_volatility"]
    c4.metric(f"Ann. Vol ({window} observations)", f"{vol:.2%}" if vol is not None else "—")
    c5.metric("Maximum drawdown", f"{metrics['maximum_drawdown']:.2%}")
    st.caption(f"Volatility and drawdown basis: {basis_label}. Maximum drawdown is the largest observed decline from a prior peak.")
    if cash_balance > 0:
        st.caption(f"Includes ${cash_balance:,.2f} uninvested cash in portfolio value and total cost. Cash earns no interest in this model; unrealized P&L covers securities only.")
    st.subheader("Positions")
    st.dataframe(positions.set_index("ticker").round(4))
    st.subheader("Portfolio Value Over Time")
    st.line_chart(history["portfolio_value"])
    if return_basis == "total":
        st.subheader("Total-return performance")
        first = history["performance_value"].dropna().iloc[0]
        st.line_chart(history["performance_value"] / first * 100, y_label="Starting value = 100")
        st.caption(f"Hypothetical reinvested performance from {metrics['performance_start']}; this is not your account balance. Starting weights use quantities × actual closing prices on that date.")
    st.subheader({"1d": "Daily Returns", "1wk": "Weekly Returns", "1mo": "Monthly Returns"}[interval])
    st.line_chart(history["returns"])
    st.subheader("Portfolio drawdown")
    st.line_chart(history["drawdown"] * 100, y_label="Decline from peak (%)")
    st.download_button("Download positions_with_prices.csv", positions.to_csv(index=False).encode(),
                       file_name="positions_with_prices.csv", mime="text/csv")
    st.download_button("Download portfolio_timeseries.csv", history.to_csv().encode(),
                       file_name="portfolio_timeseries.csv", mime="text/csv")
    st.download_button("Download holdings settings", json.dumps({"cash_balance":cash_balance,
        "return_basis":return_basis, "positions":positions[["ticker","qty","avg_cost","currency"]].to_dict("records")},indent=2),
        file_name="holdings_settings.json",mime="application/json")
    st.caption("Positions CSV contains securities only. The settings download also records cash; when reusing a CSV, enter cash separately.")
    return history


def show_diversification(analysis, return_basis):
    st.subheader("Current portfolio allocation")
    allocation = analysis["allocation"]
    st.caption(f"Market-value weights as of {analysis['valuation_date']}. These can differ from your original investment allocations.")
    st.bar_chart((allocation[["weight"]] * 100).rename(columns={"weight":"Portfolio weight (%)"}), horizontal=True)
    display = allocation[["market_value","weight"]].rename(columns={"market_value":"Market value (USD)","weight":"Portfolio weight (%)"})
    display["Portfolio weight (%)"] *= 100
    st.dataframe(display.round(2))
    st.subheader("Correlation between holdings")
    st.caption(f"Basis: {'Total return' if return_basis == 'total' else 'Price return'}; {analysis['observations']} matched returns. "
               f"Period: {analysis['sample_start'] or 'unavailable'} to {analysis['sample_end'] or 'unavailable'}.")
    correlation = analysis["correlation"]
    if not correlation.empty:
        cells = correlation.rename_axis("Holding").reset_index().melt(id_vars="Holding",var_name="Compared holding",value_name="Correlation")
        st.vega_lite_chart(cells, {
            "mark":{"type":"rect"},
            "encoding":{
                "x":{"field":"Holding","type":"nominal","sort":list(correlation.index)},
                "y":{"field":"Compared holding","type":"nominal","sort":list(correlation.index)},
                "color":{"field":"Correlation","type":"quantitative","scale":{"domain":[-1,1],"scheme":"redblue"}},
                "tooltip":[{"field":"Holding","type":"nominal"},{"field":"Compared holding","type":"nominal"},
                           {"field":"Correlation","type":"quantitative","format":".3f"}]
            }}, use_container_width=True)
        st.caption("+1 means returns moved together, −1 means they moved in opposite directions. Hover for values. Cash and constant-return correlations are undefined.")
    else:
        st.info("No security correlations to display for a cash-only portfolio.")
    st.subheader("Contribution to portfolio volatility")
    vol = analysis["annualized_volatility"]
    st.metric("Annualized volatility at current weights", f"{vol:.2%}" if vol is not None else "—")
    st.caption("This estimate applies current weights to historical covariance across the displayed sample. It can differ from the rolling, buy-and-hold volatility in the snapshot.")
    for warning in analysis["warnings"]:
        st.warning(warning)
    risk = allocation[["volatility_contribution","risk_share"]].copy() * 100
    risk.columns = ["Volatility contribution (percentage points)","Share of portfolio risk (%)"]
    st.dataframe(risk.round(3))
    if risk["Share of portfolio risk (%)"].notna().any():
        st.bar_chart(risk[["Share of portfolio risk (%)"]],horizontal=True)
    st.caption("Contributions sum to modeled volatility; risk shares sum to 100% when volatility is positive. Negative contributions indicate diversification benefits. Cash contributes zero market volatility.")
    output = allocation.copy()
    for field in ["valuation_date","sample_start","sample_end","observations","interval"]:
        output[field] = analysis[field]
    output["return_basis"] = return_basis
    output["modeled_annualized_volatility"] = vol
    st.download_button("Download allocation and risk contributions",output.to_csv().encode(),
        file_name=f"allocation_risk_{return_basis}.csv",mime="text/csv")
    st.download_button("Download correlation matrix",correlation.to_csv().encode(),
        file_name=f"correlation_{return_basis}.csv",mime="text/csv")


def show_comparison(comparison):
    st.subheader("Benchmark comparison")
    st.caption("Basis: " + comparison.get("return_basis_label", "Price return"))
    st.caption(f"Common comparison period: {comparison['start']} to {comparison['end']}. Each series starts at 100.")
    for warning in comparison["warnings"]:
        st.warning(warning)
    st.line_chart(comparison["normalized"], y_label="Starting value = 100")
    table = comparison["summary"].copy()
    table.columns = ["Period return (%)", "Maximum drawdown (%)", "Return minus benchmark (percentage points)"]
    st.dataframe((table * 100).round(2))
    st.caption("Return minus benchmark is a percentage-point difference, not risk-adjusted alpha. Drawdowns here use the common comparison period.")
    risk = comparison["risk"]
    st.subheader("Sharpe ratio and beta")
    interval_label = {"1d": "daily", "1wk": "weekly", "1mo": "monthly"}[risk["interval"]]
    st.caption(f"Annual risk-free rate: {risk['annual_risk_free_rate']:.2%} (constant assumption). "
               f"Interval: {interval_label}; {risk['matched_return_observations']} matched returns. "
               "These ratios use the full available comparison sample, not the rolling volatility window.")
    if risk["sample_start"] is not None:
        st.caption(f"Calculation period: {risk['sample_start']} to {risk['sample_end']}. Missing intervals are excluded without bridging gaps.")
    for warning in risk["warnings"]:
        st.warning(warning)
    risk_table = risk["summary"].rename(columns={"sharpe_ratio": "Annualized Sharpe ratio",
        "beta": "Beta vs benchmark", "matched_return_observations": "Matched returns"})
    st.dataframe(risk_table.round(3))
    st.caption("Sharpe measures excess return per unit of volatility; beta measures historical sensitivity to the chosen benchmark. Ratios are not percentages. Blank values are unavailable. Annualizing Sharpe assumes returns are not serially correlated.")
    st.subheader("Drawdown comparison")
    st.line_chart(comparison["drawdowns"] * 100, y_label="Decline from peak (%)")
    exports = {"comparison_normalized.csv": comparison["normalized"],
               "comparison_drawdowns.csv": comparison["drawdowns"],
               "comparison_summary.csv": comparison["summary"]}
    risk_export = risk["summary"].copy()
    for field in ["annual_risk_free_rate", "period_risk_free_rate", "interval", "sample_start", "sample_end"]:
        risk_export[field] = risk[field]
    risk_export["benchmark"] = comparison["benchmark_label"]
    risk_export["return_basis"] = comparison.get("return_basis", "price")
    exports["comparison_risk.csv"] = risk_export
    for name, data in exports.items():
        name = name.replace(".csv", "_" + comparison.get("return_basis", "price") + ".csv")
        st.download_button("Download " + name, data.to_csv().encode(), file_name=name, mime="text/csv")


def analyze(mode, positions, tickers, benchmark, period, interval, window, return_basis="price", annual_risk_free_rate=0.0, cash_balance=0.0):
    """Retrieve and validate selections, then compare on identical dates."""
    unique = list(dict.fromkeys([*tickers, benchmark]))
    identities = [cached_instrument(t) for t in unique]
    adjusted_prices = None
    if return_basis == "total":
        prices, dividends, adjusted_prices = cached_history(tuple(unique), period, interval, include_adjusted=True)
        comparison_prices = validate_adjusted_prices(pd.DataFrame({"ticker": unique}), adjusted_prices).reindex(prices.index).where(prices.notna())
    else:
        prices, dividends = cached_history(tuple(unique), period, interval)
        comparison_prices = prices
    diversification = None
    if mode == "My holdings":
        diversification = diversification_analysis(positions, prices, comparison_prices, interval, cash_balance)
        _, history, _ = compute_metrics(positions, prices, dividends, window, interval, adjusted_prices=adjusted_prices, return_basis=return_basis, cash_balance=cash_balance)
        series = history[["performance_value"]].rename(columns={"performance_value": "My portfolio"})
    else:
        series = comparison_prices.reindex(columns=tickers)
    comparison = compare_history(series, comparison_prices[benchmark], benchmark, interval=interval, annual_risk_free_rate=annual_risk_free_rate)
    comparison["return_basis"] = return_basis
    comparison["return_basis_label"] = "Total return (dividends reinvested)" if return_basis == "total" else "Price return"
    return {"prices": prices, "dividends": dividends, "adjusted_prices": adjusted_prices, "identities": identities, "comparison": comparison, "diversification": diversification}


with st.sidebar:
    st.header("Analysis settings")
    mode = st.radio("Mode", ["My holdings", "Research tickers"], key="mode")
    return_basis_label = st.radio("Return basis", ["Price return", "Total return (dividends reinvested)"], key="return_basis")
    return_basis = "total" if return_basis_label.startswith("Total") else "price"
    period = st.selectbox("History period", ["6mo", "1y", "2y", "5y", "max"], index=1)
    interval = st.selectbox("Interval", ["1d", "1wk", "1mo"], index=0)
    vol_window = st.number_input("Volatility window (observations)", min_value=2, max_value=252, value=30)
    risk_free_percent = st.number_input("Annual risk-free rate (%)", min_value=-99.0, value=0.0, step=0.25, format="%.2f", key="risk_free_percent")
    annual_risk_free_rate = float(risk_free_percent) / 100
    st.caption("Default 0% is an editable assumption, not a current Treasury yield. Applied consistently across the chosen history.")
    benchmark = st.text_input("Benchmark ticker", value="SPY").strip().upper()
    st.caption("SPY is the default. Enter another USD equity or ETF symbol to change it.")
    if st.button("Refresh market data"):
        st.cache_data.clear()
        st.session_state.pop("analysis", None)

st.caption("USD-quoted equities and ETFs only. Price return excludes dividends; total return uses dividend-adjusted history to model reinvestment. Fees, taxes, and account cash flows are excluded. Holdings value and unrealized P&L always use actual closing prices.")
source = "Enter holdings"
if mode == "My holdings":
    source = st.radio("Input method", ["Enter holdings", "Enter by allocation (optional)", "Upload CSV (optional)"], horizontal=True)

st.session_state.setdefault("selections", [])
positions, tickers = None, []
cash_balance = 0.0
allocation_rows = []
allocation_unit = "percent"
if mode == "My holdings":
    if source == "Enter by allocation (optional)":
        st.session_state.editor_signature = None
        total_invested = st.number_input("Total amount invested (USD)", min_value=0.01, value=st.session_state.get("saved_total_invested",10000.), step=100., key="total_invested")
        st.session_state.saved_total_invested = total_invested
        unit_label = st.radio("Allocate by", ["Percentage", "Dollar amount"], horizontal=True, key="allocation_unit")
        allocation_unit = "percent" if unit_label == "Percentage" else "dollars"
        st.caption("Use the original amount available to invest, not today's portfolio value. Quantity = invested dollars ÷ purchase price. Fractional shares are supported; unallocated funds remain cash. Use a split-adjusted average purchase price for stocks that have split.")
    else:
        cash_balance = st.number_input("Uninvested cash (USD)", min_value=0., value=0., step=100., key="manual_cash_balance")
valid = True
if source == "Upload CSV (optional)":
    uploaded = st.file_uploader("Upload positions CSV", type=["csv"])
    st.caption("Required columns: ticker, qty, avg_cost. Currency defaults to USD.")
    if uploaded is not None:
        try:
            positions = load_positions(uploaded)
            tickers = positions.ticker.tolist()
        except PortfolioError as exc:
            st.error(str(exc)); valid = False
else:
    with st.form("ticker_search"):
        query = st.text_input("Ticker or company name", placeholder="AAPL or Apple", key="search_query")
        search_clicked = st.form_submit_button("Search tickers")
    if search_clicked:
        st.session_state.pop("search_results", None)
        try:
            st.session_state["search_results"] = cached_search(query)
        except PortfolioError as exc:
            st.error(str(exc))
    results = st.session_state.get("search_results", [])
    if results:
        st.caption("Confirm the company and exchange before adding a symbol.")
        with st.form("confirm_symbol"):
            chosen = st.selectbox("Matching securities", range(len(results)),
                format_func=lambda i: f"{results[i]['ticker']} — {results[i]['name']} · {results[i]['exchange']}")
            add_clicked = st.form_submit_button("Add selected ticker")
        if add_clicked:
            try:
                identity = cached_instrument(results[chosen]["ticker"])
                if identity["ticker"] not in [r["ticker"] for r in st.session_state.selections]:
                    st.session_state.selections.append(identity)
                    st.session_state.pop("analysis", None)
                else:
                    st.info("That ticker is already selected.")
            except PortfolioError as exc:
                st.error(str(exc))
    selections = st.session_state.selections
    if selections:
        st.subheader("Your selections")
        st.dataframe(pd.DataFrame(selections).set_index("ticker"))
        remove = st.multiselect("Remove selected tickers", [r["ticker"] for r in selections])
        if st.button("Remove") and remove:
            st.session_state.selections = [r for r in selections if r["ticker"] not in remove]
            st.session_state.pop("analysis", None)
            st.rerun()
        tickers = [r["ticker"] for r in selections]
        if mode == "My holdings":
            if source == "Enter by allocation (optional)":
                st.session_state.setdefault("saved_allocations", {})
                st.session_state.setdefault("saved_purchase_prices", {})
                for ticker in tickers:
                    left, right = st.columns(2)
                    with left:
                        amount = st.number_input(f"{ticker} allocation ({'%' if allocation_unit == 'percent' else 'USD'})",
                            min_value=0., value=st.session_state.saved_allocations.get(f"{allocation_unit}_{ticker}",0.), step=1., key=f"allocation_{allocation_unit}_{ticker}")
                    with right:
                        purchase = st.number_input(f"{ticker} purchase price per share (USD)", min_value=0.,value=st.session_state.saved_purchase_prices.get(ticker,0.),step=1.,
                            key=f"purchase_price_{ticker}")
                    st.session_state.saved_allocations[f"{allocation_unit}_{ticker}"] = amount
                    st.session_state.saved_purchase_prices[ticker] = purchase
                    allocation_rows.append({"ticker":ticker,"allocation":amount,"purchase_price":purchase})
            else:
                st.caption("Enter quantity and average purchase cost per share (USD). Both are needed to calculate your profit/loss.")
                # Preserve previously entered values when the selected symbol list changes.
                saved = st.session_state.get("holding_values", {})
                rows = pd.DataFrame([{"ticker": t, "qty": saved.get(t, {}).get("qty"),
                                      "avg_cost": saved.get(t, {}).get("avg_cost")} for t in tickers])
                rows["qty"] = pd.to_numeric(rows["qty"], errors="coerce")
                rows["avg_cost"] = pd.to_numeric(rows["avg_cost"], errors="coerce")
                signature = tuple(tickers)
                if st.session_state.get("editor_signature") != signature:
                    st.session_state.editor_signature = signature
                    st.session_state.editor_base = rows
                edited = st.data_editor(st.session_state.editor_base, hide_index=True, disabled=["ticker"],
                    column_config={"qty": st.column_config.NumberColumn("Quantity", min_value=0., required=True),
                                   "avg_cost": st.column_config.NumberColumn("Average cost (USD)", min_value=0., required=True)},
                    key="holdings_" + "_".join(tickers))
                st.session_state.holding_values = edited.set_index("ticker").to_dict("index")
                positions = edited
        else:
            st.info("Research mode compares each ticker separately. No quantities, purchase costs, or hypothetical portfolio weights are required.")

if mode == "My holdings" and source == "Enter by allocation (optional)":
    try:
        entries = pd.DataFrame(allocation_rows, columns=["ticker","allocation","purchase_price"])
        positions, cash_balance, preview = allocations_to_positions(total_invested, entries, allocation_unit)
        tickers = positions.ticker.tolist()
        st.subheader("Calculated quantities")
        if not preview.empty:
            st.dataframe(preview.rename(columns={"qty":"Calculated quantity", "avg_cost":"Purchase price (USD)",
                "invested_amount":"Allocated amount (USD)"}).set_index("ticker"))
        st.metric("Unallocated cash", f"${cash_balance:,.2f}")
        if not tickers:
            st.info("All funds are currently unallocated cash. Add a positive allocation and purchase price to include securities.")
    except PortfolioError as exc:
        valid = False
        cash_balance = 0.
        st.error(str(exc))
if mode == "My holdings" and positions is None and cash_balance > 0 and source != "Upload CSV (optional)":
    positions = pd.DataFrame(columns=["ticker","qty","avg_cost","currency"])

fingerprint = json.dumps({"mode": mode, "source": source, "tickers": tickers,
    "positions": positions.to_json() if positions is not None else None, "benchmark": benchmark,
    "period": period, "interval": interval, "window": int(vol_window), "return_basis": return_basis, "annual_risk_free_rate": annual_risk_free_rate, "cash_balance":cash_balance, "version": 5}, sort_keys=True)
if st.button("Analyze", type="primary", disabled=(not tickers and (cash_balance <= 0 or positions is None)) or not valid):
    st.session_state.pop("analysis", None)
    try:
        if not benchmark:
            raise PortfolioError("Enter a benchmark ticker, such as SPY.")
        if mode == "My holdings" and not positions.empty:
            positions = normalize_positions(positions)
        with st.spinner("Retrieving historical prices and calculating results…"):
            result = analyze(mode, positions, tickers, benchmark, period, interval, int(vol_window), return_basis, annual_risk_free_rate, cash_balance)
        st.session_state.analysis = {"fingerprint": fingerprint, "result": result}
    except PortfolioError as exc:
        st.error(str(exc))

saved_analysis = st.session_state.get("analysis")
if saved_analysis and saved_analysis["fingerprint"] == fingerprint:
    result = saved_analysis["result"]
    with st.expander("Verified securities and benchmark"):
        st.dataframe(pd.DataFrame(result["identities"]))
    if mode == "My holdings":
        show_portfolio(positions, result["prices"], result["dividends"], int(vol_window), interval,
                       adjusted_prices=result.get("adjusted_prices"), return_basis=return_basis, cash_balance=cash_balance)
        show_diversification(result["diversification"],return_basis)
    show_comparison(result["comparison"])
else:
    st.info("Add tickers or upload holdings, then select Analyze. Results update when you analyze your current settings.")
