import StrategyTransfer from './StrategyTransfer.jsx';
import React,{useEffect,useRef,useState} from 'react';
import {ArrowRight,LoaderCircle} from 'lucide-react';
import {Panel} from './components.jsx';
import {api} from './data.js';
import {derivativesPayload} from './derivatives-model.js';
import DerivativesResults from './DerivativesResults.jsx';

export default function DerivativesLab({type,inputs:a,onChange,onTransfer,disabled=false}){
  const option=type==='option';
  const [saved,setSaved]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const payload=derivativesPayload(a,type),key=JSON.stringify(payload),latest=useRef(key),run=useRef(0),current=useRef(a);
  latest.current=key;current.current=a;
  const result=saved?.key===key?saved.data:null;
  useEffect(()=>()=>{run.current++;},[]);
  useEffect(()=>setError(''),[key]);
  const update=patch=>onChange({...current.current,...patch});
  const field=(name,label,inputType='number',help='')=><label>{label}<input aria-label={label} type={inputType} step={name==='contracts'?'1':'any'} maxLength={name==='symbol'?80:undefined} value={a[name]} onChange={e=>update({[name]:e.target.value})}/>{help&&<small className="muted">{help}</small>}</label>;
  const select=(name,label,choices)=><label>{label}<select aria-label={label} value={a[name]} onChange={e=>update({[name]:e.target.value})}>{choices.map(([id,title])=><option value={id} key={id}>{title}</option>)}</select></label>;
  async function calculate(e){
    e.preventDefault();const id=++run.current;setBusy(true);setSaved(null);setError('');
    try{const data=await api('/analytics/'+type,payload);if(run.current===id&&latest.current===key)setSaved({key,data});}
    catch(e){if(run.current===id&&latest.current===key)setError(e.message);}
    finally{if(run.current===id)setBusy(false);}
  }
  return <div className="derivatives-lab">
    <div className="section-heading"><div><h2>{option?'Option pricing':'Futures pricing'}</h2><p>{option?'Estimate vanilla option premiums, then test changes in price and volatility.':'Estimate a delivery price from spot, time and the cost of carrying the asset.'}</p></div></div>
    <form onSubmit={calculate} noValidate><fieldset className="analytics-form" disabled={disabled}>
      <Panel title="Instrument & hypothesis">
        <div className="options-fields">
          {field('symbol','Instrument / ticker','text')}
          {select('currency','Pricing currency',['USD','CAD','EUR','GBP'].map(c=>[c,c]))}
          {option?select('exercise','Exercise style',[['european','European · Black–Scholes–Merton'],['american','American · binomial tree']]):select('asset','Underlying asset',[['equity','Equity / index'],['fx','Foreign exchange'],['commodity','Commodity']])}
          {field('as_of','Pricing date','date')}{field('maturity',option?'Expiry date':'Delivery date','date')}
          {field('spot',!option&&a.asset==='fx'?'Spot (domestic per foreign unit)':'Underlying spot price')}
        </div>
        <p className="note">{option?'Price a single vanilla option using your assumptions. European exercise is at expiry; American exercise can occur before expiry.':'Use one consistent quote convention for spot and delivery price. '+(a.asset==='fx'?'Pricing currency is the domestic currency; enter domestic currency per one unit of foreign currency.':'For an index quoted in points, enter the contract’s currency value per point as its multiplier.')} No quotes or financial data are fetched.</p>
        <div className="analytics-hypothesis"><label>Pricing hypothesis<textarea aria-label="Pricing hypothesis" rows={3} maxLength={3000} placeholder="Record your assumptions, sources and what would change your view." value={a.hypothesis} onChange={e=>update({hypothesis:e.target.value})}/></label></div>
      </Panel>
      <Panel title="Pricing assumptions">
        <div className="options-fields">
          {option&&select('kind','Option type',[['call','Call'],['put','Put']])}
          {option&&field('strike','Strike price')}
          {option&&field('volatility','Annual volatility (%)','number','20 means 20% annualized volatility.')}
          {field('rate',!option&&a.asset==='fx'?'Domestic interest rate (%)':'Interest rate (%)','number','Annual, continuously compounded; zero is an editable assumption.')}
          {option&&field('dividend_yield','Dividend yield (%)','number','Continuous annual yield, not individual cash dividends.')}
          {!option&&a.asset==='equity'&&field('income_yield','Income / dividend yield (%)','number','Continuous annual income yield.')}
          {!option&&a.asset==='fx'&&field('foreign_rate','Foreign interest rate (%)','number','Annual, continuously compounded.')}
          {!option&&a.asset==='commodity'&&field('storage_rate','Storage cost (%)','number','Annual proportional cost; not a fixed cash payment.')}
          {!option&&a.asset==='commodity'&&field('convenience_yield','Convenience yield (%)','number','Annual non-cash benefit of holding the physical asset.')}
          {option&&a.exercise==='american'&&select('tree_steps','Tree resolution',[['250','250 → 500 steps'],['500','500 → 1,000 steps'],['1000','1,000 → 2,000 steps']])}
          {field('contract_size',option?'Units per contract':'Contract units / multiplier','number',option?'100 is common for equity options; verify your contract.':'Units per contract, or currency per quoted index point.')}
          {field('contracts','Number of contracts')}
          {field('market_price',option?'Market premium per unit (optional)':'Market futures price (optional)','number','Used only for comparison with your model.')}
        </div>
        <p className="note">Time uses actual calendar days ÷ 365, up to 10 years. {option?(a.exercise==='american'?'The reported premium uses the finer tree. Both resolutions and their difference are shown so you can assess numerical stability.':'Greeks use the European model. An optional market premium also gives implied volatility, when a solution exists within 0–300%.'):'Carry rates and yields stay constant through delivery. Notional is price × multiplier × contracts; it is not margin or an upfront payment.'}</p>
        <div className="panel-head"><span className="muted small">Save portfolio keeps these assumptions with your workspace.</span><button type="submit" className="primary" disabled={disabled||busy}>{busy?<LoaderCircle size={16} className="spin"/>:<ArrowRight size={16}/>}Calculate {option?'option':'futures'} price</button></div>
      </Panel>
    </fieldset></form>
    {busy&&<p className="banner" role="status">Calculating price and sensitivities…</p>}
    {error&&<p className="banner error" role="alert">{error}</p>}
    {saved&&!result&&<p className="banner">Assumptions changed. Calculate again to refresh the price.</p>}
    {result&&onTransfer&&option&&<StrategyTransfer key={saved.key} type='option' inputs={a} result={result} onTransfer={onTransfer} disabled={disabled}/>}
    {result&&<DerivativesResults type={type} result={result} inputs={a}/>}
    <details className="model-settings"><summary>Methodology & model scope</summary><div className="analytics-methodology">
      {option?<><p>Black–Scholes–Merton assumes lognormal prices, constant volatility, constant continuously compounded interest and dividend yield, and frictionless trading. This vanilla spot-option model does not price options on futures, barriers, Asian options or other path-dependent contracts.</p><p>The American model uses a Cox–Ross–Rubinstein tree with exercise at each node. Its dividend input is a continuous yield: it does not schedule discrete cash dividends. Numerical convergence checks cannot remove model risk. American sensitivities are full repricings; analytical European Greeks are not substituted for American Greeks.</p><p>At expiry, value is intrinsic. At zero volatility, the deterministic limit is used, including optimal early exercise for an American option. Greeks are unavailable at these boundaries. No volatility smile, term structure, transaction costs or exercise fees are modeled.</p><p>References: <a target="_blank" rel="noreferrer" href="https://www.kellogg.northwestern.edu/faculty/hagerty/ftp/d65/lecture/Fall2004/Black_Scholes_revisedFall2004.pdf">Northwestern — Black–Scholes</a> · <a target="_blank" rel="noreferrer" href="https://www.sciencedirect.com/science/article/pii/0304405X79900151">Cox, Ross & Rubinstein — binomial pricing</a>.</p></>:<><p>Equity/index: F = S × exp((r − q) × T). FX: F = S × exp((domestic rate − foreign rate) × T). Commodity: F = S × exp((r + storage − convenience) × T). Rates are annual continuous assumptions; commodity storage and convenience inputs are proportional yields.</p><p>This uses forward-style cost of carry, treating forward and futures prices as equal under deterministic rates. Daily settlement effects, margin, funding convexity, Treasury delivery options, perpetual funding and negative commodity prices are outside this model. It does not value an existing futures position or calculate its profit.</p><p>Reference: <a target="_blank" rel="noreferrer" href="https://www.cmegroup.com/trading/equity-index/fairvalue.html">CME — equity futures fair value and carry</a>. This calculator uses continuous compounding rather than the simple-interest convention in CME’s worked example.</p></>}
      <p>Displayed estimates are conditional on your inputs. Double-precision calculations and sensitivity tables support checking the model; they do not establish a uniquely correct market price. A quote difference is not a guaranteed trading profit.</p>
    </div></details>
  </div>;
}
