import React from 'react';
import {CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis} from 'recharts';
import {Download, ArrowRight} from 'lucide-react';
import {date, decimal, finite, money, percent, rows, download} from './data.js';

export const colors=['#e9b66c','#8ca6c8','#78cbbb','#c49dda','#db9294','#aac775','#75b7d0'];
export function Panel({title, action, children, className=''}) {
  return <section className={'panel '+className}><div className="panel-head"><h2>{title}</h2>{action}</div>{children}</section>;
}
export function Metric({label,value,note,tone=''}) {
  return <div className="metric"><div className="metric-label">{label}</div><div className={'metric-value '+tone}>{value}</div><div className="muted small">{note}</div></div>;
}
export function LinePlot({frame,columns,format='number',title}) {
  const series=columns || frame?.columns || [];
  const data=frame?.data.map((values,i)=>({date:date(frame.index[i]),...Object.fromEntries(series.map((key,j)=>['s'+j,values[frame.columns.indexOf(key)]]))})) || [];
  const fmt=value=>format==='percent'?percent(value):format==='money'?money(value):decimal(value);
  if (!data.length) return <p className="panel-body muted">No observations available.</p>;
  return <div className="chart-wrap" role="group" aria-label={title}>
    <div className="legend">{series.map((name,i)=><span key={name}><i style={{background:colors[i%colors.length]}}/>{name}</span>)}</div>
    <div className="chart"><ResponsiveContainer width="100%" height="100%" minWidth={0}>
      <LineChart data={data} margin={{top:12,right:18,bottom:8,left:14}} accessibilityLayer>
        <CartesianGrid vertical={false} stroke="#283340" strokeDasharray="3 3"/>
        <XAxis dataKey="date" stroke="#91a1b4" tickLine={false} axisLine={false} minTickGap={50} tick={{fontSize:12}} tickFormatter={v=>v.slice(2)}/>
        <YAxis domain={['auto','auto']} stroke="#91a1b4" tickLine={false} axisLine={false} width={72} tick={{fontSize:12}} tickFormatter={v=>format==='percent'?`${decimal(v*100,1)}%`:format==='money'?`${Math.abs(v)>=1000?decimal(v/1000,1)+'k':decimal(v,0)}`:decimal(v,0)}/>
        <Tooltip contentStyle={{background:'#151e2a',border:'1px solid #3a4a5d',borderRadius:6,color:'#e8edf4'}} labelStyle={{color:'#e8edf4'}} formatter={(v,name)=>[fmt(v),name]}/>
        {series.map((name,i)=><Line key={name} dataKey={'s'+i} name={name} stroke={colors[i%colors.length]} strokeWidth={2} strokeDasharray={name.startsWith('Benchmark:')?'5 4':undefined} dot={false} connectNulls={false} isAnimationActive={false}/>) }
      </LineChart>
    </ResponsiveContainer></div>
  </div>;
}
export function DataTable({frame, columns, label}) {
  const data=rows(frame);
  return <div className="table-wrap"><table aria-label={label}><thead><tr>{columns.map(c=><th key={c.key}>{c.label}</th>)}</tr></thead><tbody>
    {data.map((row,i)=><tr key={i}>{columns.map(c=><td key={c.key} className={c.key==='label'||c.key==='ticker'?'':'mono'}>{c.render?c.render(row[c.key],row):row[c.key]??'—'}</td>)}</tr>)}
    {!data.length&&<tr><td colSpan={columns.length} className="muted">No securities in this portfolio.</td></tr>}
  </tbody></table></div>;
}
export const comparisonColumns=[{key:'label',label:'Investment'},{key:'period_return',label:'Period return',render:percent},{key:'maximum_drawdown',label:'Max. drawdown',render:percent},{key:'excess_return_vs_benchmark',label:'Return minus benchmark',render:v=>finite(v)?decimal(v*100)+' pp':'—'}];
export function AllocationBars({analysis}) {
  return <div className="panel-body allocation-bars">{rows(analysis?.allocation).sort((a,b)=>b.weight-a.weight).map((row,i)=><div key={row.label} className="allocation-row"><div className="between"><span>{row.label}</span><span className="mono">{percent(row.weight)}</span></div><div className="track"><div style={{width:`${row.weight*100}%`,background:colors[i%colors.length]}}/></div><div className="small muted">{money(row.market_value)}</div></div>)}</div>;
}
export function Correlations({frame}) {
  if (!frame?.data.length) return <p className="panel-body muted">Cash has no security correlations.</p>;
  return <div className="table-wrap"><table className="heatmap" aria-label="Correlation matrix"><thead><tr><th>Holding</th>{frame.columns.map(c=><th key={c}>{c}</th>)}</tr></thead><tbody>{frame.data.map((values,i)=><tr key={frame.index[i]}><th>{frame.index[i]}</th>{values.map((v,j)=><td key={j} title={`${frame.index[i]} / ${frame.columns[j]}: ${decimal(v,3)}`} style={{background:finite(v)?`rgba(${v>=0?'75,154,160':'199,104,122'},${.08+Math.abs(v)*.46})`:undefined}}>{decimal(v)}</td>)}</tr>)}</tbody></table></div>;
}
export function Exports({result}) {
  return <details className="panel exports"><summary><Download size={16}/> Download analysis <span className="muted small">{result.exports.length} files</span></summary><div className="export-grid">{result.exports.map(file=><button key={file.name} onClick={()=>download(file)}><Download size={15}/>{file.name}</button>)}</div><p className="note">Files contain the displayed analysis. Positions CSV contains securities only; enter cash separately when importing. Holdings settings JSON records cash for reference.</p></details>;
}
export function Overview({result,onEdit,onRisk}) {
  const c=result.comparison, m=result.metrics;
  const portfolio=rows(c.summary).find(r=>r.label==='My portfolio');
  const names=Object.fromEntries(result.identities.map(i=>[i.ticker,i.name]));
  return <>
    {m&&<div className="metrics"><Metric label="Portfolio value" value={money(m.total_value)} note={`Includes ${money(m.cash_balance)} cash`}/><Metric label="Unrealized P&L" value={money(m.total_unrealized_pnl)} tone={m.total_unrealized_pnl>=0?'positive':'negative'} note={`${percent(m.total_cost>0?m.total_unrealized_pnl/m.total_cost:null)} on total cost ${money(m.total_cost)}`}/><Metric label="Period return" value={percent(portfolio?.period_return)} note={c.return_basis_label}/><Metric label="Maximum drawdown" value={percent(m.maximum_drawdown)} note="Full portfolio history · observed decline"/></div>}
    <div className={m?'overview-grid':''}><Panel title={m?'Portfolio vs. benchmark':'Research comparison'} action={<span className="eyebrow">Starting value 100</span>}><LinePlot frame={c.normalized} title="Normalized performance"/><p className="note">{date(c.start)} — {date(c.end)} · {c.return_basis_label}. Gaps represent missing quotes.</p></Panel>{m&&<Panel title="Current allocation" action={<button className="link" onClick={onRisk}>Risk details <ArrowRight size={14}/></button>}><AllocationBars analysis={result.diversification}/><p className="note">Market-value weights as of {date(m.valuation_date)}.</p></Panel>}</div>
    <Panel title="Performance comparison"><DataTable frame={c.summary} label="Performance comparison" columns={comparisonColumns}/><p className="note">Common comparison dates apply to every investment. Return minus benchmark is a percentage-point difference, not risk-adjusted alpha.</p></Panel>
    {m&&<><Panel title="Holdings" action={<button className="link" onClick={onEdit}>Manage positions <ArrowRight size={14}/></button>}><DataTable frame={result.positions} label="Holdings valuation" columns={[
      {key:'ticker',label:'Security',render:v=><><strong>{v}</strong><span className="company">{names[v]}</span></>},
      {key:'qty',label:'Quantity',render:v=>decimal(v,6)},{key:'avg_cost',label:'Avg. cost',render:money},{key:'last_price',label:'Last close',render:money},
      {key:'market_value',label:'Market value',render:money},{key:'unrealized_pnl',label:'Unrealized P&L',render:v=><span className={v>=0?'positive':'negative'}>{money(v)}</span>},
      {key:'market_value',label:'Weight',render:v=>percent(v/m.total_value)}].map((c,i)=>({...c,key:c.label==='Weight'?'weight':c.key,render:c.label==='Weight'?(_,r)=>percent(r.market_value/m.total_value):c.render}))}/><p className="note">Prices as of {date(m.valuation_date)}. Value and unrealized P&L use actual closing prices.</p></Panel>
      <div className="two-col"><Panel title="Portfolio value over time"><LinePlot frame={result.history} columns={['portfolio_value']} format="money" title="Portfolio closing value"/><p className="note">Current quantities held across the history, including cash at 0% interest.</p></Panel><Panel title={`${{'1d':'Daily','1wk':'Weekly','1mo':'Monthly'}[m.interval]} returns`}><LinePlot frame={result.history} columns={['returns']} format="percent" title="Portfolio interval returns"/><p className="note">{c.return_basis_label}. Missing intervals remain blank.</p></Panel></div>
      {m.return_basis==='total'&&<Panel title="Total-return performance · full portfolio history" action={<span className="eyebrow">Starting value 100</span>}><LinePlot frame={result.performance_normalized} title="Full-history dividend-reinvested portfolio performance"/><p className="note">Models reinvestment within each asset from {date(m.performance_start)} using quantities × closing prices as initial weights. This is hypothetical performance, not your account balance.</p></Panel>}
    </>}
    <Exports result={result}/>
    <details className="panel"><summary>Verified securities and benchmark</summary><div className="table-wrap"><table><thead><tr><th>Ticker</th><th>Name</th><th>Exchange</th><th>Currency</th></tr></thead><tbody>{result.identities.map(i=><tr key={i.ticker}><td>{i.ticker}</td><td>{i.name}</td><td>{i.exchange}</td><td>{i.currency}</td></tr>)}</tbody></table></div></details>
  </>;
}
export function Risk({result}) {
  const c=result.comparison,r=c.risk,d=result.diversification,m=result.metrics;
  const p=rows(r.summary).find(row=>row.label==='My portfolio');
  return <>
    {m&&<div className="metrics"><Metric label="Sharpe ratio" value={decimal(p?.sharpe_ratio)} note={`Risk-free assumption ${percent(r.annual_risk_free_rate)}`}/><Metric label={`Beta vs. ${result.settings.benchmark}`} value={decimal(p?.beta)} note="Historical benchmark sensitivity"/><Metric label="Rolling annualized volatility" value={percent(m.annualized_volatility)} note={`Latest ${m.annualized_volatility_window_observations} return observations`}/><Metric label="Maximum drawdown" value={percent(m.maximum_drawdown)} note="Full portfolio history"/></div>}
    <Panel title="Sharpe ratio and beta"><DataTable frame={r.summary} label="Sharpe and beta" columns={[{key:'label',label:'Investment'},{key:'sharpe_ratio',label:'Annualized Sharpe',render:v=>decimal(v,3)},{key:'beta',label:'Beta vs. benchmark',render:v=>decimal(v,3)},{key:'matched_return_observations',label:'Matched returns',render:v=>decimal(v,0)}]}/><p className="note">{date(r.sample_start)} — {date(r.sample_end)} · {r.matched_return_observations} matched returns · constant annual risk-free rate {percent(r.annual_risk_free_rate)}. These ratios use the full common sample. Undefined values remain blank. Annualizing Sharpe assumes returns are not serially correlated.</p></Panel>
    {d&&<><div className="two-col"><Panel title="Correlation between holdings"><Correlations frame={d.correlation}/><p className="note">−1 opposite movement · 0 uncorrelated · +1 together. Cash and constant-return correlations are undefined.</p></Panel><Panel title="Contribution to portfolio volatility"><div className="panel-body"><div className="metric-label">Annualized volatility at current weights</div><div className="metric-value">{percent(d.annualized_volatility)}</div></div><DataTable frame={d.allocation} label="Risk contributions" columns={[{key:'label',label:'Holding'},{key:'volatility_contribution',label:'Contribution',render:v=>finite(v)?decimal(v*100,3)+' pp':'—'},{key:'risk_share',label:'Share of risk',render:percent}]}/><p className="note">Contributions sum to modeled volatility. Negative contributions indicate diversification benefits; cash contributes zero. Risk shares are undefined when total volatility is zero.</p></Panel></div><p className="note">Current weights applied to historical covariance · {d.observations} matched returns · {date(d.sample_start)} — {date(d.sample_end)} · {c.return_basis_label}. This estimate differs from the rolling buy-and-hold volatility above.</p></>}
    <Panel title="Drawdown comparison"><LinePlot frame={c.drawdowns} format="percent" title="Drawdowns over common comparison period"/><p className="note">Observed decline from prior peak over {date(c.start)} — {date(c.end)}. Missing prices can hide deeper losses.</p></Panel>
    {m&&<Panel title="Portfolio drawdown · full history"><LinePlot frame={result.history} columns={['drawdown']} format="percent" title="Portfolio drawdown over full history"/></Panel>}
    <Exports result={result}/>
  </>;
}
