import React, {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {LayoutDashboard, Layers, ChartNoAxesCombined, Settings2, Search, RefreshCw, ArrowRight, X, Upload, LoaderCircle, FlaskConical} from 'lucide-react';
import {api, num, money, decimal, date, rows} from './data.js';
import {Panel, Overview, Risk, DataTable} from './components.jsx';
import Workspace from './Workspace.jsx';
import OptionsLab from './OptionsLab.jsx';
import AnalyticsLab from './AnalyticsLab.jsx';
import BacktestLab from './BacktestLab.jsx';
import {CryptoLab,VolatilityLab} from './ResearchLabs.jsx';
import {emptyCrypto,emptySurface} from './research-model.js';
import {keepAndTransfer} from './strategy-transfer.js';
import CoveredCallLab from './CoveredCallLab.jsx';
import {emptyCoveredCall} from './covered-call-model.js';
import {emptyBacktest} from './backtest-model.js';
import {upgradeAnalytics} from './analytics-model.js';
import {emptyOptions,upgradeOptions} from './options-model.js';

const defaults={benchmark:'SPY',period:'1y',interval:'1d',window:30,return_basis:'price',risk_free_percent:0};
const tabNames=['overview','holdings','research','options','analytics','backtesting','volatility','crypto','risk','settings'];
const tabIcons=[LayoutDashboard,Layers,Search,FlaskConical,ChartNoAxesCombined,ChartNoAxesCombined,ChartNoAxesCombined,ChartNoAxesCombined,ChartNoAxesCombined,Settings2];
const titleCase=s=>s==='analytics'?'Analytics Lab':s==='options'?'Options Lab':s[0].toUpperCase()+s.slice(1);
const newHolding=i=>({...i,qty:'',avg_cost:'',percent:'0',dollars:'0',purchase_price:''});

function TickerSearch({onAdd,disabled}) {
  const [query,setQuery]=useState(''),[matches,setMatches]=useState([]),[selected,setSelected]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const requestId=useRef(0);
  useEffect(()=>()=>{requestId.current++;},[]);
  async function search(event) {
    event.preventDefault(); const id=++requestId.current;
    setBusy(true);setError('');setMatches([]);setSelected('');
    try {const data=await api('/search?q='+encodeURIComponent(query));if(id===requestId.current){setMatches(data.matches);setSelected(data.matches[0]?.ticker||'');}}
    catch(e){if(id===requestId.current)setError(e.message);}
    finally {if(id===requestId.current)setBusy(false);}
  }
  async function add() {
    const id=++requestId.current;setBusy(true);setError('');
    try {const identity=await api('/instrument?symbol='+encodeURIComponent(selected));if(id===requestId.current){onAdd(identity);setMatches([]);setQuery('');}}
    catch(e){if(id===requestId.current)setError(e.message);}
    finally {if(id===requestId.current)setBusy(false);}
  }
  return <div className="search-block"><form className="search-form" onSubmit={search}><label className="grow">Ticker or company name<div className="search-input"><Search size={17}/><input value={query} placeholder="AAPL or Apple" autoComplete="off" onChange={e=>{requestId.current++;setQuery(e.target.value);setMatches([]);setBusy(false);setError('');}}/></div></label><button type="submit" disabled={!query.trim()||busy||disabled}>{busy?<LoaderCircle size={16} className="spin"/>:<Search size={16}/>}Search tickers</button></form>
    {matches.length>0&&<div className="search-confirm"><label className="grow">Confirm the security and exchange<select value={selected} onChange={e=>setSelected(e.target.value)}>{matches.map(m=><option key={m.ticker} value={m.ticker}>{m.ticker} — {m.name} · {m.exchange}</option>)}</select></label><button className="primary" disabled={busy||disabled} onClick={add}>Add selected ticker</button></div>}
    {error&&<p className="error" role="alert">{error}</p>}
  </div>;
}

export default function App() {return <Workspace Tracker={Tracker}/>;}

export function Tracker({initialState:initial,onDraftChange,portfolioBar,workspaceLoading=false}) {
  const [view,setView]=useState(location.hash.startsWith('#options=')?'options':initial?.view||'overview'),[mode,setMode]=useState(initial?.mode||'holdings'),[source,setSource]=useState(initial?.source||'quantity');
  const [holdings,setHoldings]=useState(initial?.holdings||[]),[research,setResearch]=useState(initial?.research||[]),[cash,setCash]=useState(initial?.cash??'0');
  const [budget,setBudget]=useState(initial?.budget??'10000'),[unit,setUnit]=useState(initial?.unit||'percent'),[settings,setSettings]=useState(initial?.settings||defaults);
  const [csv,setCsv]=useState(initial?.csv||null),[csvError,setCsvError]=useState(''),[importing,setImporting]=useState(false);
  const [options,setOptions]=useState(()=>upgradeOptions(initial?.options));
  const [coveredCall,setCoveredCall]=useState(()=>initial?.covered_call||emptyCoveredCall());
  const [backtestTool,setBacktestTool]=useState(initial?.backtest_tool||'stocks');
  const [backtest,setBacktest]=useState(()=>initial?.backtest||emptyBacktest());
  const [cryptoInputs,setCryptoInputs]=useState(()=>initial?.crypto||emptyCrypto());
  const [volatility,setVolatility]=useState(()=>initial?.volatility||emptySurface());
  function transferStrategy(next){try{setOptions(keepAndTransfer(options,next));setView('options');return null;}catch(e){return e.message;}}
  const [analytics,setAnalytics]=useState(()=>upgradeAnalytics(initial?.analytics));
  const analyticsCurrency=analytics.tool==='bond'?analytics.bond_pricing.currency:analytics.tool==='option'?analytics.option_pricing.currency:analytics.tool==='futures'?analytics.futures_pricing.currency:analytics.currency;
  const currentView=useRef(view);currentView.current=view;
  const [allocation,setAllocation]=useState(null),[allocationError,setAllocationError]=useState('');
  const [saved,setSaved]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const runId=useRef(0),importId=useRef(0);
  useEffect(()=>()=>{runId.current++;importId.current++;},[]);
  const draft=JSON.stringify({schema_version:1,view,mode,source,holdings,research,cash,budget,unit,csv,options,analytics,crypto:cryptoInputs,volatility,backtest,covered_call:coveredCall,backtest_tool:backtestTool,
    settings:{...settings,window:String(settings.window),risk_free_percent:String(settings.risk_free_percent)}});
  useLayoutEffect(()=>{onDraftChange?.(JSON.parse(draft));},[draft,onDraftChange]);
  const updateSetting=(key,value)=>setSettings(s=>({...s,[key]:value}));
  const allocations=holdings.map(h=>({ticker:h.ticker,allocation:num(h[unit]),purchase_price:num(h.purchase_price)}));
  const allocationPayload={total_invested:num(budget),allocation_unit:unit,allocations};
  const allocationKey=JSON.stringify(allocationPayload);
  const request={mode,source,benchmark:settings.benchmark.trim().toUpperCase(),period:settings.period,interval:settings.interval,window:num(settings.window),return_basis:settings.return_basis,annual_risk_free_rate:num(settings.risk_free_percent)===null?null:num(settings.risk_free_percent)/100,
    cash_balance:mode==='holdings'&&source!=='allocation'?num(cash):0,
    total_invested:mode==='holdings'&&source==='allocation'?num(budget):10000,
    allocation_unit:unit,allocations:mode==='holdings'&&source==='allocation'?allocations:[],
    positions:mode==='holdings'?(source==='csv'?csv?.positions||[]:source==='quantity'?holdings.map(h=>({ticker:h.ticker,qty:num(h.qty),avg_cost:num(h.avg_cost)})):[]):[],
    tickers:mode==='research'?research.map(h=>h.ticker):[]};
  const fingerprint=JSON.stringify(request);
  const currentKey=useRef(fingerprint);currentKey.current=fingerprint;
  const result=saved?.key===fingerprint?saved.result:null;
  const validAllocation=allocation?.key===allocationKey?allocation.data:null;

  useEffect(()=>{
    if(source!=='allocation'||mode!=='holdings')return;
    const controller=new AbortController();setAllocationError('');
    const timer=setTimeout(()=>{
      api('/allocation',JSON.parse(allocationKey),controller.signal).then(data=>setAllocation({key:allocationKey,data})).catch(e=>{if(e.name!=='AbortError'){setAllocation(null);setAllocationError(e.message);}});
    },300);
    return ()=>{clearTimeout(timer);controller.abort();};
  },[allocationKey,source,mode]);
  useEffect(()=>{setError('');setNotice('');},[fingerprint]);

  function navigate(next) {setView(next);if(next==='holdings')setMode('holdings');if(next==='research')setMode('research');}
  function add(identity) {
    const target=mode==='holdings'?holdings:research;
    if(target.some(h=>h.ticker===identity.ticker)){setNotice(identity.ticker+' is already selected.');return;}
    if(mode==='holdings')setHoldings(h=>[...h,newHolding(identity)]);else setResearch(h=>[...h,identity]);
  }
  function updateHolding(ticker,key,value) {setHoldings(h=>h.map(row=>row.ticker===ticker?{...row,[key]:value}:row));}
  async function importFile(event) {
    const file=event.target.files?.[0];if(!file)return;
    const id=++importId.current;setCsv(null);setCsvError('');setImporting(true);setSaved(null);
    try {
      if(file.size>2_000_000)throw new Error('Choose a CSV smaller than 2 MB.');
      const data=await api('/import',{text:await file.text()});
      if(id===importId.current)setCsv({name:file.name,positions:data.positions});
    }catch(e){if(id===importId.current)setCsvError(e.message);}
    finally{if(id===importId.current)setImporting(false);event.target.value='';}
  }
  async function analyze(refresh=false) {
    if(mode==='holdings'&&source==='csv'&&!csv){setError('Upload a valid holdings CSV first.');return;}
    const key=fingerprint,id=++runId.current;
    setBusy(true);setError('');setSaved(null);setNotice('');
    try {
      const data=await api('/analyze',{...request,refresh});
      if(id===runId.current&&key===currentKey.current){setSaved({key,result:data});if(!['options','analytics','backtesting'].includes(currentView.current))setView('overview');}
      else if(id===runId.current)setNotice('Inputs changed during calculation. Analyze again to use the latest values.');
    }catch(e){if(id===runId.current&&key===currentKey.current)setError(e.message);}
    finally{if(id===runId.current)setBusy(false);}
  }
  const noInput=mode==='research'?!research.length:source==='csv'?!csv:source==='allocation'?!validAllocation:!holdings.length&&!(num(cash)>0);
  const canAnalyze=!noInput&&!importing&&!busy&&!workspaceLoading;
  const entry=<>
    <div className="section-heading"><div><h1>{mode==='research'?'Research securities':'Your holdings'}</h1><p>{mode==='research'?'Compare each security against the same benchmark.':'Enter quantities, or calculate them from your original investment.'}</p></div>{mode==='holdings'&&<div className="segmented" aria-label="Holdings input method">{[['quantity','Quantity'],['allocation','Allocation'],['csv','CSV upload']].map(([key,label])=><button key={key} aria-pressed={source===key} onClick={()=>setSource(key)}>{label}</button>)}</div>}</div>
    <Panel title={mode==='research'?'Select investments':'Positions editor'} action={<span className="eyebrow">USD equities & ETFs</span>}>
      {mode==='holdings'&&source==='csv'?<div className="panel-body"><label className="upload"><Upload size={20}/><span>Choose holdings CSV</span><input aria-label="Upload holdings CSV" type="file" accept=".csv,text/csv" onChange={importFile} disabled={importing}/></label><p className="muted small">Required columns: ticker, qty, avg_cost. Currency defaults to USD. Duplicate lots are combined by weighted average cost.</p>{importing&&<p role="status">Reading holdings…</p>}{csvError&&<p className="error" role="alert">{csvError}</p>}{csv&&<><p className="positive">{csv.name} · {csv.positions.length} holdings imported</p><div className="table-wrap"><table aria-label="Imported holdings"><thead><tr><th>Ticker</th><th>Quantity</th><th>Average cost</th></tr></thead><tbody>{csv.positions.map(h=><tr key={h.ticker}><td>{h.ticker}</td><td>{decimal(h.qty,6)}</td><td>{money(h.avg_cost)}</td></tr>)}</tbody></table></div></>}</div>:<TickerSearch key={mode} onAdd={add} disabled={importing}/>}
      {mode==='holdings'&&source==='allocation'&&<div className="entry-options"><label>Total amount invested (USD)<input aria-label="Total amount invested (USD)" type="number" min="0.01" step="any" value={budget} onChange={e=>setBudget(e.target.value)}/></label><label>Allocate by<select value={unit} onChange={e=>setUnit(e.target.value)}><option value="percent">Percentage</option><option value="dollars">Dollar amount</option></select></label><p className="muted small">Use the original investment budget. Quantity = allocated dollars ÷ purchase price. Unallocated funds remain cash.</p></div>}
      {source!=='csv'&&mode==='holdings'&&<div className="table-wrap"><table aria-label="Editable holdings"><thead><tr><th>Security</th><th>{source==='allocation'?`Allocation (${unit==='percent'?'%':'USD'})`:'Quantity'}</th><th>Purchase price (USD)</th>{source==='allocation'&&<th>Calculated quantity</th>}<th><span className="sr-only">Remove</span></th></tr></thead><tbody>{holdings.map(h=><tr key={h.ticker}><td><strong>{h.ticker}</strong><span className="company">{h.name} · {h.exchange}</span></td><td><input aria-label={`${h.ticker} ${source==='allocation'?'allocation':'quantity'}`} type="number" min="0" step="any" value={source==='allocation'?h[unit]:h.qty} onChange={e=>updateHolding(h.ticker,source==='allocation'?unit:'qty',e.target.value)}/></td><td><input aria-label={`${h.ticker} purchase price`} type="number" min="0" step="any" value={source==='allocation'?h.purchase_price:h.avg_cost} onChange={e=>updateHolding(h.ticker,source==='allocation'?'purchase_price':'avg_cost',e.target.value)}/></td>{source==='allocation'&&<td className="mono">{decimal(validAllocation?.positions.find(p=>p.ticker===h.ticker)?.qty??null,6)}</td>}<td><button className="icon-button" aria-label={'Remove '+h.ticker} onClick={()=>setHoldings(items=>items.filter(row=>row.ticker!==h.ticker))}><X size={16}/></button></td></tr>)}{!holdings.length&&<tr><td colSpan={source==='allocation'?5:4} className="empty-row">Search for your first holding above, or enter cash below.</td></tr>}</tbody></table></div>}
      {mode==='research'&&<div className="panel-body selections">{research.map(h=><div className="selection" key={h.ticker}><div><strong>{h.ticker}</strong><span className="company">{h.name} · {h.exchange}</span></div><button className="icon-button" aria-label={'Remove '+h.ticker} onClick={()=>setResearch(items=>items.filter(row=>row.ticker!==h.ticker))}><X size={16}/></button></div>)}{!research.length&&<p className="muted">Search for a ticker or company name to begin.</p>}<p className="muted small">Research mode compares independent securities. It does not create portfolio weights or require purchase costs.</p></div>}
      {mode==='holdings'&&<div className="entry-options">{source==='allocation'?<><div><div className="metric-label">Unallocated cash</div><strong className="mono">{money(validAllocation?.cash_balance)}</strong></div>{!validAllocation&&!allocationError&&<span className="muted" role="status">Calculating quantities…</span>}{allocationError&&<p className="error" role="alert">{allocationError}</p>}</>:<label>Uninvested cash (USD)<input aria-label="Uninvested cash (USD)" type="number" min="0" step="any" value={cash} onChange={e=>setCash(e.target.value)}/></label>}<p className="muted small">Fractional shares supported. Cash earns 0% in the model. Use a split-adjusted average purchase price for stocks that have split.</p></div>}
      <div className="panel-head"><span className="muted small">{settings.benchmark.toUpperCase()||'Choose benchmark'} · {settings.period} · {settings.return_basis==='total'?'Total return':'Price return'}</span><button className="primary" disabled={!canAnalyze} onClick={()=>analyze()}>{busy?<LoaderCircle size={16} className="spin"/>:<ArrowRight size={16}/>}Analyze {mode==='research'?'securities':'portfolio'}</button></div>
    </Panel>
    {mode==='holdings'&&source==='allocation'&&validAllocation?.positions.length>0&&<Panel title="Calculated positions"><DataTable frame={validAllocation.preview} label="Calculated positions" columns={[{key:'ticker',label:'Ticker'},{key:'invested_amount',label:'Allocated dollars',render:money},{key:'avg_cost',label:'Purchase price',render:money},{key:'qty',label:'Quantity',render:v=>decimal(v,6)}]}/></Panel>}
  </>;
  return <div className="app-shell">
    <header className="topbar"><div className="brand"><div className="logo">PT</div><div><strong>Portfolio Tracker</strong><div className="eyebrow">Personal workspace</div></div></div><div className="top-status"><span>{view==='crypto'?'CRYPTO SPOT':view==='volatility'?'VOLATILITY':view==='backtesting'?'BACKTESTING':view==='analytics'?'ANALYTICS LAB':view==='options'?'OPTIONS LAB':mode==='research'?'RESEARCH':'MY HOLDINGS'}</span><span className="muted">{view==='crypto'?'USD · 365-day calendar':view==='volatility'?'Observed IV · No fitted values':view==='backtesting'&&backtestTool==='covered_call'?'USD · Modeled option prices':view==='backtesting'?`USD · ${backtest.source==='demo'?'Offline example':'Historical simulation'}`:view==='analytics'?`${analyticsCurrency} · Your assumptions`:view==='options'?`${options.currency||'USD'} · Options scenarios`:'USD · Yahoo Finance'}</span></div></header>
    <nav className="tabs" role="tablist" aria-label="Portfolio views" onKeyDown={e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;const i=tabNames.indexOf(view),next=e.key==='Home'?0:e.key==='End'?tabNames.length-1:(i+(e.key==='ArrowRight'?1:tabNames.length-1))%tabNames.length;navigate(tabNames[next]);document.getElementById('tab-'+tabNames[next])?.focus();e.preventDefault();}}>{tabNames.map((tab,i)=>{const Icon=tabIcons[i];return <button key={tab} id={'tab-'+tab} role="tab" aria-selected={view===tab} aria-controls="workspace" tabIndex={view===tab?0:-1} onClick={()=>navigate(tab)}><Icon size={17}/>{titleCase(tab)}</button>;})}</nav>
    <main id="workspace" role="tabpanel" aria-labelledby={'tab-'+view}>
      {portfolioBar}
      {!['options','analytics','backtesting','volatility','crypto'].includes(view)&&<div className="toolbar"><div className="toolbar-context"><span className="context-label">{mode==='holdings'?'My portfolio':'Research comparison'}</span><span className="muted small">{result?`Closing prices · ${date(result.metrics?.valuation_date||result.comparison.end)}`:'Ready for your selections'}</span></div><div className="toolbar-actions"><button aria-label="Open analysis settings" onClick={()=>navigate('settings')}><Settings2 size={16}/>{settings.benchmark.toUpperCase()||'Benchmark'}<span className="desktop-only"> · {settings.period} · {settings.return_basis==='total'?'Total return':'Price return'}</span></button><button aria-label="Refresh market data and analyze" title="Fetch fresh market data and recalculate" disabled={!canAnalyze} onClick={()=>analyze(true)}><RefreshCw size={16} className={busy?'spin':''}/><span className="desktop-only">Refresh</span></button><button className="primary" disabled={!canAnalyze} onClick={()=>analyze()}>{busy?<LoaderCircle size={16} className="spin"/>:<ArrowRight size={16}/>}Analyze</button></div></div>}
      {busy&&!['options','analytics','backtesting','volatility','crypto'].includes(view)&&<div className="banner" role="status"><LoaderCircle size={17} className="spin"/>Retrieving historical prices and calculating results… You can keep editing.</div>}
      {error&&!['options','analytics','backtesting','volatility','crypto'].includes(view)&&<div className="banner error" role="alert">{error}</div>}{notice&&!['options','analytics','backtesting','volatility','crypto'].includes(view)&&<div className="banner" role="status">{notice}</div>}
      {saved&&!result&&!['options','analytics','backtesting','volatility','crypto'].includes(view)&&<div className="banner">Inputs have changed. Analyze again to update charts and downloads.</div>}
      {result?.warnings.length>0&&!['options','analytics','backtesting','volatility','crypto'].includes(view)&&<details className="warnings"><summary>{result.warnings.length} calculation {result.warnings.length===1?'note':'notes'}</summary><ul>{result.warnings.map(w=><li key={w}>{w}</li>)}</ul></details>}
      {view==='backtesting'&&<><div className="segmented backtest-tool-picker" aria-label="Backtesting tools"><button aria-pressed={backtestTool==='stocks'} onClick={()=>setBacktestTool('stocks')}>Historical stocks & ETFs</button><button aria-pressed={backtestTool==='covered_call'} onClick={()=>setBacktestTool('covered_call')}>Options strategy simulation</button></div>{backtestTool==='stocks'?<BacktestLab inputs={backtest} onChange={setBacktest} disabled={workspaceLoading}/>:<CoveredCallLab inputs={coveredCall} onChange={setCoveredCall} disabled={workspaceLoading}/>}</>}
      {view==='crypto'&&<CryptoLab inputs={cryptoInputs} onChange={setCryptoInputs} disabled={workspaceLoading}/>}
      {view==='volatility'&&<VolatilityLab inputs={volatility} onChange={setVolatility} disabled={workspaceLoading}/>}
      {view==='analytics'&&<AnalyticsLab inputs={analytics} onChange={setAnalytics} onTransfer={transferStrategy} disabled={workspaceLoading}/>}
      {view==='options'&&<OptionsLab inputs={options} onChange={setOptions} disabled={workspaceLoading}/>}
      {view==='overview'&&(result?<Overview result={result} onEdit={()=>navigate(mode==='holdings'?'holdings':'research')} onRisk={()=>navigate('risk')}/>:entry)}
      {(view==='holdings'||view==='research')&&entry}
      {view==='risk'&&(result?<Risk result={result}/>:<Panel title="Risk analysis"><div className="empty"><ChartNoAxesCombined size={32}/><h1>Analyze your selections first</h1><p>Sharpe, beta, drawdown, correlations, and risk contributions will appear here.</p><button onClick={()=>navigate(mode==='holdings'?'holdings':'research')}>Edit selections <ArrowRight size={16}/></button></div></Panel>)}
      {view==='settings'&&<><div className="section-heading"><div><h1>Analysis settings</h1><p>One set of assumptions across every view.</p></div></div><Panel title="Performance & risk"><div className="settings-grid">
        <label>Return basis<select value={settings.return_basis} onChange={e=>updateSetting('return_basis',e.target.value)}><option value="price">Price return · dividends excluded</option><option value="total">Total return · dividends reinvested</option></select><span className="muted small">Holdings value and unrealized P&L always use actual closing prices.</span></label>
        <label>Benchmark ticker<input value={settings.benchmark} onChange={e=>updateSetting('benchmark',e.target.value)} placeholder="SPY" autoComplete="off"/><span className="muted small">Any verified USD equity or ETF. SPY is the default.</span></label>
        <label>History period<select value={settings.period} onChange={e=>updateSetting('period',e.target.value)}>{[['6mo','6 months'],['1y','1 year'],['2y','2 years'],['5y','5 years'],['max','Maximum available']].map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>
        <label>Observation interval<select value={settings.interval} onChange={e=>updateSetting('interval',e.target.value)}><option value="1d">Daily</option><option value="1wk">Weekly</option><option value="1mo">Monthly</option></select></label>
        <label>Volatility window (observations)<input type="number" min="2" max="252" step="1" value={settings.window} onChange={e=>updateSetting('window',e.target.value)}/><span className="muted small">Snapshot volatility uses the latest complete window of returns.</span></label>
        <label>Annual risk-free rate (%)<input type="number" min="-99" step="any" value={settings.risk_free_percent} onChange={e=>updateSetting('risk_free_percent',e.target.value)}/><span className="muted small">0% is an editable assumption, not a current Treasury yield. It does not pay interest on cash.</span></label>
      </div><div className="panel-head"><span className="muted small">Changes apply on the next analysis.</span><button className="primary" disabled={!canAnalyze} onClick={()=>analyze()}>Analyze with these settings <ArrowRight size={16}/></button></div></Panel><Panel title="Data & calculation assumptions"><div className="panel-body assumptions"><p>USD-quoted equities and ETFs. Fees, taxes, actual trade dates, and account cash flows are excluded. Historical performance assumes the entered quantities were held throughout the period.</p><p>Total return uses adjusted prices to model dividend reinvestment within each asset. Cash stays constant at 0% interest. Missing prices and undefined statistics remain blank.</p><p>Market history is cached for 15 minutes; ticker identities and search results for one hour. Refresh retrieves fresh data. Closing prices may be delayed. This is not a real-time trading feed.</p><p>Named portfolios are saved in your project folder when you select Save portfolio. Unfinished edits are recovered automatically in this browser. Drafts include holdings, allocations, cash, imported CSV positions, research lists, options scenarios, Analytics Lab, backtest and covered-call assumptions, and settings. Saved market results are recalculated with Analyze.</p></div></Panel></>}
    </main><footer><span>PORTFOLIO TRACKER <span className="muted">/</span> {view==='analytics'?analyticsCurrency:view==='options'?(options.currency||'USD'):'USD'} workspace</span><span>{view==='backtesting'?'Historical simulation · hypothetical results':view==='analytics'?'User inputs only · assumption-based valuations':view==='options'?'Delayed quotes · modeled option scenarios':result?`Data retrieved ${new Date(result.market_data_fetched_at).toLocaleString()}`:'Historical market data · local workspace'}</span></footer>
  </div>;
}
