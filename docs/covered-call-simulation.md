# Covered-call research simulator

This project separates **historical stock/ETF backtesting** from **modeled options
strategy simulation**. The covered-call module is the second capability. It never
labels a Black–Scholes–Merton premium as an observed historical option quote.

## Run the free example

Start the terminal as described in the main README, then choose:

1. **Backtesting → Options strategy simulation**.
2. **Try covered-call example → Load covered-call example**.
3. **Run covered-call simulation**.

DEMO-CC contains deterministic invented weekday observations, including some market
holidays. No network, key, brokerage account or subscription is used. It is useful
for checking the UI and accounting, not for measuring investment performance.
The sample inputs are assumptions, not a recommended strategy.

For downloaded stock observations, select Yahoo Finance, enter an exact USD stock
or ETF ticker and completed dates, and choose the other inputs yourself. The API
verifies the stock identity/currency. It does not verify that a matching option
was listed or traded. There is no paid option-data connection in this version.

## Strategy and cash account

The user specifies capital and a fixed number of whole contracts. Each synthetic
call covers 100 stock units. At the first session's open, buy the fixed quantity
with stock slippage and commission. Capital must cover this purchase *before*
receiving the option premium. The stock-only comparator buys exactly the same
quantity with the same capital and stock costs. Both retain unused cash at 0%.

Write calls at a modeled opening bid. Select the strike from the **previous
close**: round `previous_close × (1 + OTM_percent/100)` upward to the specified
strike increment. An opening gap can make that strike in the money at entry.
The grid is synthetic, not evidence of listed strikes or available liquidity.
Premium remains in cash; it does not increase the fixed stock position.

At expiry close, a stock price **strictly above** strike delivers the stock for
`strike × units`, less the assignment fee. Do not also debit intrinsic value from
cash: the delivered stock already accounts for the obligation. At or below strike,
the call expires and stock is retained. After assignment, try to repurchase the
fixed quantity at the following open. If cash is insufficient, remain in cash and
retry on later sessions; do not borrow or reduce the requested lot size silently.

An optional early-roll rule buys the call back at the close with the requested
number of sessions remaining, then writes a new call at the following open.
The stock stays in place. If there is insufficient cash for the buyback and fee,
record a skipped roll and hold to expiry. This is a single roll attempt per call.
A call is not written if its modeled opening premium cannot cover its option fee.
All skipped actions are included in the ledger and exported.

## Pricing model and time convention

Premiums use the shared European Black–Scholes–Merton function, with user-entered
constant interest rate and dividend yield. Rates are continuously compounded.
Early exercise is not priced or simulated. Actual U.S. equity options usually
have American exercise, so especially around dividends this approximation can
differ materially from their prices and assignment outcomes.

The simulator uses **business time**: 252 observed sessions per year; an opening
is half a session before that session's close. A call lasting N sessions expires
at the close of the Nth session, including its entry session. Therefore:

- Opening time to expiry: `(N − 0.5) / 252` years.
- Closing time to expiry: `remaining_sessions / 252` years.
- At expiry: intrinsic value, with no residual time value.

This is not ACT/365 or an exchange expiration calendar. Weekend/holiday decay and
overnight calendar interest are not separately modeled. A contract may remain
open beyond the selected end date; its final liability is still marked. Dates
shown as planned expirations inside the range are labels from the session sequence,
not inputs from future stock prices.

Volatility can be fixed or based on a trailing proxy. The latter takes the sample
standard deviation of N daily log returns **ending before entry**, multiplies by
`sqrt(252)`, and adds the user-entered volatility premium in percentage points.
It is not observed or estimated option-market implied volatility. The resulting
assumption is bounded at 0–300% and frozen for that call until closure/expiry.
Subsequent calls can use a different trailing value. There is no calibrated smile,
term structure, stochastic volatility or forecast of future realized returns.

## Costs, data and distributions

Stock buys use `open × (1 + stock_slippage_bps/10000)`. Stock commission is the
traded fill value times `stock_fee_bps/10000`. Calls are sold at
`model × (1 − option_half_spread_percent/100)` and bought back at
`model × (1 + option_half_spread_percent/100)`. Each option opening or early
buyback pays the per-contract fee. Assignment uses strike proceeds without a
market stock sale/spread; its separate per-contract fee applies. Worthless expiry
has no closing transaction fee. Fees and spread effects enter account value once.

Stock history uses Yahoo's split-adjusted **Open/Close**, with `auto_adjust=False`
and actions enabled. Do not substitute dividend-adjusted total-return prices.
Recorded dividends/capital-gain distributions are credited on ex-date to units
owned at the previous close, before that day's purchases. This approximates cash
availability earlier than actual payment dates. The BSM dividend-yield input is a
separate pricing assumption; it does not create a second distribution credit or
inspect future dividend records.

The provider's price scale may reflect later split adjustments. These are synthetic
100-unit contracts on that scale, not reconstructed historical option deliverables.
Ranges with a split **inside the test** are rejected. Mergers, special deliverables,
spinoffs, payment-date accounting, taxes, funding, cash interest and actual option
exercise/assignment notices are unsupported.

Positive finite opening/closing quotes and finite non-negative action observations
are required. Duplicate dates, missing required fields, insufficient warm-up and
materially truncated ranges stop calculation. No missing quote is interpolated or
filled. With no independent exchange calendar, a session absent from the entire
supplied series cannot be detected. This can affect the session-based expiry clock.
Current provider history is not point-in-time or survivorship-free; ticker selection,
delistings and revisions can bias a historical experiment.

## Results and sensitivity

`Net account value = cash + stock units × close − short-call model liability`.

The charts compare net value and daily-close drawdowns. Gross premium is disclosed
separately and is **not profit**. Open positions are marked without hypothetical
end-of-test liquidation or exit costs. The final cash/stock/liability reconciliation
is shown explicitly. The ledger exposes cash changes, included fees and stock units
after each action. Each completed call records premium, fees and exit option value.
For assignment, that option value is foregone upside (intrinsic), an attribution
entry rather than a second cash debit. It excludes the stock's P&L.

Risk metrics reuse the stock backtest definitions: sample close-to-close returns,
252-session annualization, 0% Sharpe reference, initial capital in drawdown peaks,
and inclusive-calendar-day CAGR only for ranges of at least 365 days. The first
partial session is included in total P&L and drawdown, but excluded from close-to-
close volatility/Sharpe. Undefined ratios remain null, not zero.

The 3×3 table reruns the whole strategy at assumed-volatility shifts of −5/0/+5
percentage points and at 0×/1×/2× all cost settings. Positions/cash paths can change
because of calls skipped after fees, assignment and repurchase/roll affordability.
Unfunded scenarios are labeled unavailable, never silently replaced by base values.
The table is sensitivity analysis, not a confidence interval or probability claim.

## Save, export and replay

Named portfolios and browser recovery preserve incomplete simulator inputs,
independently of stock backtests, holdings and valuation labs. Old clients that
omit the simulator fields cannot erase them from existing saves.

CSV and full-run JSON filenames include `MODELED`. Both record assumptions and
the explicit result type. JSON additionally includes every stock observation used,
including warm-up, a SHA-256 fingerprint, all cycle/event/daily records for both
paths, and the sensitivity results. This allows offline replay without calling a
market-data provider:

```python
import json
import pandas as pd
from covered_call_simulation import CoveredCallRequest, run_covered_simulation

with open("covered_call_MODELED_run.json") as file:
    saved = json.load(file)
request = CoveredCallRequest(**saved["settings"])
history = pd.DataFrame(saved["observations"]).set_index("date")
replayed = run_covered_simulation(request, history)
assert replayed["data_sha256"] == saved["data_sha256"]
assert replayed["covered_call"] == saved["covered_call"]
assert replayed["stock_only"] == saved["stock_only"]
assert replayed["sensitivity"] == saved["sensitivity"]
```

Use the same engine version for exact replay. Do not publish downloaded market
datasets without checking the provider's redistribution rights. The checked-in
fixture contains invented prices only. Local downloaded validation results live
under ignored `.runtime/`, and saved user portfolios under ignored `data/`.

## Future historical option data

`option_history.py` defines the typed `HistoricalOptionsProvider` interface with
contract discovery and per-contract quotes at a supplied decision timestamp.
Contract metadata includes strike, expiration, multiplier, exercise style and
whether its deliverable is standard. Quotes distinguish observation time from
availability time, carry their provider name and expose actual bid/ask values.
Validation rejects crossed/nonfinite quotes, future/unavailable observations,
naive timestamps and stale records. A missing quote is `None`, never a BSM fallback.

This is an extension contract, **not a connected historical-data mode**. Before
using observed quotes in a backtest, implement provider-specific contract selection,
expiry/calendar handling, exercise/assignment and data coverage checks. Preserve
the separation between observed and modeled results. Add adapter contract tests
against a permitted fixture before enabling it in the UI.

Future adapters must read secrets from environment variables or local secret
storage, never from saved assumptions, result JSON or committed code. `.env`,
`.env.*`, local backups, runtime outputs and saved account data are excluded by
`.gitignore`. No credential, subscription or provider SDK is bundled here.

## Verification and references

Run `python -m unittest test_covered_call_simulation` and
`pnpm --dir terminal test --run src/CoveredCallLab.test.jsx`.

Tests cover premium/liability accounting, physical assignment, contract scaling,
distributions, cash-constrained rebuys/rolls, cost accounting, lagged volatility,
future-price perturbations, terminal marks, sensitivity, split/missing-data errors,
snapshot replay, API/data acquisition, save compatibility, provider timestamp/quote
validation and the UI workflows/exports. No market network is needed by these tests.

References: [OIC covered calls](https://www.optionseducation.org/strategies/all-strategies/covered-call-buy-write)
and [OIC assignment guidance](https://www.optionseducation.org/referencelibrary/faq/options-assignment).
This simulator does not reproduce Cboe's BXM methodology and should not be presented
as evidence of achievable historical option profits.
