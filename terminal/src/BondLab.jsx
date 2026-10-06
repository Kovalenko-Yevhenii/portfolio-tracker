import React,{useEffect,useRef,useState} from 'react';
import {ArrowRight,LoaderCircle} from 'lucide-react';
import {Panel} from './components.jsx';
import {api} from './data.js';
import {bondPayload,bondExample} from './bond-model.js';
import BondResults from './BondResults.jsx';

export default function BondLab({inputs:b,onChange,disabled=false}){
  const [saved,setSaved]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[example,setExample]=useState(null);
  const payload=bondPayload(b),key=JSON.stringify(payload),latest=useRef(key),run=useRef(0),current=useRef(b);
  latest.current=key;current.current=b;
  useEffect(()=>()=>{run.current++;},[]);
  useEffect(()=>setError(''),[key]);
  const result=saved?.key===key?saved.data:null;
  const update=patch=>onChange({...current.current,...patch});
  const field=(name,label,type='number',help='')=><label>{label}<input aria-label={label} type={type} step="any" maxLength={name==='name'?100:undefined} value={b[name]} onChange={e=>update({[name]:e.target.value})}/>{help&&<small className="muted">{help}</small>}</label>;
  const select=(name,label,choices)=><label>{label}<select aria-label={label} value={b[name]} onChange={e=>update({[name]:e.target.value})}>{choices.map(([id,title])=><option key={id} value={id}>{title}</option>)}</select></label>;
  async function calculate(e){e.preventDefault();const id=++run.current;setBusy(true);setSaved(null);setError('');try{const data=await api('/analytics/bond',payload);if(id===run.current&&key===latest.current)setSaved({key,data});}catch(e){if(id===run.current&&key===latest.current)setError(e.message);}finally{if(id===run.current)setBusy(false);}}
  return <div className="derivatives-lab bond-lab">
    <div className="section-heading"><div><h2>Bond Analytics</h2><p>Value regular fixed-rate government and corporate bonds. Test yield and spread assumptions.</p></div></div>
    <div className="bond-examples"><span className="muted small">Explore an offline example</span><button disabled={disabled} onClick={()=>setExample('government')}>Government bond example</button><button disabled={disabled} onClick={()=>setExample('corporate')}>Corporate bond example</button></div>
    {example&&<div className="banner bond-example-confirm" role="status"><span>Load the fictional {example} example? This replaces the current bond inputs. Other tools keep their inputs.</span><button disabled={disabled} onClick={()=>{onChange(bondExample(example));setExample(null);}}>Load example</button><button onClick={()=>setExample(null)}>Cancel</button></div>}
    <form onSubmit={calculate} noValidate><fieldset className="analytics-form" disabled={disabled}>
      <Panel title="Bond & cash flows"><div className="options-fields">
        {field('name','Bond name / identifier','text')}
        {select('issuer_type','Issuer type',[['government','Government'],['corporate','Corporate']])}
        {select('currency','Bond currency',['USD','CAD','EUR','GBP'].map(c=>[c,c]))}
        {field('settlement','Settlement date','date','Date cash and the bond change hands; not the trade date.')}
        {field('maturity','Bond maturity date','date')}
        {field('face_amount','Total face amount','number','Face value of the whole position, in the selected currency.')}
        {field('coupon_rate','Annual coupon rate (%)','number','Fixed contractual rate. Principal is repaid at 100% at maturity.')}
        {select('frequency','Coupon frequency',[['1','Annual'],['2','Semiannual'],['4','Quarterly']])}
        {select('day_count','Accrued-interest basis',[['actual_actual','Actual/Actual · regular coupon period'],['30u360','30/360 US · February-end adjustments']])}
        {select('date_roll','Coupon date rule',[['maturity_day','Same day as maturity · clip shorter months'],['month_end','End of each coupon month']])}
        {select('discounting','Final-period discounting',[['compound','Compound in every period'],['simple_final','Simple interest when one payment remains']])}
      </div><p className="note">Regular coupons are generated backward from maturity. Check the resulting dates against the bond’s terms. A coupon on settlement is treated as already paid. No holiday adjustments, ex-coupon window or irregular first/last coupon is modeled.</p>
      <div className="analytics-hypothesis"><label>Bond hypothesis<textarea aria-label="Bond hypothesis" rows={3} maxLength={3000} placeholder="Record your rate outlook, credit assumptions and source of each input." value={b.hypothesis} onChange={e=>update({hypothesis:e.target.value})}/></label></div></Panel>
      <Panel title="Price & yield assumptions"><div className="options-fields">
        {select('mode','Bond calculation',[['price','Price from yield'],['yield','Yield from market price'],['spread','Price from benchmark + spread']])}
        {b.mode==='price'&&field('yield_percent','Annual yield to maturity (%)','number','Nominal annual yield, compounded at the coupon frequency.')}
        {b.mode==='spread'&&field('benchmark_yield','Benchmark yield (%)','number','Use a comparable maturity and the same compounding convention.')}
        {b.mode==='spread'&&field('spread_bps','Yield spread (basis points)','number','100 basis points = 1 percentage point.')}
        {field('market_clean',b.mode==='yield'?'Market clean price per 100':'Market clean price per 100 (optional)','number','100 means par. Excludes accrued interest; this is not the total cash cost.')}
      </div><p className="note">{b.mode==='spread'?'Discount yield = benchmark yield + spread. This is a flat yield spread, not a Z-spread, OAS or estimated default probability.':'Yield to maturity discounts the promised remaining cash flows. It is not a guaranteed realized return.'} Annual yields and the price-to-yield solver support −20% to 100%. Issuer type labels the analysis; it does not automatically supply a credit rating or change the selected conventions.</p>
      <div className="panel-head"><span className="muted small">User inputs only · Save portfolio keeps this bond model.</span><button type="submit" className="primary" disabled={busy||disabled}>{busy?<LoaderCircle size={16} className="spin"/>:<ArrowRight size={16}/>}Calculate bond</button></div></Panel>
    </fieldset></form>
    {busy&&<p className="banner" role="status">Calculating bond cash flows and risk…</p>}{error&&<p className="banner error" role="alert">{error}</p>}{saved&&!result&&<p className="banner">Assumptions changed. Calculate again to refresh the bond analysis.</p>}
    {result&&<BondResults result={result} inputs={b}/>}
    <details className="model-settings"><summary>Bond methodology & scope</summary><div className="analytics-methodology">
      <p>Supported: regular fixed-rate, non-callable bullet bonds paying annual, semiannual or quarterly coupons with principal repaid at par. These conventions are configurable, not inferred from a bond identifier. Callable bonds, convertibles, amortizing debt, mortgage-backed securities, floaters and inflation-linked bonds need different models.</p>
      <p>Coupon per 100 = annual coupon rate ÷ payments per year. Actual/Actual uses elapsed actual days divided by actual days in the regular coupon period. US 30/360 uses adjusted 30-day months, including February-end rules, divided by 360 ÷ frequency. Dirty price includes accrued interest; clean price excludes it. Total cash at settlement = dirty price × face amount ÷ 100, before fees and taxes.</p>
      <p>For compound discounting, each cash flow is discounted by (1 + yield ÷ frequency) raised to its remaining fractional coupon periods. If selected and only one payment remains, simple discounting uses 1 + yield × remaining coupon-period years. Match this choice to the security’s market convention. This is a cash-flow model, not a claim to reproduce every sovereign market’s quoted yield.</p>
      <p>Macaulay duration is the present-value-weighted time to payments, in coupon-period years. Modified duration and convexity are exact first and second price derivatives normalized by dirty price. DV01 is the position’s approximate loss for a one-basis-point yield rise. Scenarios reprice the same promised cash flows at the same settlement date. They exclude passage of time, reinvestment, default, recovery, funding and trading costs.</p>
      <p>Sources: <a href="https://www.canada.ca/en/department-finance/programs/financial-sector-policy/securities/securities-technical-guide/determining-bond-treasury-bill-prices-yields.html" target="_blank" rel="noreferrer">Finance Canada — bond price and yield</a> · <a href="https://www.finra.org/investors/insights/bond-yield-return" target="_blank" rel="noreferrer">FINRA — yield and return</a> · <a href="https://github.com/lballabio/QuantLib/blob/master/ql/time/daycounters/thirty360.cpp" target="_blank" rel="noreferrer">QuantLib — 30/360 conventions</a>.</p>
    </div></details>
  </div>;
}
