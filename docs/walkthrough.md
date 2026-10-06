# Offline portfolio-project walkthrough

Use **New portfolio** before starting; the previous draft stays in recovery. These examples are invented and require no market downloads. Named saves retain assumptions; downloadable run files additionally preserve observations and outputs.

## Option valuation → strategy

1. Open Analytics Lab → Option pricing. Enter ticker `DEMO`, currency USD, European call, pricing date 2025-01-01, expiry 2026-01-01, spot 100, strike 100, volatility 20%, interest 5%, dividend yield 0%, 100 units per contract, one contract. Leave market premium blank.
2. Calculate. BSM premium should be approximately **10.450584 per unit**, or **1,045.0584 per contract**. The engine uses 365 calendar days.
3. In the hypothesis-transfer panel, confirm ticker DEMO and select **Keep current strategy & open hypothesis**. The inputs arrive in Options Lab. The theoretical value appears in a note; entry premium remains blank.
4. Enter a hypothetical entry premium of 10.50, target underlying 120, and expiry 2026-01-01. At expiry the call is worth 20 per unit; one 100-unit contract earns **950 before fees**. A target of 90 loses the **1,050 premium**. These are scenario values, not observed trades.
5. Compare 1× and 2× exposure. Contracts and dollar gains/losses double; this does not guarantee 2× the underlying return. Keep the scenario, then save a named portfolio if desired.

An American option price cannot be transferred as an equivalent European dated strategy. Futures pricing remains a valuation tool, not a futures trade-execution simulator.

## Equity hypothesis → underlying scenario

Fill an equity DCF and calculate. The transfer panel lists calculated cases/terminal methods. Select a positive fair-value estimate, enter an exact ticker, and choose your own target date. DCF present value does not imply the stock will reach that price on that date. Only the underlying target and your separately entered current market price transfer. Add the option's strike, expiry, volatility and entry premium yourself. Full existing scenario libraries require freeing a slot before transfer.

## Volatility and crypto

The default Volatility example contains a visible skew across strikes and three expirations. Run it with the default 50% maximum spread, inspect the two holes in the nearest expiry, and read their exclusion reasons. Raise minimum open interest to 501: all otherwise eligible example quotes are excluded. Empty results remain empty rather than generating a fitted surface.

In Crypto, load the offline example: 0.1 DEMO-BTC, 2 DEMO-ETH and 1,000 cash. Run it and compare the fixed quantities with the fully invested benchmark. DEMO-ETH has no purchase cost entered, so its unrealized P&L is unavailable; its value and period-return contribution still exist. Change the period or units and recalculate. Download the full result to preserve exact daily observations.

## Backtesting

Run both included backtesting examples. For stock rules, inspect signal dates and the next session's opening fill. Increase commission and slippage, recalculate and compare net value. For covered calls, inspect premium cash, short-option liability, rolling costs and expiry assignment separately. The options simulator prices options synthetically even when underlying history is downloaded.

This walkthrough demonstrates implementation and model transparency. It is not evidence that the illustrated strategies are profitable in actual markets.
