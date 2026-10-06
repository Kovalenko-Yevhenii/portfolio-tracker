import React,{useEffect,useRef,useState} from 'react';
import {Search,RefreshCw} from 'lucide-react';
import {api,decimal} from './data.js';
import {Panel} from './components.jsx';
import {fromContract} from './options-model.js';

export default function OptionChain({inputs,onQuote,onUnderlying,disabled=false}) {
  const [expiries,setExpiries]=useState([]),[expiry,setExpiry]=useState(''),[chain,setChain]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [kind,setKind]=useState('call'),[strike,setStrike]=useState(''),[pricing,setPricing]=useState('natural'),[target,setTarget]=useState(()=>{const i=inputs.legs.findIndex(l=>l.kind!=='stock'&&(!l.strike||!l.premium));return i<0?'new':String(i);}),[page,setPage]=useState(0);
  const symbol=inputs.symbol.trim().toUpperCase(),active=useRef(symbol),run=useRef(0);active.current=symbol;
  useEffect(()=>{run.current++;setChain(null);setExpiries([]);setExpiry('');setError('');setBusy(false);},[symbol]);
  useEffect(()=>()=>{run.current++;},[]);
  useEffect(()=>setPage(0),[kind,strike,chain]);
  async function load(refresh=false,selected='') {
    const id=++run.current;setBusy(true);setError('');setChain(null);
    try{
      let dates=expiries;
      if(!selected){const meta=await api(`/options/expirations?symbol=${encodeURIComponent(symbol)}&refresh=${refresh}`);dates=meta.expirations;if(id!==run.current||symbol!==active.current)return;setExpiries(dates);}
      const exp=selected||dates.find(d=>d>new Date().toISOString().slice(0,10))||dates[0];
      const data=await api(`/options/chain?symbol=${encodeURIComponent(symbol)}&expiration=${encodeURIComponent(exp)}&refresh=${refresh}`);
      if(id===run.current&&symbol===active.current){setExpiry(exp);setChain(data);onUnderlying(data);}
    }catch(e){if(id===run.current&&symbol===active.current)setError(e.message);}
    finally{if(id===run.current)setBusy(false);}
  }
  const rows=chain?.contracts.filter(r=>r.kind===kind&&(!strike||String(r.strike).includes(strike)))||[];
  function choose(row,side){if(target!=='new'&&!inputs.legs[Number(target)])return;onQuote({...fromContract(row,side,pricing),quote_note:`${chain.symbol} · ${fromContract(row,side,pricing).quote_note} · fetched ${chain.fetched_at}`},target,chain);}
  return <Panel title="Option chain" action={<span className="eyebrow">Yahoo Finance · delayed</span>}>
    <div className="option-tool-row"><button type="button" className="primary" disabled={!symbol||busy||disabled} onClick={()=>load(false)}><Search size={16}/>{busy?'Loading chain…':'Load option chain'}</button><button type="button" aria-label="Refresh option chain" disabled={!symbol||busy||disabled} onClick={()=>load(true)}><RefreshCw size={16}/></button><label>Expiration<select aria-label="Chain expiration" value={expiry} disabled={busy||!expiries.length} onChange={e=>{setExpiry(e.target.value);load(false,e.target.value);}}>{!expiries.length&&<option value="">Load a ticker first</option>}{expiries.map(d=><option key={d}>{d}</option>)}</select></label><label>Show<select aria-label="Chain option type" value={kind} onChange={e=>setKind(e.target.value)}><option value="call">Calls</option><option value="put">Puts</option></select></label><label>Strike filter<input aria-label="Filter chain strikes" value={strike} placeholder="All strikes" onChange={e=>setStrike(e.target.value)}/></label></div>
    <div className="option-tool-row"><label>Entry pricing<select aria-label="Chain entry pricing" value={pricing} onChange={e=>setPricing(e.target.value)}><option value="natural">Buy at ask / sell at bid</option><option value="mid">Bid/ask midpoint</option><option value="last">Last trade (may be stale)</option></select></label><label>Add to<select aria-label="Chain destination leg" value={target} onChange={e=>setTarget(e.target.value)}><option value="new">New option leg</option>{inputs.legs.map((l,i)=>l.kind!=='stock'&&<option key={i} value={String(i)}>Replace leg {i+1} · {l.side} {l.kind}</option>)}</select></label></div>
    {!symbol&&<p className="note">Enter an underlying ticker above to browse its option contracts.</p>}{error&&<p className="banner error" role="alert">{error}</p>}
    {chain&&<><p className="note"><strong>{chain.name} · {chain.symbol}</strong> · {chain.currency} {decimal(chain.spot)} · underlying quote {chain.underlying_time?new Date(chain.underlying_time).toLocaleString():'time unavailable'} · retrieved {new Date(chain.fetched_at).toLocaleString()}</p>
      <div className="table-wrap option-chain-table"><table aria-label="Available option contracts"><thead><tr><th>Strike</th><th>Bid</th><th>Ask</th><th>Last</th><th>IV</th><th>Volume</th><th>Open interest</th><th>Last trade</th><th>Use contract</th></tr></thead><tbody>{rows.slice(page*40,(page+1)*40).map(r=><tr key={r.contract_symbol}><td className="mono">{decimal(r.strike)}</td><td>{decimal(r.bid)}</td><td>{decimal(r.ask)}</td><td>{decimal(r.last)}</td><td>{r.iv===null?'—':decimal(r.iv)+'%'}</td><td>{decimal(r.volume,0)}</td><td>{decimal(r.open_interest,0)}</td><td>{r.last_trade?new Date(r.last_trade).toLocaleString():'Unavailable'}</td><td><div className="button-group">{['buy','sell'].map(side=><button type="button" key={side} disabled={disabled||(!r.valid_market&&pricing!=='last')||(pricing==='mid'?r.mid===null:pricing==='last'?r.last===null:r[side==='buy'?'ask':'bid']===null)||r.currency!==chain.currency} aria-label={`${side==='buy'?'Buy':'Sell'} ${r.kind} ${r.strike}`} onClick={()=>choose(r,side)}>{side==='buy'?'Buy':'Sell'}</button>)}</div></td></tr>)}</tbody></table></div>
      {!rows.length&&<p className="note">No contracts match this filter.</p>}
      <div className="option-tool-row"><button type="button" disabled={page===0} onClick={()=>setPage(p=>p-1)}>Previous</button><span className="muted">{rows.length?`${page*40+1}–${Math.min(rows.length,(page+1)*40)} of ${rows.length}`:'0 contracts'}</span><button type="button" disabled={(page+1)*40>=rows.length} onClick={()=>setPage(p=>p+1)}>Next</button></div><p className="note">{chain.note} Prices remain editable after selection. Unknown contract sizes require manual entry.</p>
    </>}
  </Panel>;
}
