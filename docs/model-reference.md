# Detailed model reference

This reference preserves the calculation conventions of each module. Historical test counts below describe checks made when individual modules were introduced; see the main README for the current release checks.

## Options Lab

This local upgrade implements the calculator workflows reviewed on [Options Profit Calculator](https://www.optionsprofitcalculator.com/), while retaining the terminal’s own design, calculations, and local storage. It does not copy the website’s code or reproduce its account, subscription, advertising, or public hosting services.

**Build a position:** choose Options Lab → Strategy builder, then select a template. Choices cover long calls/puts, covered calls, cash-secured/naked puts, naked calls, protective puts, call/put/credit/vertical spreads, poor man’s covered calls, calendars, ratio backspreads, iron condors, butterflies, collars, diagonals/double diagonals, straddles/strangles, covered strangles, synthetic puts, reverse conversions, and custom strategies. Templates supply the leg structure; enter actual strikes, dates, premiums, and quantities. Editing legs can change the economic strategy from the template name.

- Use up to **eight option legs plus one stock position**. Each option has its own buy/sell direction, quantity, contract size, strike, expiration, premium, and IV. Premiums are per underlying unit; total option exposure is contracts × contract size. Stock legs use an explicit share quantity and entry cost, including short stock. Quantities are not automatically synchronized after editing.
- **Option chain:** enter an exact ticker and load its available expirations. Browse calls/puts, filter strikes, and select contracts into a new leg or an existing one. The table shows bid, ask, last trade, IV, volume, open interest, and last-trade timestamps. The default entry uses ask for buys and bid for sells; midpoint and last-trade entry are explicit alternatives. All selected values remain editable.
- Yahoo Finance data can be delayed, stale, incomplete, or rate-limited. Retrieval time is not the quote timestamp; the underlying timestamp and last option trade are shown separately. Crossed/missing markets have no usable midpoint. No example prices replace unavailable quotes. Option data is cached for five minutes; Refresh retrieves it again. Unknown contract sizes require manual entry. Provider `REGULAR`/`MINI` size labels do not verify every adjusted deliverable.
- Chains support USD/CAD when available from Yahoo. Manual scenarios also support these currencies. Every leg must reference the same underlying and currency; there is no FX conversion, and the equity tracker remains USD-only. Coverage is provider-dependent and does not guarantee every Canadian/MX contract.

**Calculate:** choose either Expiration payoff only or Dates & time value. The former works without current quotes or IV. Date-based analysis needs a current stock price, a calculation date, and each option’s expiration. Blank scenario date means the earliest expiration. Blank IV is inferred from the entered premium; chain selection uses provider IV when available. Invalid model prices require corrected inputs or explicit IV instead of silently substituting volatility.

The date-based model in `options_pricing.py` uses European Black–Scholes with continuous dividend yield. Rates default to zero assumptions; they are not live Treasury/dividend data. Volatility, risk-free rate, and yield are annual percentages. An IV shift of +5 means 25% becomes 30%. Each date is a close-of-date snapshot, with remaining calendar days divided by 365. This differs from the reference website’s morning snapshots. All dated estimates stop at the first expiry; longer-dated legs retain time value, so calendars/diagonals do not falsely expire every leg together. Final all-leg payoff, global max gain/loss, and probability are unavailable for mixed expirations because later settlement depends on the price path and exercise decisions.

For a common expiration, option values are intrinsic value: calls `max(S − K, 0)` and puts `max(K − S, 0)`. For each leg, signed quantity × (value − entry premium/cost) gives P&L. The round-trip fee allowance is entered per option contract and charged once in the modeled P&L, including on the calculation-date column. Stock fees are not modeled. **Break-even roots/ranges and global extrema use Decimal arithmetic over all nonnegative underlying prices**, independent of chart bounds. Unlimited loss/profit, entire zero-P&L ranges, and unusually profitable/losing manual price combinations are handled explicitly.

**Explore results:** the heatmap and values table show price against date; select a cell for exact P&L, return, and net position value. The line chart compares the calculation date, selected scenario date, and first expiry. Change the price range to zoom; global expiry metrics do not change. An optional stock comparison invests the entered comparison budget (or return capital basis) at the current underlying price, with fractional shares and no fees or dividend cash flows. It appears in the P&L line view. Download the scenario matrix as CSV or the line chart as SVG.

Return percentages use an explicitly entered capital basis when supplied. Otherwise the basis is a positive net entry debit including fees (optionally excluding stock cost), or a finite positive maximum expiration loss for credit positions. The cash-secured-put template uses strike cash collateral. Unlimited-risk credit positions require an entered basis for percentage returns. This denominator is not a broker margin calculation. Stock cost inclusion affects only the automatic denominator, not economic P&L.

Greeks are signed totals for the position at the calculation date/current stock price after the IV shift: delta per one-unit stock move; gamma as delta change per one-unit move; theta per calendar day; vega and rho per one percentage-point IV/rate change. Greeks are unavailable at zero time/volatility. Probability of nonnegative P&L at the common expiry uses a **risk-neutral lognormal** stock distribution with the separately entered probability IV (default 30%). It includes all profitable payoff regions and is a model assumption, not an empirical forecast or delta-based probability.

**Leverage & borrowing:** after Calculate strategy, the exposure panel reports gross contract/share notional, net and gross delta exposure, and signed effective leverage. Net delta exposure = current stock price × the position’s total delta; effective leverage = net delta exposure / the explicitly labeled capital basis. The approximate P&L for a +1% stock move is 1% of net delta exposure. These are local sensitivities, not fixed return multipliers; offsetting legs can have low net delta and substantial gross exposure. Date-based mode, current spot, and available deltas are needed for effective leverage. Expiration-only mode can show gross notional but does not invent a current delta.

The automatic leverage denominator is the full positive net entry debit including stock and fees, regardless of the separate return-basis stock-cost checkbox. An explicitly entered capital basis overrides it. The cash-secured-put template uses its stated collateral assumption. For other credit positions, maximum loss is **not** assumed to be deposited capital: enter a capital basis to get a leverage ratio. Increasing contracts and capital proportionally increases dollar exposure while leaving leverage unchanged.

Enable **Include borrowing costs** to model a constant loan funding part of a positive net entry debit. Enter the loan principal and annual borrowing rate; principal must be smaller than the debit, leaving positive own capital. Credit positions and zero/negative equity are not supported by this funding model. With funding enabled, both return and leverage use own capital = full entry debit − loan principal, and custom return-basis/stock-cost exclusions are suspended (their inputs are retained for when funding is disabled).

Interest is simple, noncompounding `principal × annual rate / 100 × elapsed days / 365`. Dated scenarios accrue from the calculation date through each grid/scenario date and the first expiry. Expiration-only calculations require explicit holding days, even without a calendar expiration. Zero rates and zero days are allowed; default zero is an assumption, not a market rate. Interest reduces P&L, shifts expiry break-evens and maximum loss, and feeds the common-expiry probability calculation. The loan principal is **not charged a second time as a loss**: net P&L = position value − full entry debit − interest; equity after repayment = position value − principal − interest. Signed position values and option Greeks themselves are unchanged; theta excludes the separately shown daily loan cost. Returns can be below −100%, and negative ending equity is displayed.

Funding is optional and off for existing scenarios. It does not change contract quantities, validate broker borrowing eligibility, or simulate collateral requirements, margin calls, forced liquidation, interest compounding, variable balances, or stock-borrow fees. Cash and stock comparison lines remain unfunded. Saved setups, comparisons, URL scenarios, browser recovery, and CSV exports retain/report funding assumptions and results. Version 3 snapshots prevent older clients from erasing these fields.

**Option Finder:** choose target price/date, up to four expirations, calls/puts, long/short options or debit/credit verticals, optional maximum expiration risk and minimum open interest, entry pricing, and a ranking by scenario P&L or return on capital. It uses one-contract positions and the same pricing assumptions/fees as the builder, excluding borrowing. Opening a Finder result disables borrowing; enable it in the builder for a funded analysis. Screening is bounded to the nearest 32 usable strikes of each option type to the midpoint of current and target prices, per selected expiry; it reports examined/eligible counts and shows the best 30 within that universe. Unusable quotes and unknown sizes are excluded. A risk limit excludes unlimited-loss positions. Open a result in the builder for full analysis; rankings are conditional on the entered scenario and do not establish a recommended trade.

**Keep and share:** Keep scenario stores up to 12 named setups within the current portfolio; Save portfolio writes the workspace and setups to the local database. Compare kept scenarios recalculates the first six with their own assumptions and displays failures per scenario without clearing them. Comparisons are not normalized for risk, currency, or date. Copy scenario link encodes only the current option inputs in a URL fragment; it opens in a running local tracker, not a public hosted site, and requires an explicit Load linked scenario action. Existing portfolio inputs are not applied silently from a link.

Version 1 option drafts and saved snapshots migrate their actual premiums, quantities, and matched stock positions into the new leg editor in expiration-only mode. Existing data is preserved. An older open client cannot overwrite a saved Options Lab using a newer engine version; it receives a refresh/copy message. A pre-options client omitting the options field preserves saved option inputs.

The model excludes American early exercise/assignment, discrete dividend effects, financing beyond the optional fixed loan described above, slippage, taxes, real-time feeds, and orders. It provides model values for vanilla options, not exercise or margin simulations. It does not value historical option chains or forecast future volatility.

References: [reference-site calculator assumptions](https://www.optionsprofitcalculator.com/faq.html), [reference Option Finder](https://www.optionsprofitcalculator.com/option-finder.html), [Society of Actuaries Greek/lognormal formulas](https://www.soa.org/globalassets/assets/Files/Edu/2018/exam-ifm-cbt-table.pdf), [yfinance Ticker/option-chain API](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.html), [OIC long call](https://www.optionseducation.org/strategies/all-strategies/long-call), and [OIC bull call spread](https://www.optionseducation.org/strategies/all-strategies/bull-call-spread-debit-call-spread).

Leverage references: [OIC delta and option-price sensitivity](https://www.optionseducation.org/referencelibrary/faq/option-price-behavior), [FINRA margin borrowing disclosure](https://www.finra.org/sites/default/files/Industry/p125981.pdf). The fixed-rate ACT/365 loan is this calculator’s explicit simplifying assumption.

### Saved portfolios and draft recovery

1. Enter a **Portfolio name** and select **Save portfolio** to keep the current workspace in the project folder.
2. Choose a name under **Saved portfolios**, then select **Load** to open that saved snapshot. Select **Analyze** to retrieve current market results.
3. Use **New portfolio** to start another account or strategy. **Make a copy** keeps the current inputs in a new draft with a suggested name; select Save portfolio to save it separately.
4. Edits are written to a recovery draft in this browser as you make them, even when quantities or prices are incomplete. A refresh or reopening the page restores the active draft. **Draft recovery** can also restore earlier workspaces after switching or starting a new portfolio.

Each snapshot preserves manual quantities and average costs, both percentage and dollar allocation inputs, purchase prices, total investment budget, cash, normalized CSV holdings, independent research lists, entry mode, all analysis settings, and Options Lab inputs, Finder settings, and kept scenarios. Analysis results, cached prices, and file-upload objects are not stored in the snapshot. Calculations always revalidate their inputs after loading; holdings and research also revalidate securities.

**Storage:** named snapshots are in `data/portfolios.sqlite3` beside the application. They survive browser-data deletion and are available from other browsers on this device. The database is excluded from source control and static web assets. Back up the `data` folder along with the project. No account or cloud service is involved; this feature is for the local terminal and does not change Streamlit.

**Recovery vs. Save:** browser drafts capture unfinished work; they do not overwrite the named snapshot until Save portfolio is selected. Browser drafts belong to the current browser and local address (host/port), and clearing that browser's site data removes them. If draft storage is disabled or full, a visible message asks you to save to the device before closing. Save failures keep the inputs on screen. Loading a saved snapshot keeps the previous draft available for recovery. The initial upgrade cannot recover inputs entered before recovery was installed; export any holdings/settings in the old page before its first refresh.

Names must be unique ignoring case, and can be changed by editing the name and saving the loaded portfolio. Updates use revision checks and atomic SQLite transactions: an older tab cannot silently overwrite a newer save. The conflict message offers Make a copy so both versions can be kept. Retrying an identical save after a lost response is safe. Corrupt or unsupported saved data is preserved and reported, never silently reset. There is no deletion workflow in this version.

### Local setup and development

The installed `.venv-terminal` uses the existing Python market-data packages while keeping the added web-server dependencies separate. To set up a new machine:

```bash
python3 -m venv .venv-terminal
.venv-terminal/bin/python -m pip install -r requirements-terminal.txt
.venv-terminal/bin/python launch_terminal.py --open
```

The server listens only on this device at `127.0.0.1:8502` and serves the compiled frontend and API together. An already-running terminal is reused by the launcher; it does not terminate other processes. To change the port, use `launch_terminal.py --port 8503 --open`.

For frontend changes, use Node 22.12+ and pnpm (this checkout was built with pnpm 11):

```bash
cd terminal
pnpm install --frozen-lockfile
pnpm dev
pnpm build
pnpm test
```

The development interface uses Vite at `127.0.0.1:5173` and proxies `/api` to the running Python service. `pnpm build` updates `terminal/dist`; reload the normal terminal page to use the new build. Restart the Python service after changing Python source files. The lockfile pins frontend dependencies, and only esbuild's installation script is enabled.

Run Python checks from the project root:

```bash
PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg .venv-terminal/bin/python -m unittest -q
```

Validation covers the existing 78 calculation/Streamlit tests, 11 API tests (including direct Streamlit parity for both return bases, all observation intervals, allocation/cash, CSV, exports, gaps, and refresh), 7 storage tests (durability, validation, conflicts, idempotency, corruption and write failures), 13 Options Lab tests (known strategy outcomes, exact break-even roots/ranges, chart-independent extrema, leg reconciliation, input/API validation, and older saved-data/client compatibility), 18 expanded option pricing/provider/storage tests, 13 leverage/funding tests (quantity scaling, signed/offsetting exposures, credit bases, loan/P&L reconciliation, interest across dates, invalid borrowing, and save compatibility), and 27 React interaction/recovery tests. React tests use deterministic API fixtures in `terminal/src/fixtures`; they are not included in the application build. Live verification also exercised Apple ticker search, exact-symbol validation, and a one-year AAPL/MSFT/SPY total-return analysis through the local HTTP API. The expanded options update also verified a live AAPL chain, dated calculation, and 2,112 Finder candidates across all four supported categories. No automated visual browser inspection was performed.

Architecture references: [FastAPI static files](https://fastapi.tiangolo.com/tutorial/static-files/), [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/), [Vite production builds](https://vite.dev/guide/build).

## Run

```bash
python -m pip install -r requirements.txt
python tracker.py --positions portfolio_example.csv --period 1y --interval 1d --vol_window 30
streamlit run streamlit_app.py
```

## Dashboard: no file required

1. Choose **My holdings** (default) or **Research tickers**.
2. Enter a company name or symbol, such as Apple or AAPL, and select **Search tickers**.
3. Confirm the company and exchange in the matching-securities list and select **Add selected ticker**. The app verifies the exact symbol, security type, and USD quote currency before adding it.
4. In holdings mode, enter quantity and average purchase cost per share. In research mode, only the selected tickers are required; each is compared separately, with no assumed portfolio weights.
5. Leave the benchmark as **SPY**, or enter another USD equity/ETF symbol. Choose a history period and daily, weekly, or monthly observations, choose **Price return** or **Total return (dividends reinvested)** under **Return basis**, then select **Analyze**.

CSV entry remains available under **Upload CSV (optional)** in holdings mode. Existing CLI usage is unchanged. Search requires the Search functionality provided by yfinance 0.2.66 or later; no API key is needed. Results depend on Yahoo availability and may be delayed or rate-limited, so search is not guaranteed to be instantaneous.

Downloads are cached for 15 minutes and security identities/searches for one hour. **Refresh market data** clears these caches. Changing selections, holdings, or settings hides previous results until you analyze again, so old results are not presented as current ones.

## Benchmark comparison and maximum drawdown

- All compared investments and the benchmark are aligned to the same first and last complete observation, then rebased to 100 at that common start. The actual dates are shown. A later-listed asset can shorten the comparison period.
- Research mode compares each selected ticker individually. Holdings mode compares modeled portfolio performance with the benchmark. Both sides always use the selected return basis.
- The table shows period return on the selected basis, maximum observed drawdown, and return minus the benchmark in percentage points. The return difference is not alpha and does not adjust for risk.
- Drawdown = observed value / running historical peak − 1. Maximum drawdown is the most negative observed value (for example, −20%). The portfolio snapshot uses its full requested available history; the comparison table uses the common comparison period, so these can differ.
- Missing interior observations remain gaps for every series in the comparison. No future or stale quotes are filled in. Missing observations can hide a deeper drawdown, and this is disclosed when gaps occur. Weekly/monthly data also cannot reveal declines between observations.
- Price return excludes dividends. Total return uses dividend-adjusted prices to approximate reinvested distributions. Both exclude taxes, fees, account cash flows, and trading costs.
- Download buttons provide normalized comparison history, drawdown history, and a summary as CSV. Comparison filenames include `price` or `total` to identify the basis. These CSV returns/drawdowns are decimal fractions (−0.20 = −20%); the displayed table shows percentages.

Data-provider reference: [yfinance Search documentation](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Search.html).

## Positions CSV

Required columns: `ticker`, `qty`, `avg_cost`. Optional `currency` defaults to `USD`.

```csv
ticker,qty,avg_cost,currency
AAPL,10,160,USD
MSFT,5,320,USD
VOO,8,420,USD
```

- Column names and tickers are normalized for whitespace and case.
- Quantities must be positive and finite. Average costs must be finite and non-negative.
- Invalid rows raise an error identifying the CSV row; they are never silently removed.
- Duplicate ticker rows are combined: quantities and costs are summed, and average cost is quantity-weighted.
- This version supports USD-quoted holdings only. Non-USD currency labels are rejected; the input currency must match the actual quote currency.
- Shorts, FX conversion, actual transaction accounting, and new asset classes are not implemented.

## Calculation behavior

- Security market value = shares × closing price; security unrealized P&L = security market value − purchase cost. Total portfolio value adds any uninvested cash.
- Historical values assume current quantities were held throughout the selected history. These are modeled holdings, not the account's actual realized performance.
- Price-return performance uses Close; total-return performance uses provider Adj Close growth factors. Separate closing prices continue to drive holdings valuation and unrealized P&L. Performance models are described below.
- Missing, non-finite, and non-positive quotes are unknown, never zero. A historical portfolio value is blank unless every holding has a valid quote on that date.
- Returns are blank on missing observations and immediately after a gap. Prices are not filled forward or backward, and multi-period changes are not reported as single-period returns.
- The snapshot uses the latest observation with valid quotes for every holding. Its date is displayed explicitly; if the newest observation is incomplete, a warning explains the older snapshot.
- Downloads with no prices, unavailable tickers, or no overlapping complete observation produce actionable errors.
- Volatility uses sample standard deviation of the latest **N consecutive return observations**, annualized by √252 for daily, √52 for weekly, or √12 for monthly data. The window is observations, not always days.
- If the final window is incomplete, volatility is unavailable with an explanatory message; an older valid window is not silently substituted.
- Dividend data is requested for all tickers. `dividends_last_year_by_ticker` is an informational **per-share** sum over available observations in the trailing calendar year ending at the requested history's final timestamp. Short histories provide only partial-year coverage; weekly/monthly observations are grouped by the provider. This informational dividend sum is never added to performance again: Adj Close already incorporates dividend adjustments in total-return mode. Unrealized P&L excludes dividend income.

## Price return and total return

The default remains **Price return**. To include reinvested distributions, select **Total return (dividends reinvested)** in the dashboard, or run:

```bash
python tracker.py --positions portfolio_example.csv --return_basis total --period 1y
```

A single download requests both `Close` and `Adj Close` with `auto_adjust=False`. Price return uses Close changes; total return uses Adj Close changes. Yahoo supplies historical split adjustments; the adjusted series also reflects dividend/distribution adjustments. Reinvestment results are estimates based on the provider's adjustments, not a cash ledger or guaranteed reproduction of a broker's reinvestment execution prices.

For portfolio total return, let the first date with complete Close and Adj Close for all holdings be the start. Initial dollars for each holding are `quantity × Close[start]`. Its modeled reinvested wealth is then:

`initial dollars × AdjClose[date] / AdjClose[start]`

Summing these values preserves actual starting market-value weights, models reinvestment within each holding, and avoids accidental equal weighting or dependence on arbitrary adjusted-price scales. There is no portfolio rebalancing. The starting date is shown; account purchases and cash flows during the history are not known. If benchmark coverage begins later, comparison charts rebase this existing modeled portfolio to the common comparison start; they do not reset its asset weights.

- Snapshot value and unrealized P&L always use Close × entered quantity, never adjusted prices. Switching return basis does not change them.
- The original portfolio-value chart remains based on entered quantities and Close. Total-return mode adds a normalized reinvested-performance chart, explicitly labeled as hypothetical performance rather than an account balance.
- Performance returns, volatility, and drawdown use the selected basis. Benchmark and research series use that same basis. Information about dividends is not added again.
- Missing adjusted history causes an actionable error for total return; it never silently falls back to price return. Interior gaps remain blank, and no returns are manufactured across gaps. Observed drawdowns can miss losses during missing observations.
- History exports distinguish `portfolio_value` (Close-based), `performance_value` (selected basis), `price_returns`, `returns` (selected basis), `drawdown` (selected basis), and `return_basis`. Metrics also report the performance start/end and missing performance observations.

Provider reference: [yfinance download options](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html) and [adjusted-price repair documentation](https://ranaroussi.github.io/yfinance/advanced/price_repair.html).

## Sharpe ratio and beta

Use **Annual risk-free rate (%)** in the sidebar to set a constant effective annual rate, then select **Analyze**. The default **0% is an assumption, not a live Treasury yield**. Rate changes invalidate prior results until you analyze again.

The comparison view reports annualized Sharpe and beta for every research ticker, the holdings portfolio when selected, and the benchmark itself. These ratios use the selected price/total-return basis and the entire available common comparison sample, independently of the rolling volatility window.

- Convert the entered annual rate to an observation rate: `rf_period = (1 + rf_annual) ** (1 / periods_per_year) - 1`.
- Annualized Sharpe = `mean(return - rf_period) / sample_std(return - rf_period) * sqrt(periods_per_year)`.
- Beta = `sample_cov(asset_return, benchmark_return) / sample_variance(benchmark_return)`. Beta is a dimensionless regression slope and is not annualized. Changing observation frequency changes the returns used to estimate it.
- Annualization uses 252 daily, 52 weekly, or 12 monthly observations. Square-root Sharpe annualization assumes no serial correlation and can be misleading when that assumption fails.
- Returns are calculated **before** missing rows are excluded. Each series must have valid quotes at both ends of the interval; gaps are never bridged. All displayed risk ratios share exactly the same complete return observations, including the benchmark.
- The actual calculation start/end and matched-return count are shown. The interval may contain excluded gaps; the count identifies the usable sample.
- At least two matched returns are required. Fewer than 30 generates a small-sample message. Two observations make the formulas calculable, not reliable estimates.
- A zero or numerically negligible excess-return standard deviation (≤1e-12) makes Sharpe unavailable; zero/negligible benchmark standard deviation makes beta unavailable. Missing ratios remain blank rather than showing zero or infinity. A constant asset can have beta zero when benchmark variance is positive.
- Changing the constant risk-free rate affects Sharpe but not beta. Negative annual rates greater than -100% are supported by the engine; the dashboard input starts at -99%.
- Risk CSV downloads include the ratios, matched-return count, dates, return basis, benchmark, observation interval, and annual/per-period risk-free assumptions. Ratios are **not percentages**; exported rates are decimal fractions (0.05 means 5%).

Method references: [William Sharpe: The Sharpe Ratio](https://web.stanford.edu/~wfsharpe/art/sr/SR.htm) and [Sharpe's performance worksheet instructions](https://web.stanford.edu/~wfsharpe/ws/wi_perf.htm).

## Optional allocation-based entry

In **My holdings → Input method**, choose **Enter by allocation (optional)**. Manual quantities and CSV upload remain available.

1. Enter the **total amount invested**: your original budget, not today's portfolio value.
2. Select percentage allocations or dollar amounts.
3. Search and add securities as before. Enter each allocation and its average purchase price per share. Use a split-adjusted average cost when stock splits have occurred; transaction dates/splits are not reconstructed here.
4. Review calculated fractional quantities and unallocated cash, then select **Analyze**.

`quantity = allocated dollars / purchase price`

For example: $10,000 total, 30% assigned to a security bought at $150, gives $3,000 / $150 = 20 shares. Dollar allocations work the same way. Fractional quantities retain their precision; there is no whole-share rounding or order execution. Allocations above the budget, negative/non-finite amounts, and zero/invalid purchase prices for funded holdings are rejected. Zero-allocation selections are excluded from the portfolio. An entirely unallocated budget is a cash-only portfolio.

Percentage and dollar inputs are kept separately so switching entry methods does not overwrite the other method's values. The terminal includes both in browser draft recovery and named portfolio saves. Streamlit inputs remain session-scoped.

### Cash treatment

- Unallocated dollars become a separate **Uninvested cash (USD)** allocation. Manual/CSV modes have an optional cash input as well.
- Cash is included in current portfolio value, modeled historical portfolio/performance values, total cost, benchmark comparisons, returns, volatility, Sharpe, and beta. Securities-only unrealized P&L is unchanged. Total cost equals securities cost plus cash.
- Cash is held constant throughout the modeled history and earns **0% interest**, even if a nonzero risk-free assumption is entered for Sharpe. No interest, dividends paid into cash, cash flows, or trade ledger are inferred.
- Cash has zero covariance/volatility contribution. Its correlation is undefined and it is excluded from the security correlation heatmap. Percentage risk shares are undefined when total modeled volatility is zero.
- Positions CSV exports contain securities only. **Download holdings settings** records the securities, cash amount, and return basis as JSON for reference; it is not an import workflow. Re-enter cash when using a positions CSV.
- CLI reports support `--cash 1000` in addition to the existing positions file, e.g. `python tracker.py --positions portfolio_example.csv --cash 1000`.

## Allocation, correlation, and risk contribution

Holdings results now include:

- **Current portfolio allocation:** dollar market values and weights based on the latest common actual Close for the holdings, including cash. These are current weights, not original invested percentages.
- **Correlation between holdings:** an interactive heatmap with tooltip values, using the selected price-return or total-return basis. It uses a shared complete return sample for all securities, computes returns before removing gaps, and never bridges missing quotes. Constant-return correlations remain blank. Correlation measures co-movement, not causality.
- **Contribution to portfolio volatility:** historical sample covariance with today's market-value weights. This is a static-weight estimate, distinct from the rolling buy-and-hold volatility shown in the snapshot. Dates, sample size, frequency, and warnings are displayed.

For annualized covariance matrix `Σ` and current security weights `w` (cash remains in the denominator):

- Model volatility: `σ = sqrt(wᵀ Σ w)`.
- Holding i's contribution to volatility: `w_i × (Σw)_i / σ`.
- Percentage share of risk: `contribution_i / σ`.

Covariance is annualized by 252/52/12 for daily/weekly/monthly observations. Contributions sum to annualized model volatility, and risk shares sum to 100% when volatility is positive. Negative contributions can occur when a holding reduces aggregate risk; these are retained, not clipped. A share can therefore exceed 100% if another share is negative. Cash contributes zero. All-zero model volatility and insufficient observations produce unavailable percentage risk contributions, not fabricated zeros. At least two matched returns are required, and samples below 30 carry a small-sample notice.

Downloads include allocation/risk contribution tables and the security correlation matrix, with analysis dates and return basis in the allocation report. Exported weights, volatility contributions, and risk shares are decimal fractions; the UI displays percentages/percentage points. The heatmap ranges from −1 to +1.

Formula reference: [MOSEK Portfolio Cookbook — Risk budgeting](https://docs.mosek.com/portfolio-cookbook/risk_parity.html).

## Outputs

The CLI writes these files to `outputs/` (override with `--out`):

- `positions_with_prices.csv`
- `portfolio_timeseries.csv`
- `portfolio_metrics.json`
- `portfolio_report.xlsx` (Positions, TimeSeries, Metrics)
- `portfolio_value_chart.png`

The dashboard shows the same engine results and provides positions/history CSV downloads. Existing saved example outputs predate this rebuild and are not refreshed automatically.

Metrics include the valuation date, data interval, missing-quote count, and warnings. `annualized_volatility_window_observations` replaces the ambiguous window label; the legacy `annualized_volatility_window_days` is retained for daily data and is null for other intervals.

## Verification

```bash
python -m unittest -v
```

The offline suite checks known-answer calculations, duplicate lots, missing and invalid prices, input validation, all three annualization intervals, simulated download successes/failures, report exports, Streamlit rendering, known peak-to-trough drawdowns, matched-date benchmark returns, complete direct-entry/research workflows, ex-dividend price drops, adjustment-scale invariance, missing adjusted prices, total-return export, and basis switching without changing valuation. It requires the packages in `requirements.txt` but does not use a live Yahoo connection.

Live verification during this update also confirmed Apple search, AAPL metadata, and a public AAPL/SPY history download. No existing saved example outputs were overwritten.

Total-return verification: 48 offline checks and a live 252-observation AAPL/SPY download passed; both price fields were available and valuations matched between modes.

Risk update verification: 59 offline checks passed, including known Sharpe values, beta values of 2/1/0/−0.5, interval conversion, zero variance, missing observations, and dashboard setting propagation.

Allocation update verification: 78 offline checks cover previous behavior plus percentage/dollar entry, fractional quantities, cash consistency, over-allocation rejection, shared-sample correlations, contribution reconciliation, negative risk contributions, and complete allocation-entry dashboard flows.

## Analytics Lab — manual equity valuation

Open **Analytics Lab** in the terminal. All forecasts, prices, peers, capital claims,
share counts, and valuation dates are entered by the user. No quote or financial
statement provider is consulted by `/api/analytics/valuation`.

- DCF: 1–10 complete future years; required Base and optional Bear/Bull cases;
  constant WACC; year-end discounting; perpetual-growth and/or exit EV/EBITDA
  terminal value. Each year derives FCFF from EBIT, operating tax, D&A, capex,
  and changes in operating working capital. Losses receive no immediate tax
  credit unless explicitly enabled. NOL carryforwards are not modeled.
- Equity bridge: add excess cash and other non-operating assets; subtract debt,
  preferred equity and non-controlling interests; divide by diluted common shares.
  Financial amounts **and shares** use the selected scale; stock prices never do.
- Comps: EV/EBITDA, EV/revenue, P/E, with user-entered peer values and target metrics.
  Require at least two eligible peers per method. Missing or nonpositive inputs
  exclude that peer only from the affected ratio. Peer quartiles use linear
  interpolation at `(n−1) × percentile`. P/E directly estimates common equity.
- Football field: min–max of included DCF cases, with a Base marker; peer 25th–75th
  percentile ranges, with median markers. These ranges are not confidence intervals
  and are not averaged into a single target. Negative equity estimates remain
  visible as bridge shortfalls, rather than being silently clipped to zero.
- Sensitivity: Base WACC ±1 percentage point in 0.5-point steps, against terminal
  growth ±1 point or exit multiple ±2×. Undefined combinations display missing
  values rather than zeros.
- Audit: cash-flow discounting, terminal contribution, equity bridge, excluded peers,
  CSV calculation trail, and a JSON download of inputs and results. Unfinished inputs
  survive browser recovery and named portfolio saves. Old clients that omit Analytics
  Lab cannot erase it from an existing named portfolio.

Inputs accept up to 12 decimal places, with finite magnitude bounds. The Python
engine uses 34 significant decimal digits internally before serializing numbers.
Display rounding is separate from valuation math. This is computational accuracy,
not a guarantee of fair value. The model does not provide an integrated financial
statement forecast, bank regulatory-capital model, midyear/stub-period convention,
automatic dilution, or an independently reviewed investment opinion.

Formula references: [NYU Stern DCF](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/lectures/val.html),
[terminal value](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/valquestions/termvalapproaches.htm),
and [relative valuation](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/lectures/multintr.htm).

Run `python -m unittest test_analytics` in the terminal Python environment and
`pnpm --dir terminal test` for valuation and workspace workflow checks.

## Analytics Lab — option and futures pricing

Select **Option pricing** or **Futures pricing** within Analytics Lab. These tools
use manual inputs only and keep their assumptions separately from equity valuation
and Options Lab strategies. Named portfolios and browser recovery keep incomplete
inputs. Existing equity drafts migrate without changing their assumptions; an old
page cannot overwrite newer derivatives data in a named portfolio.

- European vanilla options: Black–Scholes–Merton with continuous dividend yield,
  per-unit/contract/total premium, intrinsic value and analytical Greeks. Delta and
  gamma use a one-unit spot change; theta is per calendar day; vega and rho are per
  **one percentage point**. Greeks are per option unit, before contract scaling.
  An optional market premium gives European implied volatility in the range 0–300%
  when a solution exists; impossible quotes produce a note, not a fabricated IV.
- American vanilla options: Cox–Ross–Rubinstein binomial rollback with early exercise
  and continuous dividend yield. Choose 250/500/1,000 coarse steps; the reported
  premium uses twice that resolution. Results show both prices, their absolute
  difference, a same-tree European comparator and its Black–Scholes benchmark.
  The resolution difference is not an error bound. Early exercise premium compares
  American and European values on the same fine tree. No European Greeks are
  presented as American Greeks. Invalid risk-neutral probabilities are rejected.
- Futures: `F = S exp(carry × T)`. Equity/index carry is `r − income yield`; FX carry
  is `domestic rate − foreign rate`; commodity carry is `r + storage − convenience`.
  FX spot is domestic currency per one foreign unit. Commodity costs are annual
  proportional yields, not scheduled cash payments. For quoted index points, use
  the currency value per point as the multiplier. Contract and total **notional**
  are shown separately from delivery price; neither is an upfront cost or margin.
- Sensitivity: full repricing at spot ±10%/20%, crossed with volatility ±5/10
  percentage points (options) or funding rate ±0.5/1 percentage point (futures).
  Impossible tree cells display unavailable. Shading indicates distance from the
  entered estimate, not profit or probability.
- Audit: calendar days, discount factors, formula inputs, tree diagnostics, quote
  comparison, calculation CSV and a JSON download of inputs/results. Changes to
  inputs hide stale results; late responses cannot replace newer calculations.

Both endpoints (`/api/analytics/option`, `/api/analytics/futures`) use ACT/365 and
constant annual continuous rates, with a horizon up to 10 years. Inputs accept
explicit zero rates/yields and zero volatility; dates and required prices remain
blank until entered. Options at expiry return intrinsic value. Zero volatility
uses deterministic valuation, including possible interior optimal exercise for
American options; boundary Greeks are unavailable. The derivatives engines use
double precision and displays round separately from calculation output.

Model scope: no discrete cash-dividend schedule, stochastic rates or volatility,
volatility surface, exotic contracts, or options on futures. The futures model
equates forward and futures pricing under deterministic rates; it does not include
daily-settlement convexity, margin, Treasury delivery options, perpetual funding,
negative commodity prices or existing-position P&L. Quote gaps are conditional
model comparisons, not guaranteed trading profits or validated investment advice.

References: [Northwestern Black–Scholes notes](https://www.kellogg.northwestern.edu/faculty/hagerty/ftp/d65/lecture/Fall2004/Black_Scholes_revisedFall2004.pdf),
[Cox, Ross & Rubinstein (1979)](https://www.sciencedirect.com/science/article/pii/0304405X79900151),
and [CME equity futures fair value](https://www.cmegroup.com/trading/equity-index/fairvalue.html).
The CME example uses simple interest; this implementation consistently uses
continuous compounding.

Verification: `python -m unittest test_derivatives_pricing test_analytics
test_portfolio_store test_options_pricing test_options_leverage test_options_exposure
test_terminal` passes 82 checks; `pnpm --dir terminal test` passes 46 UI/workspace
checks. The new tests cover known BSM prices, put–call parity with dividends and
negative rates, Greek units, independent small-tree rollback, early exercise,
deterministic limits, invalid trees, carry identities, no-provider endpoints,
legacy drafts, named saves, errors, stale responses and export contents.

## Analytics Lab — Bond Analytics

Open **Analytics Lab → Bond Analytics**. This local, manual-input module supports
regular fixed-rate government and corporate bullet bonds with par redemption.
It needs no market-data subscription, API key or hosted service. Use **Government
bond example** or **Corporate bond example**, confirm loading, and select
**Calculate bond** for a reproducible, explicitly fictional demonstration.

The government example is a 4% five-year semiannual bond, settling on a coupon
date at a 4% yield: clean and dirty prices are both 100 per 100 face, accrued
interest is zero, and a 10,000 face position costs 10,000 before fees. The corporate
example has a 6% coupon, 4% benchmark yield and 150 bp spread, giving a 5.5% total
yield and approximately 102.160019 clean price per 100. These are model examples,
not observed market quotes. Both use settlement 2026-10-01 and maturity 2031-10-01.

### Inputs and outputs

- Price from yield; solve YTM from an entered **clean** price; or price from a flat
  benchmark yield plus spread. 100 bp = 1 percentage point. Use matching maturities
  and compounding conventions for benchmark comparisons. This is not a Z-spread,
  OAS, calibrated yield curve, or default-probability model.
- Annual, semiannual or quarterly regular coupons; Actual/Actual within the regular
  coupon period or US 30/360 with February-end adjustments. Coupons are anchored
  backward from maturity, either at its calendar day (clipping shorter months) or
  at month end. End-of-month mode requires a month-end maturity.
- Prices are quoted per 100 face. Dirty price = clean price + accrued interest;
  settlement cash = dirty price × total face / 100. Annual coupon, payment amount,
  current yield, nominal YTM and equivalent annual compounded yield are distinct.
- Macaulay duration, modified duration, convexity and position DV01. The latter is
  the approximate loss in currency for a +1 bp yield change, with dirty price as
  the sensitivity denominator. Risk amounts scale with face value; prices and
  normalized durations do not.
- Full yield-shock repricing (−200/−100/−50/0/+50/+100/+200 bp), compared with the
  duration-plus-convexity approximation. Benchmark/spread mode also provides a
  5×5 clean-price matrix. Shocks hold settlement and promised cash flows fixed;
  they are instantaneous value changes, not holding-period returns.
- Cash-flow dates, coupon/principal separation, discount factors, present values,
  day-count fractions, optional market quote comparison, price-solver residual,
  and complete CSV/JSON exports. Inputs persist in recovery drafts and named saves;
  Analytics schema version 3 migrates earlier labs without changing their inputs.
  An older page cannot save over newer bond inputs in an existing named portfolio.

### Pricing conventions and limits

For payment frequency `f`, annual decimal yield `y`, and fraction `a` of the current
coupon period remaining, discount cash flow `j` by `(1+y/f)^−(a+j)`, starting at
`j=0`. Actual/Actual accrued fraction is elapsed actual days / period actual days;
US 30/360 uses adjusted elapsed days / `(360/f)`. Accrued interest is that fraction
times coupon per period. When requested, a **single remaining payment** instead
uses simple discounting `1 / (1 + y*a/f)`. Duration and convexity use derivatives
of the selected formula; Macaulay time remains measured in coupon-period years.

The date of settlement must precede maturity by no more than 100 years. A coupon
on settlement is considered already paid and excluded from future cash flows.
There are no business-day adjustments, settlement-lag calculation, ex-coupon
periods or irregular coupon stubs. The generated dates must match the security's
terms. Conventions are explicit rather than inferred from government/corporate
labels. The module does not claim to reproduce every national quotation rule.

Yields and the monotonic price-to-yield solver are bounded at −20% to 100% annually.
An out-of-range solution is reported as unavailable (or an input error in yield
mode), never substituted with a boundary value. Where 30/360 leaves zero discount
time to the sole payment, yield cannot be uniquely inferred. Double-precision math
is used; displays round independently. A zero coupon input is supported under the
selected bond convention, not as a Treasury-bill discount-rate convention.

Cash flows assume payment in full. Credit spread shifts the discount yield; it
does not simulate default, recovery or liquidity. No callable, convertible,
amortizing, inflation-linked, floating-rate or mortgage-backed models are included.
Fees, taxes, reinvestment and financing are excluded. This is scenario research,
not a guaranteed fair value or investment return.

References: [Finance Canada bond pricing](https://www.canada.ca/en/department-finance/programs/financial-sector-policy/securities/securities-technical-guide/determining-bond-treasury-bill-prices-yields.html),
[FINRA yield and return](https://www.finra.org/investors/insights/bond-yield-return),
and [QuantLib US 30/360 conventions](https://github.com/lballabio/QuantLib/blob/master/ql/time/daycounters/thirty360.cpp).

Bond-specific tests: `python -m unittest test_bond_analytics`. Seventeen tests cover
par bonds, the Finance Canada worked example, accrual, leap years and month-end
schedules, coupon boundaries, negative-yield round trips, simple final periods,
derivative checks, credit-spread units, invalid inputs and saved-data protection.
Eight UI tests cover offline examples, price/yield modes, spread scenarios, draft
migration, named saves, stale results, failures and exports. These checks also run alongside the other lab and workspace tests.


## Backtesting — stocks and portfolios

Open **Backtesting** for a long/cash historical simulation of one USD stock/ETF
or a basket of up to ten securities. Choose exact tickers, initial percentage
allocations totaling 100%, starting capital, inclusive dates, a benchmark and a
trading rule. Dates must end before today in New York and span no more than ten
years. Prices and currencies are verified through the existing market provider.
The app remains local and needs no hosted service or paid subscription.

For a reproducible demonstration without a network connection: **Try offline
example → Load example → Run backtest**. DEMO-A, DEMO-B and DEMO-MKT are invented
weekday series, not real securities. The example covers 2024–2025, includes
synthetic warm-up data, and deliberately includes weekdays that may be market
holidays. Its performance is not investment evidence.

### Rules and execution

- **Moving average:** each asset is invested when its previous session's adjusted
  close is strictly above its simple moving average of N closes (2–252 sessions),
  otherwise in cash. Equality means cash. Execute at the *next* observed session's
  adjusted open, with slippage. Warm-up prices before the selected start can create
  the initial signal but are never part of the simulated P&L. A signal at the final
  close cannot create an order in the completed test.
- **Buy and hold:** invest at the first session's open, then hold. Every run includes
  both buy-and-hold of the same initial basket and a 100%-invested benchmark, using
  identical dates and cost assumptions. Comparing a basket with a different
  benchmark does not make their risk exposures equivalent.
- Allocate the starting capital into independent accounts for each ticker. Each
  retains its cash and profits; there are no inter-asset transfers or periodic
  rebalancing. Entries invest the account's available cash after costs. Exits sell
  all its units. Cash earns 0%; no shorting, borrowing or external cash flows.
- Buys fill at `open × (1 + slippage_bps/10000)`; sells at
  `open × (1 − slippage_bps/10000)`. Commission is traded fill-value times
  `commission_bps/10000`, plus the additional fixed order fee. Entry quantity is
  `(cash − fixed_fee) / (fill × (1 + commission_rate))`, preventing overspending.
  Slippage is already embedded in prices, not subtracted a second time. Entries
  unable to cover the fixed fee are skipped and exported. A sale whose fee exceeds
  proceeds stops the run rather than creating unmodeled borrowing.
- Final positions are marked at the final close, **not force-liquidated**; ending
  value excludes prospective exit costs. Open positions and cash are displayed.

### Prices, results and reproducibility

Yahoo data is requested with daily `auto_adjust=True`, no repair or back adjustment,
including an extra warm-up range and an exclusive provider end date one day beyond
the requested inclusive end. This models a **total-return proxy** with reinvested
distributions, using fractional adjusted units. Adjusted prices are not historical
executable dollar quotes, and adjusted units are not actual share counts. Dividend
cash timing, actual split quantities, tax lots and broker statements are not
reconstructed. Both opening and closing prices must be finite and positive.

All needed series share the union of their observed dates. Missing opening or
closing quotes, duplicate dates, insufficient warm-up and materially truncated
ranges stop the calculation; no forward filling, backward filling, interpolation
or silently dropping partial rows. The actual start/end dates are displayed to
account for weekends/holidays. Dates missing from every series remain undetectable
without an independent exchange calendar. The full run records the exact adjusted
observations used, including warm-up, and a SHA-256 fingerprint of those data.
Data is cached for 15 minutes; **Refresh data & run** fetches anew.

Outputs include net portfolio value, total return, daily-close drawdown, CAGR,
annualized volatility and Sharpe, average end-of-day invested exposure, order count,
closed-trade win rate, fees, slippage, all three trade ledgers and ending positions.
The ledger records signal date, signal close and moving average, reference open,
fill, units, commissions, slippage, cash remaining and net realized P&L.

Drawdown includes initial opening capital as a high-water mark, so entry costs
count. Volatility/Sharpe use sample standard deviation of close-to-close returns
and 252 sessions/year; the first partial opening-to-close session is excluded from
these risk statistics, but included in total P&L and drawdown. Sharpe subtracts
`(1 + annual_reference_rate)^(1/252) − 1`; this reference rate does not pay interest
on cash. Undefined ratios are null. CAGR uses inclusive calendar days and 365.25
days/year and is shown only for periods of at least 365 days. Win rate counts
strictly profitable completed buy/sell pairs after costs, excluding open trades.

**Download daily values** and **Download trades** export CSV with settings and the
data fingerprint. **Download full run** exports JSON containing settings, research
notes, data timestamps, observations, summaries, daily values, all ledgers and
skipped orders. Portfolio saves retain incomplete backtest assumptions alongside
holdings and all other labs; results must be recalculated. Old clients omitting
backtests cannot erase existing saved backtest inputs.

A full-run download can be replayed offline with the same engine version:

```python
import json
import pandas as pd
from backtesting import BacktestRequest, run_backtest

with open("backtest_run.json") as file:
    saved = json.load(file)
request = BacktestRequest(**saved["settings"])
history = {
    ticker: pd.DataFrame(rows).set_index("date")
    for ticker, rows in saved["observations"].items()
}
replayed = run_backtest(request, history)
assert replayed["data_sha256"] == saved["data_sha256"]
assert replayed["runs"] == saved["runs"]
```

### Scope and validation

The historical stock/ETF backtester does not model historical options, futures, crypto, bonds,
assignment, rolling, liquidity limits, settlement delays, taxes or market impact
beyond the entered slippage. A hand-selected universe and currently available
Yahoo history are not point-in-time or survivorship-free; unavailable delisted
securities and historical revisions can bias results. Avoid optimizing to the best
result on one period: record a hypothesis and test a separate holdout period.
Historical profitability does not establish future profitability.

The engine is independent of acquisition (`backtesting.py`), exposed through
`POST /api/backtest`; UI inputs use a separate saved draft (`backtest_store.py`).
No additional runtime dependencies were introduced.

Validation: `python -m unittest test_backtesting` covers hand-calculated ledgers,
next-session execution across overnight gaps, future-price perturbations,
commissions/slippage, allocation independence, initial-cost drawdown, risk
statistics, missing/duplicate observations, input bounds, deterministic replay,
provider request conventions, offline endpoints and save compatibility.
`pnpm --dir terminal test` includes six backtesting workflow tests for controls,
basket inputs, charts, comparator ledgers, recovery/saving, stale responses,
errors and reproducible exports. The relevant Python regression suite passes
118 tests and all 60 React tests pass.

Methodology references: [QuantConnect research guide](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/research-guide)
and [yfinance historical data interface](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.history.html).


## Options strategy simulation — covered calls

Open **Backtesting → Options strategy simulation**. Start with **Try covered-call
example → Load covered-call example → Run covered-call simulation** for a free,
fully offline demonstration. The displayed stock history is invented in this
mode; in downloaded mode the stock observations come from Yahoo Finance. In
both modes **all option premiums remain modeled**, with European BSM pricing,
a synthetic strike grid and expiry-only assignment assumptions.

Choose a fixed stock/call size, strike distance, holding period, volatility and
costs; optionally buy back calls before expiry and replace them next session.
Compare net account value with holding the same stock quantity. The tool shows
cash, stock and short-call liability separately; collected premium is not treated
as profit. A 3×3 volatility/cost table shows dependence on assumptions. Inputs are
saved independently of stock backtests and other labs. CSV/JSON exports label the
results as modeled; full JSON includes the exact stock observations for replay.

See [the complete methodology, offline replay and future data-provider interface](covered-call-simulation.md).
The simulator is research software, not evidence of executable historical options
profits or a substitute for observed options data. Twenty-two engine/provider
checks and six UI workflow tests cover the new module; the combined relevant
Python regression suite has 140 passing tests, and the React suite has 66.
