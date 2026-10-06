import React,{useEffect,useRef,useState} from 'react';
import {LineChart,Line,XAxis,YAxis,Tooltip,Legend,ResponsiveContainer,CartesianGrid} from 'recharts';
import {Panel} from './components.jsx';
import {api,decimal,money,percent,download} from './data.js';
import {cryptoExample,cryptoPayload,surfacePayload} from './research-model.js';
import './research.css';

function useCalculation(path,payload){
  const key=JSON.stringify(payload),latest=useRef(key),run=useRef(0);
  const [saved,setSaved]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  latest.current=key;
  useEffect(()=>()=>{run.current++;},[]);
  useEffect(()=>setError(''),[key]);
  async function calculate(e,refresh=false){
    e.preventDefault();const id=++run.current;setBusy(true);setError('');setSaved(null);
    try{const data=await api(path,{...payload,refresh});if(id===run.current&&key===latest.current)setSaved({key,data});}
    catch(e){if(id===run.current&&key===latest.current)setError(e.message);}
    finally{if(id===run.current)setBusy(false);}
  }
  return {calculate,busy,error,result:saved?.key===key?saved.data:null,stale:!!saved&&saved.key!==key};
}
function Status({run}){return <>{run.busy&&<p className="banner" role="status">Calculating…</p>}{run.error&&<p className="banner error" role="alert">{run.error}</p>}{run.stale&&<p className="banner">Inputs changed. Calculate again to refresh results and downloads.</p>}</>;}
function RunButtons({run,source,label}){return <div className="research-actions">{source==='market'&&<button type="button" disabled={run.busy} onClick={e=>run.calculate(e,true)}>Refresh data & calculate</button>}<button className="primary" type="submit" disabled={run.busy}>{label}</button></div>;}
function Export({result,name}){return <button onClick={()=>download({name,mime:'application/json',content:JSON.stringify(result,null,2)})}>Download inputs, data & results</button>;}
const colors=['#4cc9b0','#e8b86e','#8e9fff','#ee87b5'];
function Chart({data,x,series,label}){return <div className="research-chart" role="img" aria-label={label}><ResponsiveContainer width="100%" height={300}><LineChart data={data}><CartesianGrid stroke="#26333f"/><XAxis dataKey={x} minTickGap={35} stroke="#9baab8"/><YAxis stroke="#9baab8" domain={['auto','auto']} tickFormatter={v=>decimal(v,0)}/><Tooltip contentStyle={{background:'#121b25',border:'1px solid #354454',borderRadius:8}} labelStyle={{color:'#e7edf3'}} formatter={v=>decimal(v)}/><Legend/>{series.map((s,i)=><Line key={s} dataKey={s} stroke={colors[i%colors.length]} dot={false} connectNulls={false} isAnimationActive={false}/>)}</LineChart></ResponsiveContainer></div>;}
function Field({name,label,s,update,type='number',help=''}){return <label>{label}<input aria-label={label} type={type} step="any" value={s[name]} onChange={e=>update({[name]:e.target.value})}/>{help&&<small className="muted">{help}</small>}</label>;}

export function CryptoLab({inputs:s,onChange,disabled=false}){
  const run=useCalculation('/crypto',cryptoPayload(s)),r=run.result;
  const [example,setExample]=useState(false);
  const update=p=>onChange({...s,...p});
  return <div className="research-lab"><div className="section-heading"><div><h1>Crypto spot portfolio</h1><p>Fixed holdings, daily USD prices, and risk measured across all 365 days.</p></div><button disabled={disabled} onClick={()=>setExample(true)}>Try crypto example</button></div>
    {example&&<div className="banner"><span>Replace crypto inputs with invented Bitcoin-like and Ether-like series?</span><button disabled={disabled} onClick={()=>{onChange(cryptoExample());setExample(false);}}>Load crypto example</button><button onClick={()=>setExample(false)}>Cancel</button></div>}
    <form onSubmit={run.calculate} noValidate><fieldset disabled={disabled}>
      <Panel title="History & assumptions"><div className="research-fields"><label>Crypto data source<select aria-label="Crypto data source" value={s.source} onChange={e=>update({source:e.target.value})}><option value="market">Yahoo Finance · USD spot</option><option value="demo">Offline · invented prices</option></select></label>
        <Field name="start" label="Crypto start date" type="date" s={s} update={update}/><Field name="end" label="Crypto end date" type="date" s={s} update={update}/>
        <Field name="benchmark" label="Crypto benchmark" type="text" s={s} update={update}/><Field name="cash" label="Crypto cash (USD)" s={s} update={update}/><Field name="risk_free_percent" label="Crypto Sharpe reference rate (%)" s={s} update={update}/>
      </div><p className="note">Only completed UTC days, including weekends. Cash earns zero. Use exact USD spot tickers such as BTC-USD or ETH-USD. Offline dates: 2024–2025, tickers DEMO-BTC / DEMO-ETH.</p></Panel>
      <Panel title="Spot holdings" action={<button type="button" disabled={s.holdings.length>=10} onClick={()=>update({holdings:[...s.holdings,{ticker:'',quantity:'',avg_cost:''}]})}>Add crypto</button>}>
        <div className="table-wrap"><table aria-label="Crypto holdings inputs"><thead><tr><th>Ticker</th><th>Units</th><th>Average cost / unit (optional)</th><th/></tr></thead><tbody>{s.holdings.map((h,i)=><tr key={i}>{['ticker','quantity','avg_cost'].map(k=><td key={k}><input aria-label={`Crypto ${k} ${i+1}`} type={k==='ticker'?'text':'number'} step="any" value={h[k]} onChange={e=>update({holdings:s.holdings.map((row,j)=>i===j?{...row,[k]:e.target.value}:row)})}/></td>)}<td><button type="button" disabled={s.holdings.length===1} aria-label={`Remove crypto ${i+1}`} onClick={()=>update({holdings:s.holdings.filter((_,j)=>j!==i)})}>Remove</button></td></tr>)}</tbody></table></div>
        <p className="note">Quantities are held constant throughout the selected period. Purchase costs affect unrealized P&L only. This does not reconstruct actual trades or combine crypto with the stock portfolio.</p><RunButtons run={run} source={s.source} label="Analyze crypto"/>
      </Panel></fieldset></form><Status run={run}/>
    {r&&<section aria-label="Crypto results"><div className="section-heading"><h2>{s.source==='demo'?'Invented example':'Historical fixed holdings'} · USD</h2><Export result={r} name="crypto-history.json"/></div>
      <div className="research-stats">{[['Ending value',money(r.summary.ending_value)],['Period return',percent(r.summary.total_return)],['Max drawdown',percent(r.summary.max_drawdown)],['Annual volatility · 365 days',percent(r.summary.annual_volatility)],['Sharpe',decimal(r.summary.sharpe)],['CAGR · one year minimum',percent(r.summary.cagr)]].map(([k,v])=><div key={k}><span>{k}</span><strong>{v}</strong></div>)}</div>
      <Panel title="Fixed holdings vs benchmark"><Chart label="Crypto historical values" data={r.daily} x="date" series={['value','benchmark']}/></Panel>
      <Panel title="Holdings at final close"><div className="table-wrap"><table aria-label="Crypto ending holdings"><thead><tr><th>Ticker</th><th>Units</th><th>Last close</th><th>Value</th><th>Weight</th><th>Unrealized P&L vs entered cost</th></tr></thead><tbody>{r.holdings.map(h=><tr key={h.ticker}><th>{h.ticker}</th><td>{decimal(h.quantity,6)}</td><td>{money(h.price)}</td><td>{money(h.value)}</td><td>{percent(h.weight)}</td><td>{money(h.unrealized_pnl)}</td></tr>)}</tbody></table></div><p className="note">Cash: {money(r.summary.cash)}. Period P&L: {money(r.summary.period_pnl)}. Cost-based P&L has no implied holding period.</p></Panel>
      <Panel title="Calculation notes">{r.notes.map(n=><p className="note" key={n}>{n}</p>)}<p className="note">Data retrieved: {r.market_data_fetched_at||'Offline example'}. Full download includes every observation and a SHA-256 data fingerprint.</p></Panel>
    </section>}
  </div>;
}

export function VolatilityLab({inputs:s,onChange,disabled=false}){
  const run=useCalculation('/volatility',surfacePayload(s)),r=run.result;
  const [available,setAvailable]=useState(null),[loading,setLoading]=useState(false),[error,setError]=useState(''),[page,setPage]=useState(0);
  const current=useRef(s);current.current=s;const lookup=useRef(0);
  useEffect(()=>()=>{lookup.current++;},[]);
  useEffect(()=>{setAvailable(null);setError('');lookup.current++;setLoading(false);},[s.symbol,s.source]);
  useEffect(()=>setPage(0),[r]);
  const update=p=>onChange({...s,...p});
  async function load(){const id=++lookup.current;setLoading(true);setError('');try{const data=await api('/options/expirations?symbol='+encodeURIComponent(s.symbol.trim().toUpperCase()));if(lookup.current===id)setAvailable(data.expirations);}catch(e){if(lookup.current===id)setError(e.message);}finally{if(lookup.current===id)setLoading(false);}}
  const smiles=r?r.strikes.map(strike=>Object.fromEntries([['strike',strike],...r.expirations.map(exp=>[exp,r.points.find(p=>p.strike===strike&&p.expiration===exp)?.iv_percent??null])])):[];
  return <div className="research-lab"><div className="section-heading"><div><h1>Volatility surface</h1><p>Observe the strike and expiry grid. Inspect the quotes behind each implied volatility.</p></div><span className="eyebrow">Unfitted observations</span></div>
    <form onSubmit={run.calculate} noValidate><fieldset disabled={disabled}>
      <Panel title="Quotes & filters"><div className="research-fields"><label>Volatility data source<select aria-label="Volatility data source" value={s.source} onChange={e=>update({source:e.target.value,expirations:[]})}><option value="demo">Offline · invented quotes</option><option value="market">Yahoo Finance · delayed quotes</option></select></label>
        {s.source==='market'&&<Field name="symbol" label="Surface ticker" type="text" s={s} update={p=>update({...p,expirations:[]})}/>}
        <label>Option side<select aria-label="Surface option side" value={s.kind} onChange={e=>update({kind:e.target.value})}><option value="otm">OTM puts / calls (ATM uses call)</option><option value="call">Calls only</option><option value="put">Puts only</option></select></label>
        <Field name="rate" label="Surface interest rate (%)" s={s} update={update}/><Field name="dividend_yield" label="Surface dividend yield (%)" s={s} update={update}/><Field name="min_open_interest" label="Minimum open interest" s={s} update={update}/><Field name="max_spread_percent" label="Maximum bid/ask spread (% of mid)" s={s} update={update}/>
      </div>
      {s.source==='market'&&<><button type="button" disabled={loading||!s.symbol.trim()} onClick={load}>{loading?'Loading…':'Load expirations'}</button>{error&&<p role="alert" className="error">{error}</p>}<div className="research-expirations">{(available||s.expirations).map(exp=><label key={exp}><input type="checkbox" checked={s.expirations.includes(exp)} disabled={!s.expirations.includes(exp)&&s.expirations.length>=4} onChange={e=>update({expirations:e.target.checked?[...s.expirations,exp]:s.expirations.filter(x=>x!==exp)})}/>{exp}</label>)}</div><p className="note">Select up to four expirations. Market valuation uses today's UTC date; provider quotes may be older. Last-trade time does not establish bid/ask freshness.</p></>}
      <p className="note">European-equivalent IV from midpoint, ACT/365 and continuous rates. American exercise, discrete dividends and adjusted deliverables require separate review. Zero bids, crossed markets, wide spreads and impossible model prices are excluded. Rates of zero are editable assumptions.</p>
      {s.source==='demo'&&<p className="note">Fixed invented snapshot: 2025-01-01, underlying 100, three maturities. Two quotes deliberately fail quality checks. No live connection needed.</p>}
      <RunButtons run={run} source={s.source} label="Build volatility grid"/>
      </Panel></fieldset></form><Status run={run}/>
    {r&&<section aria-label="Volatility results"><div className="section-heading"><div><h2>{r.symbol} · {r.currency} · {r.as_of}</h2><p>{r.included} quotes included · {r.excluded} excluded (including the unselected side)</p></div><Export result={r} name="volatility-observations.json"/></div>
      {r.points.length===0?<p className="banner">No quotes pass these filters. Review exclusions below; no surface was inferred.</p>:<><Panel title="Implied volatility (%) · expiry × strike"><div className="table-wrap"><table aria-label="Volatility grid"><thead><tr><th>Expiry / strike</th>{r.strikes.map(k=><th key={k}>{decimal(k)}</th>)}</tr></thead><tbody>{r.expirations.map(exp=><tr key={exp}><th>{exp}</th>{r.strikes.map(k=>{const p=r.points.find(p=>p.expiration===exp&&p.strike===k);return <td key={k} style={p?{background:`rgba(76,201,176,${.08+.42*Math.min(p.iv_percent/100,1)})`}:undefined}>{p?decimal(p.iv_percent):'—'}</td>;})}</tr>)}</tbody></table></div><p className="note">Stronger green indicates higher IV (shade saturates at 100%). A dash means no retained quote; no interpolation fills the gap.</p></Panel><Panel title="Volatility smiles · one line per expiry"><Chart data={smiles} x="strike" series={r.expirations} label="Volatility smiles by expiry"/></Panel></>}
      <Panel title="Quote audit"><div className="table-wrap"><table aria-label="Volatility quote audit"><thead><tr><th>Expiry</th><th>Type</th><th>Strike</th><th>Spot</th><th>Bid</th><th>Ask</th><th>Open interest</th><th>IV %</th><th>Status / reason</th></tr></thead><tbody>{r.audit.slice(page*100,(page+1)*100).map((p,i)=><tr key={i}><td>{p.expiration}</td><td>{p.kind}</td><td>{decimal(p.strike)}</td><td>{decimal(p.spot)}</td><td>{decimal(p.bid,4)}</td><td>{decimal(p.ask,4)}</td><td>{decimal(p.open_interest,0)}</td><td>{decimal(p.iv_percent)}</td><td>{p.status}: {p.reason}</td></tr>)}</tbody></table></div>{r.audit.length>100&&<div className="research-actions"><button disabled={page===0} onClick={()=>setPage(page-1)}>Previous quotes</button><span>Page {page+1} / {Math.ceil(r.audit.length/100)}</span><button disabled={(page+1)*100>=r.audit.length} onClick={()=>setPage(page+1)}>Next quotes</button></div>}</Panel>
      <Panel title="Methodology & limitations">{r.notes.map(n=><p className="note" key={n}>{n}</p>)}</Panel>
    </section>}
  </div>;
}
