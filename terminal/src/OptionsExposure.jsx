import React from 'react';
import {num} from './data.js';
import {exposureMultiple,scaledQuantity} from './options-model.js';

export default function OptionsExposure({inputs,result,busy,onChange,disabled}) {
  const multiple=exposureMultiple(inputs);
  const legs=inputs.legs.map(leg=>({...leg,quantity:scaledQuantity(leg,multiple)}));
  const fee=num(inputs.fee_per_contract);
  const ready=Number.isFinite(fee)&&fee>=0&&legs.length>0&&legs.every(l=>l.quantity!==null&&Number.isFinite(num(l.premium))&&num(l.premium)>=0&&(l.kind==='stock'||Number.isInteger(num(l.multiplier))&&num(l.multiplier)>0));
  const debit=ready?legs.reduce((total,l)=>total+l.quantity*(l.kind==='stock'?1:num(l.multiplier))*num(l.premium)*(l.side==='buy'?1:-1)+(l.kind==='stock'?0:l.quantity*fee),0):null;
  const money=value=>new Intl.NumberFormat('en-US',{style:'currency',currency:inputs.currency,maximumFractionDigits:2}).format(value);
  const loss=!result?(busy?'Updating…':'Calculate to see risk'):!result.summary?'Depends on dates':result.summary.loss_unlimited?'Unlimited':money(result.summary.maximum_loss);
  return <section className="exposure-control" aria-labelledby="exposure-heading">
    <div className="exposure-heading"><div><h3 id="exposure-heading">Exposure multiplier</h3><p>Choose how many copies of your strategy to model.</p></div>
      <div className="segmented" role="group" aria-label="Exposure multiplier">{['1','2','3','5'].map(value=><button key={value} type="button" disabled={disabled} aria-pressed={multiple===Number(value)} onClick={()=>onChange(value)}>{value}×</button>)}</div>
    </div>
    <div className="options-summary exposure-summary" aria-live="polite">
      <div><span>Total entry {debit!==null&&debit<0?'credit':'cost'}</span><strong>{debit===null?'Enter leg prices':money(Math.abs(debit))}</strong><small>Includes entered option fees</small></div>
      <div><span>Maximum loss at expiry</span><strong>{loss}</strong><small>{!result?.summary?'Full risk appears after calculation':'For the entire scaled position'}</small></div>
      <div><span>Scenario profit / loss</span><strong>{result?money(result.scenario_pnl):busy?'Updating…':'Calculate to see P&L'}</strong><small>At your scenario underlying price</small></div>
    </div>
    <ul className="exposure-quantities" aria-label="Scaled position quantities">{legs.map((leg,i)=><li key={i}>Leg {i+1} · {leg.side==='buy'?'Buy':'Sell'} {leg.quantity===null?'—':leg.quantity.toLocaleString('en-US',{maximumFractionDigits:8})} {leg.kind==='stock'?'shares':`${leg.kind} contract${leg.quantity===1?'':'s'}`}</li>)}</ul>
    <p className="note">Quantities below define 1×. We scale every leg together, keeping the strategy proportions. This changes dollar exposure; it does not make the underlying price move {multiple}× or guarantee {multiple}× percentage returns.</p>
  </section>;
}
