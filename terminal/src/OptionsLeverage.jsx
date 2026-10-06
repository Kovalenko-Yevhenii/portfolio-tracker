import React from 'react';
import {Panel,Metric} from './components.jsx';
import {decimal} from './data.js';

export default function OptionsLeverage({result,money}) {
  const l=result.leverage,f=result.financing;
  if(!l)return null;
  const multiple=v=>v==null?'Unavailable':decimal(v)+'×';
  return <>
    <Panel title="Leverage & exposure">
      <div className="metrics leverage-metrics">
        <Metric label="Effective leverage" value={multiple(l.effective_leverage)} note={l.one_percent_move_pnl==null?'Use date-based mode with a current stock price and positive capital.':`A +1% stock move ≈ ${money(l.one_percent_move_pnl)} P&L, locally`}/>
        <Metric label="Net delta exposure" value={money(l.net_delta_notional)} note="Signed stock-equivalent exposure at the calculation date"/>
        <Metric label="Gross delta exposure" value={money(l.gross_delta_notional)} note="Absolute exposure of all legs before offsets"/>
        <Metric label="Leverage capital basis" value={money(l.capital)} note={l.capital_label}/>
      </div>
      <p className="note">Effective leverage = net delta exposure ÷ capital basis. A negative value means bearish sensitivity. Near-zero net delta can hide large offsetting exposures and other risks. This is a local estimate: delta changes with price, time, and volatility. It is not a fixed multiplier of future returns.</p>
      <p className="note">Gross contract/share notional: {money(l.gross_notional)} · gross delta exposure ÷ capital: {multiple(l.gross_delta_leverage)}. Credit positions need an explicit capital basis, except the cash-secured-put collateral assumption. Maximum loss alone is not treated as deposited capital. Stock cost is included in the automatic leverage basis even if excluded from the return basis.</p>
    </Panel>
    {f?.enabled&&<Panel title="Borrowing breakdown">
      <div className="options-summary financing-summary"><div><span>Own capital at entry</span><strong>{money(f.own_capital)}</strong></div><div><span>Loan principal</span><strong>{money(f.principal)}</strong></div><div><span>Interest to scenario date</span><strong>{money(f.scenario_interest)}</strong></div><div><span>Equity after repayment</span><strong className={f.scenario_equity<0?'negative':''}>{money(f.scenario_equity)}</strong></div></div>
      <p className="note">Position P&L before interest: {money(f.scenario_gross_pnl)} − interest {money(f.scenario_interest)} = net scenario P&L {money(result.scenario_pnl)}. Interest uses {decimal(f.annual_rate)}% per year for {f.scenario_days} days; the daily cost is {money(f.daily_interest)}. Interest through first expiry: {money(f.horizon_interest)}.</p>
      <p className="note">The loan funds part of the entry debit. Repayment reduces equity; it is not charged again as a trading loss. Returns use own capital and may fall below −100%. The figures assume the loan and positions remain open for the modeled period; no forced liquidation or broker margin rules are simulated.</p>
    </Panel>}
  </>;
}
