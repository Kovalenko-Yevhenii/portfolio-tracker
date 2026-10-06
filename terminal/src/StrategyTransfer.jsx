import React,{useState} from 'react';
import {Panel} from './components.jsx';
import {decimal} from './data.js';
import {equityTransfer,optionTransfer} from './strategy-transfer.js';
export default function StrategyTransfer({type,inputs:a,result,onTransfer,disabled=false}){
  const [symbol,setSymbol]=useState(type==='option'?a.symbol:''),[target,setTarget]=useState(''),[choice,setChoice]=useState('0'),[error,setError]=useState('');
  const equity=type==='equity',rows=result.dcf||[],selected=rows[Number(choice)];
  function transfer(){try{const next=equity?equityTransfer(a,selected,symbol,target):optionTransfer(a,result,symbol);const problem=onTransfer(next);if(problem)setError(problem);}catch(e){setError(e.message);}}
  return <Panel title="Use this hypothesis in Options Lab"><div className="transfer-fields">
    <label>Strategy ticker<input aria-label="Strategy ticker" maxLength={40} value={symbol} onChange={e=>setSymbol(e.target.value)}/></label>
    {equity&&<><label>Fair-value case<select aria-label="Fair-value case" value={choice} onChange={e=>setChoice(e.target.value)}>{rows.map((r,i)=><option key={i} value={i}>{r.case} · {r.method} · {decimal(r.price)} {a.currency}</option>)}</select></label><label>Hypothesis target date<input aria-label="Hypothesis target date" type="date" value={target} onChange={e=>setTarget(e.target.value)}/></label></>}
  </div><p className="note">{equity?'The selected DCF estimate becomes a hypothetical underlying target, not a forecast with a known arrival date. Choose your own horizon. Option strike, expiry and entry premium remain for you to enter.':'Transfers the option assumptions. Only your separately entered market premium becomes the entry price; otherwise that field remains blank. The theoretical value is kept as a reference note.'} Your current strategy is kept as a scenario before opening the new draft. Market identity and quote freshness must be checked separately.</p>
    {(!equity&&a.exercise!=='european')&&<p className="note">American pricing is not transferable to the European dated-strategy engine.</p>}
    {error&&<p role="alert" className="error">{error}</p>}<button className="primary" disabled={disabled||(equity&&!rows.length)||(!equity&&a.exercise!=='european')} onClick={transfer}>Keep current strategy & open hypothesis</button>
  </Panel>;
}
