# Crypto spot and volatility methodology

## Crypto fixed holdings

`crypto_portfolio.py` accepts 1–10 distinct USD cryptocurrency spot tickers, positive units, optional nonnegative average cost, cash, benchmark and a historical interval of at most five years. Identity verification requires the provider's CRYPTOCURRENCY type, exact symbol and USD currency. No name guessing or stablecoin-as-USD conversion is performed.

Each required series must include every UTC calendar date, including weekends. The selected end precedes today's UTC date. Provider daily candles are requested with an exclusive end one day after the user's inclusive end. Duplicates, missing dates, nonfinite/nonpositive prices and non-midnight UTC timestamps stop the run. There is no filling, dropping or latest-price substitution.

Value at each close is `cash + sum(quantity × close)`, with the same units and zero-interest cash held throughout history. Period return starts at the first close; average cost changes only cost-basis P&L. A benchmark starts fully invested with the same initial total value. Fees, transactions, staking, token distributions, funding, borrowing and tax lots are excluded.

Volatility is sample standard deviation of close-to-close simple returns times `sqrt(365)`. Sharpe subtracts `(1 + annual_reference_rate)^(1/365) - 1` from each daily return, then annualizes mean/std by `sqrt(365)`. Zero-variance or insufficient samples yield null, not infinity. Drawdown uses the running daily closing-value maximum. CAGR uses the actual elapsed day count and 365 days per year, only when at least 365 days have elapsed. Leap days remain observations.

Full JSON includes settings, verified identities (market mode), retrieval timestamp, the exact observation series, results and a SHA-256 data fingerprint. `DEMO-BTC` and `DEMO-ETH` are deterministic invented prices over 2024–2025.

Replay a download:

```python
import json
import pandas as pd
from crypto_portfolio import CryptoRequest, crypto_analysis
with open('crypto-history.json') as f:
    saved = json.load(f)
history = {k: pd.DataFrame(v).set_index('date')['close']
           for k, v in saved['observations'].items()}
replay = crypto_analysis(CryptoRequest(**saved['settings']), history)
assert replay['summary'] == saved['summary']
assert replay['data_sha256'] == saved['data_sha256']
```

## Observed volatility grid

`volatility_surface.py` analyzes one underlying and up to four expirations. The existing delayed option-chain adapter supplies currency, underlying price, bid/ask, contract size, open interest, provider IV and last-trade metadata. The calculator derives its own European-equivalent IV from midpoint using BSM, ACT/365 and the user's annual continuous interest and dividend yields. It does not substitute the provider's IV.

The OTM view takes puts below spot and calls at/above spot. Calls-only and puts-only modes remain available. Quotes are excluded for missing/zero bids, crossed markets, spread `(ask-bid)/mid` beyond the chosen threshold, insufficient/unknown open interest when its filter is positive, unverified size/currency, invalid expiry, or failed pricing bounds. Duplicate strike/type/expiry keys fail rather than choosing among potentially different deliverables. Default rates of zero are explicit editable assumptions.

The IV solver checks the zero-volatility lower bound and finite-volatility upper bound before bisection over 0–300%. Seventy-five bisection iterations support numerical recovery; they do not establish market accuracy. Each expiry uses its own retrieved underlying spot, and the audit records it. Market valuation uses today's UTC date; quote time and spot may not be synchronized. Retrieval and last-trade timestamps cannot prove bid/ask freshness. American exercise and discrete dividends are not modeled.

Every strike/expiry cell comes from a retained quote. Missing cells stay blank. Smile lines connect displayed observations only; no interpolated pricing surface, extrapolation, static-arbitrage check or future-volatility forecast is supplied. The grid is for inspection, not automatic calibration of other engines.

`DEMO-IV` is fixed at 2025-01-01 with spot 100 and three invented expirations. Default OTM filtering yields 13 points; two selected-side quotes intentionally fail. The other 15 exclusions are unselected option sides. Exports include all retrieved observations and exclusion reasons. For an exact replay, pass the exported `as_of` date to `build_surface` alongside the exported settings and observations.

References: [OIC volatility skew overview](https://prd-web.optionseducation.org/news/volatility-skew-and-options-an-overview-1), [yfinance history interface](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.history.html), [Coinbase data conventions](https://help.coinbase.com/en/data-marketplace/getting-started/data-marketplace-products). Crypto quotes here come from Yahoo, not Coinbase.
