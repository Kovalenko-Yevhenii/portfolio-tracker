import React from 'react';
import BondLab from './BondLab.jsx';
import EquityValuation from './EquityValuation.jsx';
import DerivativesLab from './DerivativesLab.jsx';
import './derivatives.css';
export default function AnalyticsLab({inputs,onChange,onTransfer,disabled=false}){
  const tool=inputs.tool||'equity';
  return <div className="analytics-lab">
    <div className="section-heading"><div><h1>Analytics Lab</h1><p>Build a hypothesis. Price it from your own assumptions.</p></div><span className="eyebrow">User inputs only</span></div>
    <div className="analytics-tool-switch segmented" role="group" aria-label="Analytics tools">{[['equity','Equity valuation'],['option','Option pricing'],['futures','Futures pricing'],['bond','Bond Analytics']].map(([id,label])=><button type="button" key={id} aria-pressed={tool===id} disabled={disabled} onClick={()=>onChange({...inputs,tool:id})}>{label}</button>)}</div>
    {tool==='equity'?<EquityValuation inputs={inputs} onChange={onChange} onTransfer={onTransfer} disabled={disabled}/>:tool==='bond'?<BondLab inputs={inputs.bond_pricing} onChange={value=>onChange({...inputs,bond_pricing:value})} disabled={disabled}/>:<DerivativesLab onTransfer={onTransfer} key={tool} type={tool} inputs={inputs[tool+'_pricing']} onChange={value=>onChange({...inputs,[tool+'_pricing']:value})} disabled={disabled}/>}
  </div>;
}
