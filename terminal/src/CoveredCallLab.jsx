import React,{useEffect,useRef,useState} from 'react';
import {ArrowRight,LoaderCircle} from 'lucide-react';
import {Panel} from './components.jsx';
import {api} from './data.js';
import {coveredCallPayload,coveredCallExample} from './covered-call-model.js';
import CoveredCallResults from './CoveredCallResults.jsx';
import './backtest.css';

export default function CoveredCallLab({inputs:s,onChange,disabled=false}){
  const [saved,setSaved]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[example,setExample]=useState(false);
  const payload=coveredCallPayload(s),key=JSON.stringify(payload),latest=useRef(key),run=useRef(0),current=useRef(s);
  latest.current=key;current.current=s;
  useEffect(()=>()=>{run.current++;},[]);useEffect(()=>setError(''),[key]);
  const update=patch=>onChange({...current.current,...patch});
  const field=(k,label,type='number',help='')=><label>{label}<input aria-label={label} type={type} step="any" value={s[k]} maxLength={type==='text'?40:undefined} onChange={e=>update({[k]:e.target.value})}/>{help&&<small className="muted">{help}</small>}</label>;
  const result=saved?.key===key?saved.data:null;
  async function simulate(e,refresh=false){e.preventDefault();const id=++run.current;setBusy(true);setSaved(null);setError('');try{const data=await api('/simulation/covered-call',{...payload,refresh});if(id===run.current&&key===latest.current)setSaved({key,data});}catch(e){if(id===run.current&&key===latest.current)setError(e.message);}finally{if(id===run.current)setBusy(false);}}
  return <div className="backtest-lab covered-call-lab">
    <div className="section-heading"><div><h1>Covered-call simulation</h1><p>Own the stock, write a call, and compare the modeled outcome with holding the same stock position.</p></div><button disabled={disabled} onClick={()=>setExample(true)}>Try covered-call example</button></div>
    <div className="banner simulation-label"><strong>MODELED OPTION PRICES</strong><span>Stock history can be downloaded. Option premiums, strikes, expirations and assignment are assumptions—not historical option quotes.</span></div>
    {example&&<div className="banner backtest-example" role="status"><span>Load the invented covered-call example? This replaces this simulator’s inputs.</span><button disabled={disabled} onClick={()=>{onChange(coveredCallExample());setExample(false);}}>Load covered-call example</button><button onClick={()=>setExample(false)}>Cancel</button></div>}
    <form onSubmit={simulate} noValidate><fieldset className="backtest-form" disabled={disabled}>
      <Panel title="Stock position & period"><div className="backtest-fields">
        <label>Underlying data<select aria-label="Underlying data" value={s.source} onChange={e=>update({source:e.target.value})}><option value="market">Downloaded stock history · Yahoo Finance</option><option value="demo">Offline example · invented stock history</option></select></label>
        {field('ticker','Simulation ticker','text',s.source==='demo'?'Use DEMO-CC for the offline example.':'Exact USD stock or ETF ticker. No actual option listings are assumed.')}
        {field('start','Simulation start','date')}{field('end','Simulation end','date','Completed sessions only; at most five years.')}
        {field('capital','Simulation starting capital (USD)')}{field('contracts','Covered-call contracts','number','Whole contracts. Each requires 100 stock units; unused capital stays in cash.')}
      </div><p className="note">Buy the fixed stock position at the first open. Both comparisons start with the same stock quantity, capital, stock costs and distribution rules. After assignment, try to repurchase that quantity at the next open. Premiums are retained as cash, with no borrowing or growth in position size.</p></Panel>
      <Panel title="Call selection & management"><div className="backtest-fields">
        {field('tenor_sessions','Call holding period (sessions)','number','2–126 sessions, including entry and expiry sessions.')}
        {field('otm_percent','Strike above prior close (%)','number','Strike = previous close × (1 + percentage), rounded upward to the chosen increment.')}
        {field('strike_increment','Synthetic strike increment (USD)','number','An assumed strike grid, not a verified listed option chain.')}
        {field('roll_before','Roll before expiry (sessions)','number','0 holds to expiry. Otherwise buy back at that session’s close and write a replacement at the next open.')}
        <label>Assignment assumption<input value="Expiry only · deliver stock when close > strike" readOnly aria-label="Assignment assumption"/><small className="muted">European-style approximation. Early American assignment and ex-dividend exercise are excluded.</small></label>
      </div></Panel>
      <Panel title="Option pricing assumptions"><div className="backtest-fields">
        <label>Volatility assumption<select aria-label="Volatility assumption" value={s.volatility_mode} onChange={e=>update({volatility_mode:e.target.value})}><option value="fixed">Fixed assumed volatility</option><option value="trailing">Trailing realized volatility + assumed premium</option></select></label>
        {s.volatility_mode==='fixed'?field('volatility_percent','Assumed annual volatility (%)'): <>{field('volatility_window','Trailing volatility sessions','number','Sample standard deviation of log returns, using only sessions before call entry.')}{field('volatility_premium','Volatility premium (percentage points)','number','Added to realized volatility. This does not estimate observed implied volatility.')}</>}
        {field('rate_percent','Pricing interest rate (%)','number','Constant continuously compounded rate; cash itself earns 0%.')}
        {field('dividend_yield_percent','Pricing dividend yield (%)','number','Constant BSM yield assumption. Separate from stock distributions actually recorded in the history.')}
      </div><p className="note">European Black–Scholes–Merton prices with a 252-session business-time clock. Volatility is fixed at each call’s entry for its life. The sensitivity table reruns the strategy at −5, 0 and +5 volatility points and at 0×, 1× and 2× your cost settings.</p></Panel>
      <Panel title="Execution costs & hypothesis"><div className="backtest-fields">
        {field('stock_fee_bps','Stock commission (basis points)')}{field('stock_slippage_bps','Stock slippage (basis points)')}
        {field('option_fee','Option fee per contract (USD)')}{field('option_half_spread_percent','Option half-spread (% of model premium)','number','Sell at model × (1 − spread); buy back at model × (1 + spread). This is not a stock-price percentage.')}
        {field('assignment_fee','Assignment fee per contract (USD)')}
      </div><div className="backtest-hypothesis"><label>Covered-call hypothesis<textarea aria-label="Covered-call hypothesis" rows={3} maxLength={3000} value={s.hypothesis} onChange={e=>update({hypothesis:e.target.value})} placeholder="Record the assumptions and the question you want to test."/></label></div>
        <p className="note">A roll needs enough cash to buy back the call; otherwise the model holds it to expiry. Gross premium is not net profit. Open calls remain liabilities in the final portfolio value.</p>
        <div className="panel-head"><span className="muted small">Save portfolio keeps assumptions. Full-run downloads include the stock data and all modeled results.</span><div className="backtest-actions">{s.source==='market'&&<button type="button" disabled={busy||disabled} onClick={e=>simulate(e,true)}>Refresh stock data & simulate</button>}<button type="submit" className="primary" disabled={busy||disabled}>{busy?<LoaderCircle size={16} className="spin"/>:<ArrowRight size={16}/>}Run covered-call simulation</button></div></div>
      </Panel>
    </fieldset></form>
    {busy&&<p className="banner" role="status">Simulating covered calls, stock ownership and volatility/cost scenarios…</p>}{error&&<p role="alert" className="banner error">{error}</p>}{saved&&!result&&<p className="banner">Assumptions changed. Run again to refresh modeled results and downloads.</p>}
    {result&&<CoveredCallResults result={result} hypothesis={s.hypothesis}/>}
    <details className="model-settings"><summary>Simulation methodology & limits</summary><div className="backtest-methodology">
      <p>The strategy owns a fixed whole-lot stock position and sells one synthetic call per 100 units. Strike selection uses the prior close. Fixed volatility is user-entered; trailing volatility uses the preceding N log returns and annualizes their sample standard deviation by √252. An assumed premium is added, then volatility is bounded at 0–300%. It remains fixed for that call.</p>
      <p>The synthetic contract expires at the close of its Nth observed session. A session open is half a session before its close, so entry time to expiry is (N − 0.5)/252 years; each closing mark uses remaining sessions/252. This business-time approximation does not separately account for weekend decay, calendar interest or actual listed expiration schedules. A gap in provider dates can affect it.</p>
      <p>Opening premiums are model values reduced by the assumed half-spread; early buybacks are model values plus the half-spread. At expiry, a strictly in-the-money call delivers the stock for the strike price. Its intrinsic value is not also debited from cash. A call exactly at the strike expires unassigned. Actual American exercise and assignment are more complex.</p>
      <p>Stock data uses the provider’s split-adjusted price scale, with recorded cash distributions credited separately on ex-date to the previous holder. It does not use total-return-adjusted closes. Periods containing splits are rejected because option deliverable adjustments are unsupported. Historical revisions, unavailable delisted stocks, corporate actions and distribution timing remain limitations.</p>
      <p>Final value = cash + stock value − short-call liability. Open positions are marked without closing costs. The stock comparator has the same initial quantity and cash, rather than investing all remaining cash. Risk statistics follow the stock backtester; Sharpe uses 0% and CAGR is withheld below one year. No tax, cash interest, leverage or liquidity model is included.</p>
      <p>References: <a href="https://www.optionseducation.org/strategies/all-strategies/covered-call-buy-write" target="_blank" rel="noreferrer">OIC covered-call guide</a> · <a href="https://www.optionseducation.org/referencelibrary/faq/options-assignment" target="_blank" rel="noreferrer">OIC assignment guidance</a>. This is not a reproduction of an exchange buy-write index.</p>
    </div></details>
  </div>;
}
