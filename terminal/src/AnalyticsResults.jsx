import React,{useState} from 'react';
import {Panel} from './components.jsx';
import {decimal,download} from './data.js';

function FootballField({result,money}){
  const values=result.ranges.flatMap(r=>[r.low,r.mid,r.high]);
  if(result.current_price!==null)values.push(result.current_price);
  const lo=Math.min(...values),hi=Math.max(...values),padding=Math.max((hi-lo)*.12,Math.abs(hi)*.02,1),min=lo-padding,max=hi+padding;
  const x=value=>(value-min)/(max-min)*100;
  return <div className="football-field" role="img" aria-label="Football field valuation ranges and current share price">
    {result.ranges.map(r=><div className="football-row" key={r.method} title={`${r.method}: ${money(r.low)} to ${money(r.high)}; marker ${money(r.mid)}. ${r.basis}`}><span className="football-label">{r.method}</span><div className="football-track">
      <span className={'football-range '+(r.method.startsWith('DCF')?'dcf-range':'')} style={{left:`${x(r.low)}%`,width:`${Math.max(x(r.high)-x(r.low),.4)}%`}}/>
      {result.current_price!==null&&<span className="football-market" style={{left:`${x(result.current_price)}%`}}/>}
      <span className="football-marker" style={{left:`${x(r.mid)}%`}}/>
    </div></div>)}
    <div className="football-axis"><span/><div><span>{money(min)}</span><span>{money((min+max)/2)}</span><span>{money(max)}</span></div></div>
  </div>;
}

export default function AnalyticsResults({result:r,inputs}){
  const [auditIndex,setAuditIndex]=useState(()=>String(Math.max(0,r.dcf.findIndex(d=>d.case==='Base'))));
  const money=v=>Number.isFinite(v)?new Intl.NumberFormat('en-US',{style:'currency',currency:r.currency,maximumFractionDigits:2}).format(v):'—';
  const selected=r.dcf[Number(auditIndex)]||r.dcf[0];
  const method=m=>m==='growth'?'Perpetual growth':'Exit EV/EBITDA';
  function exportCsv(){
    const rows=[['Analytics Lab',r.company],['Valuation date',r.valuation_date],['Currency',r.currency],['Financial amounts and shares in',r.units],['Share prices','Actual currency per share'],[],['Method','Low / share','Base or median / share','High / share','Range basis']];
    for(const v of r.ranges)rows.push([v.method,v.low,v.mid,v.high,v.basis]);
    rows.push([],['Equity bridge item','Amount']);for(const [k,v] of Object.entries(r.bridge))rows.push([k,v]);
    for(const d of r.dcf){rows.push([],['DCF',d.case,method(d.method)],['WACC %',d.wacc],['Terminal growth %',d.growth],['Exit multiple',d.exit_multiple],['PV forecast',d.pv_forecast],['Terminal value at horizon',d.terminal_value],['PV terminal',d.pv_terminal],['Enterprise value',d.enterprise_value],['Common equity value',d.equity_value],['Value per share',d.price],['Year','EBIT','Tax %','Operating taxes','NOPAT','D&A','Capex','Change NWC','FCFF','Discount factor','PV FCFF']);for(const y of d.forecast)rows.push([y.year,y.ebit,y.tax_rate,y.taxes,y.nopat,y.depreciation,y.capex,y.change_nwc,y.fcff,y.discount_factor,y.pv_fcff]);}
    rows.push([],['Peer','Method','Multiple','Exclusion']);for(const p of r.peer_audit)rows.push([p.peer,p.method,p.multiple,p.exclusion]);
    for(const s of r.sensitivity){rows.push([],['Base sensitivity',method(s.method)],['WACC % / terminal assumption',...s.columns]);for(const row of s.rows)rows.push([row.wacc,...row.values]);}
    rows.push([],['Model version',r.model_version],['Hypothesis',inputs.hypothesis]);
    const escape=v=>'"'+(typeof v==='string'&&/^[=+@-]/.test(v)?"'":'')+String(v??'').replaceAll('"','""')+'"';
    download({name:'valuation-audit.csv',mime:'text/csv',content:rows.map(row=>row.map(escape).join(',')).join('\n')});
  }
  return <div className="analytics-results">
    <div className="section-heading"><div><h2>Valuation results{r.company?' · '+r.company:''}</h2><p>{r.valuation_date} · {r.currency} per share · conditional on your assumptions</p></div><div className="analytics-export"><button onClick={exportCsv}>Download calculation CSV</button><button onClick={()=>download({name:'valuation-model.json',mime:'application/json',content:JSON.stringify({inputs,result:r},null,2)})}>Download full model</button></div></div>
    {r.warnings.map(w=><p className="banner" key={w}>{w}</p>)}
    <Panel title="Football field"><p className="note">Each bar is a valuation range. The marker is the DCF Base case or the peer median. {r.current_price!==null?`The dashed line is your entered market price: ${money(r.current_price)}.`:'Enter a current share price to add a market reference.'}</p>
      <FootballField result={r} money={money}/>
      <div className="table-wrap"><table aria-label="Valuation ranges"><thead><tr><th>Method</th><th>Low</th><th>Base / median</th><th>High</th><th>Base / median vs. price</th><th>Range basis</th></tr></thead><tbody>{r.ranges.map(v=><tr key={v.method}><th scope="row">{v.method}</th><td>{money(v.low)}</td><td>{money(v.mid)}</td><td>{money(v.high)}</td><td>{r.current_price===null?'—':decimal((v.mid/r.current_price-1)*100)+'%'}</td><td>{v.basis}</td></tr>)}</tbody></table></div><p className="note">DCF bars span the entered cases, which may produce a single point. Comps bars span peer multiple quartiles. These are different sources of uncertainty, not probability intervals or a combined price target. Negative equity estimates indicate a shortfall in the equity bridge.</p>
    </Panel>
    {r.dcf.length>0&&<>
      <Panel title="DCF cases"><div className="table-wrap"><table aria-label="DCF case valuations"><thead><tr><th>Case</th><th>Terminal approach</th><th>Enterprise value</th><th>Common equity value</th><th>Value / share</th><th>Terminal % of EV</th><th>Vs. entered price</th></tr></thead><tbody>{r.dcf.map(d=><tr key={d.case+d.method}><th scope="row">{d.case}</th><td>{method(d.method)}</td><td>{decimal(d.enterprise_value)}</td><td>{decimal(d.equity_value)}</td><td>{money(d.price)}</td><td>{d.terminal_weight_percent===null?'—':decimal(d.terminal_weight_percent)+'%'}</td><td>{d.upside_percent===null?'—':decimal(d.upside_percent)+'%'}</td></tr>)}</tbody></table></div><p className="note">Enterprise and equity values are in {r.units} of {r.currency}. Share prices use actual currency units. A large terminal-value share means the conclusion depends heavily on long-term assumptions.</p></Panel>
      {r.sensitivity.map(s=><Panel key={s.method} title={`Base sensitivity · ${method(s.method)}`}><div className="table-wrap"><table className="sensitivity-table" aria-label={`Sensitivity ${s.method}`}><thead><tr><th>WACC ↓ / {s.method==='growth'?'growth %':'exit multiple ×'} →</th>{s.columns.map(c=><th key={c}>{decimal(c)}</th>)}</tr></thead><tbody>{s.rows.map(row=><tr key={row.wacc}><th scope="row">{decimal(row.wacc)}%</th>{row.values.map((v,i)=><td key={i} className={r.current_price!==null&&v!==null?(v>=r.current_price?'valuation-positive':'valuation-negative'):''}>{money(v)}</td>)}</tr>)}</tbody></table></div><p className="note">Value per share, holding the Base forecast and equity bridge constant. WACC steps are 0.5 percentage points; {s.method==='growth'?'growth steps are 0.5 percentage points. Cells with growth ≥ WACC are invalid.':'exit-multiple steps are 1×. Nonpositive multiples are invalid.'} Invalid cells display —. Colored cells compare with your entered market price.</p></Panel>)}
      <Panel title="DCF calculation audit"><div className="option-tool-row"><label>Case to inspect<select aria-label="DCF audit case" value={auditIndex} onChange={e=>setAuditIndex(e.target.value)}>{r.dcf.map((d,i)=><option key={d.case+d.method} value={i}>{d.case} · {method(d.method)}</option>)}</select></label></div>
        <div className="table-wrap"><table aria-label="DCF cash flow audit"><thead><tr>{['Year','EBIT','Taxes','NOPAT','D&A','Capex','Δ NWC','FCFF','Discount factor','PV of FCFF'].map(t=><th key={t}>{t}</th>)}</tr></thead><tbody>{selected.forecast.map(y=><tr key={y.year}><th scope="row">{y.year}</th>{['ebit','taxes','nopat','depreciation','capex','change_nwc','fcff','discount_factor','pv_fcff'].map(k=><td key={k}>{decimal(y[k],k==='discount_factor'?6:2)}</td>)}</tr>)}</tbody></table></div>
        <div className="analytics-audit-summary">{[['PV of forecast cash flows',selected.pv_forecast],['Terminal value at horizon',selected.terminal_value],['PV of terminal value',selected.pv_terminal],['Enterprise value',selected.enterprise_value],['Net equity bridge adjustment',r.bridge.adjustment],['Common equity value',selected.equity_value],['Diluted shares',r.bridge.shares]].map(([label,value])=><div key={label}><span>{label}</span><strong>{decimal(value)}</strong></div>)}</div><p className="note">Values in {r.units}; common equity value ÷ diluted shares = {money(selected.price)} per share. Discount factor in year t = 1 / (1 + WACC)^t. The full model download includes all inputs and unrounded output numbers.</p>
      </Panel>
    </>}
    {r.comps.length>0&&<Panel title="Comparable multiples"><p className="note">Shared comparison basis: {inputs.period}. Multiples use your entered peer values.</p><div className="table-wrap"><table aria-label="Comparable multiple statistics"><thead><tr><th>Method</th><th>Eligible peers</th><th>25th percentile</th><th>Median</th><th>75th percentile</th></tr></thead><tbody>{r.comps.map(c=><tr key={c.method}><th scope="row">{c.method}</th><td>{c.count}</td>{c.multiples.map((v,i)=><td key={i}>{decimal(v)}×</td>)}</tr>)}</tbody></table></div></Panel>}
    {r.peer_audit.length>0&&<details className="model-settings"><summary>Peer eligibility audit</summary><div className="table-wrap"><table aria-label="Peer eligibility audit"><thead><tr><th>Peer</th><th>Method</th><th>Multiple</th><th>Included / excluded</th></tr></thead><tbody>{r.peer_audit.map(p=><tr key={p.peer+p.method}><th scope="row">{p.peer}</th><td>{p.method}</td><td>{p.multiple===null?'—':decimal(p.multiple)+'×'}</td><td>{p.exclusion||'Included'}</td></tr>)}</tbody></table></div></details>}
  </div>;
}
