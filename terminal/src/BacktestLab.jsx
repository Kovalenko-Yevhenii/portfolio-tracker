import React,{useEffect,useRef,useState} from 'react';
import {ArrowRight,LoaderCircle,Plus,X} from 'lucide-react';
import {Panel} from './components.jsx';
import {api,decimal} from './data.js';
import {backtestPayload,backtestExample} from './backtest-model.js';
import BacktestResults from './BacktestResults.jsx';
import './backtest.css';

export default function BacktestLab({inputs:b,onChange,disabled=false}){
  const [saved,setSaved]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[example,setExample]=useState(false);
  const payload=backtestPayload(b),key=JSON.stringify(payload),latest=useRef(key),run=useRef(0),current=useRef(b);
  latest.current=key;current.current=b;
  useEffect(()=>()=>{run.current++;},[]);
  useEffect(()=>setError(''),[key]);
  const result=saved?.key===key?saved.data:null;
  const update=patch=>onChange({...current.current,...patch});
  const asset=(i,patch)=>update({assets:current.current.assets.map((a,j)=>i===j?{...a,...patch}:a)});
  const field=(name,label,type='number',help='')=><label>{label}<input aria-label={label} type={type} step="any" value={b[name]} maxLength={type==='text'?40:undefined} onChange={e=>update({[name]:e.target.value})}/>{help&&<small className="muted">{help}</small>}</label>;
  async function calculate(e,refresh=false){
    e.preventDefault();const id=++run.current;setBusy(true);setSaved(null);setError('');
    try{const data=await api('/backtest',{...payload,refresh});if(id===run.current&&key===latest.current)setSaved({key,data});}
    catch(e){if(id===run.current&&key===latest.current)setError(e.message);}
    finally{if(id===run.current)setBusy(false);}
  }
  return <div className="backtest-lab">
    <div className="section-heading"><div><h1>Backtesting</h1><p>Test a rule through history. Compare returns, drawdowns and the trades behind them.</p></div><button disabled={disabled} onClick={()=>setExample(true)}>Try offline example</button></div>
    {example&&<div className="banner backtest-example" role="status"><span>Load an invented two-asset example? This replaces the backtest inputs.</span><button disabled={disabled} onClick={()=>{onChange(backtestExample());setExample(false);}}>Load example</button><button onClick={()=>setExample(false)}>Cancel</button></div>}
    <form onSubmit={calculate} noValidate><fieldset disabled={disabled} className="backtest-form">
      <Panel title="Strategy & period"><div className="backtest-fields">
        <label>Price history<select aria-label="Price history" value={b.source} onChange={e=>update({source:e.target.value})}><option value="market">Yahoo Finance · downloaded daily history</option><option value="demo">Offline example · invented prices</option></select></label>
        <label>Trading rule<select aria-label="Trading rule" value={b.strategy} onChange={e=>update({strategy:e.target.value})}><option value="sma">Moving average · invested or cash</option><option value="buy_hold">Buy and hold</option></select></label>
        {field('start','Backtest start','date')}{field('end','Backtest end','date','Choose a date before today; up to ten years per run.')}
        {field('capital','Starting capital (USD)')}
        {b.strategy==='sma'&&field('window','Moving-average sessions','number','2–252 prior closing prices; extra warm-up history is fetched automatically.')}
        {field('benchmark','Comparison benchmark','text',b.source==='demo'?'Use DEMO-MKT for the offline example.':'Exact ticker of a USD stock or ETF, such as SPY.')}
      </div><p className="note">{b.strategy==='sma'?'For each asset: buy if the previous closing price is above its simple moving average; sell if it is at or below. Orders execute at the following session’s open, including a signal from before the test’s first session.':'Invest at the first session’s open and hold to the final close.'} Long positions only. Cash earns 0%; no borrowing or short selling.</p></Panel>
      <Panel title="Initial portfolio allocation" action={<button type="button" disabled={b.assets.length>=10} onClick={()=>update({assets:[...b.assets,{ticker:'',weight:''}]})}><Plus size={15}/>Add security</button>}>
        <div className="table-wrap"><table aria-label="Backtest allocations"><thead><tr><th>Exact ticker</th><th>Initial allocation (%)</th><th>Remove</th></tr></thead><tbody>{b.assets.map((a,i)=><tr key={i}><td><input aria-label={`Backtest ticker ${i+1}`} value={a.ticker} maxLength={40} placeholder={b.source==='demo'?'DEMO-A':'AAPL'} autoComplete="off" onChange={e=>asset(i,{ticker:e.target.value})}/></td><td><input aria-label={`Backtest weight ${i+1}`} type="number" step="any" value={a.weight} onChange={e=>asset(i,{weight:e.target.value})}/></td><td><button type="button" className="icon-button" aria-label={`Remove backtest asset ${i+1}`} disabled={b.assets.length===1} onClick={()=>update({assets:b.assets.filter((_,j)=>j!==i)})}><X size={16}/></button></td></tr>)}</tbody></table></div>
        <p className="note">Total: <strong>{decimal(b.assets.reduce((n,a)=>n+(Number(a.weight)||0),0))}%</strong> · Must equal 100%. Each asset keeps its own cash and profits; weights can drift. Selling one asset leaves that money in cash rather than reallocating it. Up to ten USD stocks/ETFs with a common trading calendar.</p>
      </Panel>
      <Panel title="Costs & research assumptions"><div className="backtest-fields">
        {field('commission_bps','Commission (basis points)','number','Charged on every order’s traded value. 1 bp = 0.01%.')}
        {field('fee_per_order','Additional fee per order (USD)')}
        {field('slippage_bps','Slippage each way (basis points)','number','Buys execute above the opening price; sells below it.')}
        {field('risk_free_percent','Sharpe reference rate (%)','number','Annual effective rate for the statistic only. It does not pay interest on cash.')}
      </div><div className="backtest-hypothesis"><label>Backtest hypothesis<textarea aria-label="Backtest hypothesis" rows={3} maxLength={3000} value={b.hypothesis} placeholder="Write the rule and why it might work before testing. Reserve a different period to check it." onChange={e=>update({hypothesis:e.target.value})}/></label></div>
        <p className="note">{b.source==='demo'?'Offline example: DEMO-A, DEMO-B and DEMO-MKT are fictional. Available dates: 2024-01-02 to 2025-12-31.':'Historical opening and closing prices are adjusted for splits and distributions, modeling reinvestment. Trade quantities are adjusted units, not historical share counts. Tickers and USD currency are verified before download.'}</p>
        <div className="panel-head"><span className="muted small">Save portfolio keeps these assumptions. Download a run to preserve its prices and results.</span><div className="backtest-actions">{b.source==='market'&&<button type="button" disabled={busy||disabled} onClick={e=>calculate(e,true)}>Refresh data & run</button>}<button type="submit" className="primary" disabled={busy||disabled}>{busy?<LoaderCircle size={16} className="spin"/>:<ArrowRight size={16}/>}Run backtest</button></div></div>
      </Panel>
    </fieldset></form>
    {busy&&<p className="banner" role="status">{b.source==='demo'?'Running the offline example…':'Verifying securities, retrieving history and simulating trades…'}</p>}
    {error&&<p className="banner error" role="alert">{error}</p>}{saved&&!result&&<p className="banner">Assumptions changed. Run the backtest again to refresh results and downloads.</p>}
    {result&&<BacktestResults result={result} hypothesis={b.hypothesis}/>}
    <details className="model-settings"><summary>Backtesting methodology & limits</summary><div className="backtest-methodology">
      <p>The moving average uses exactly the preceding N completed closes. A signal is evaluated after that close and executed at the next observed session’s open, with adverse slippage and commissions. It cannot execute at the same close that generated it. The final close generates no order inside the test.</p>
      <p>Each initial allocation is a separate cash account. Entries invest all available cash after costs; exits sell all units. There is no periodic rebalancing. Fractional adjusted units and immediate reinvestment are assumed. Buy-and-hold comparators use the same opening date, costs and final valuation date. Open positions are not force-sold at the end.</p>
      <p>Adjusted prices are a total-return proxy. They do not reproduce dividend cash payment timing, whole-share rounding, tax lots, actual split-adjusted share quantities or broker statements. Liquidity limits, order failures, market impact beyond fixed slippage, taxes, settlement delays and cash interest are excluded. This version tests equities/ETFs; historical multi-leg options require separate data and execution rules.</p>
      <p>Daily drawdown includes starting capital and opening costs. Volatility and Sharpe use sample standard deviation of close-to-close returns, with 252 sessions/year; the first opening-to-close return is excluded from those statistics. Sharpe subtracts the entered effective annual rate converted to a daily rate. Undefined ratios remain blank. CAGR uses inclusive calendar days and is withheld for periods shorter than one year. Win rate includes only completed buy/sell pairs after costs.</p>
      <p>Missing or invalid quotes in the needed history stop the run. Market holidays can move the actual start/end dates; both are displayed. A date absent from every downloaded series cannot be detected without an independent exchange calendar. Provider data is not a point-in-time universe: symbol selection, survivorship bias and revised history remain limitations. A good historical result is not a forecast; do not select rules solely by their best historical result.</p>
      <p>References: <a href="https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/research-guide" target="_blank" rel="noreferrer">QuantConnect research guide</a> · <a href="https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.history.html" target="_blank" rel="noreferrer">yfinance historical data interface</a>.</p>
    </div></details>
  </div>;
}
