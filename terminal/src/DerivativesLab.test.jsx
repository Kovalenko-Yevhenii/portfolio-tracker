import React from 'react';
import {describe,it,expect,vi} from 'vitest';
import {render,screen,fireEvent,within,act} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App.jsx';
import {emptyAnalytics,validAnalytics,upgradeAnalytics} from './analytics-model.js';
import {derivativesPayload} from './derivatives-model.js';
import fixture from './fixtures/derivatives.json';
import * as helpers from './data.js';
const ok=data=>({ok:true,json:async()=>data});
const edit=(label,value)=>fireEvent.change(screen.getByLabelText(label),{target:{value}});
function setup(handler){
  const records=new Map(),requests=[];
  vi.stubGlobal('fetch',vi.fn(async(url,options={})=>{
    const body=options.body?JSON.parse(options.body):null;requests.push({url,body});
    if(url==='/api/portfolios')return ok({portfolios:[...records.values()]});
    if(url==='/api/portfolios/save'){const record={...body,revision:body.revision+1};records.set(body.id,structuredClone(record));return ok(record);}
    if(url.startsWith('/api/portfolios/'))return ok(records.get(url.split('/').at(-1)));
    if(url==='/api/analytics/option')return handler?handler(body):ok(body.exercise==='american'?fixture.american:fixture.european);
    if(url==='/api/analytics/futures')return ok(fixture.futures);
    throw Error('Unexpected external data request '+url);
  }));
  return {...render(<React.StrictMode><App/></React.StrictMode>),user:userEvent.setup(),records,requests};
}
async function open(user,type='option'){
  await user.click(screen.getByRole('tab',{name:'Analytics Lab'}));
  await user.click(screen.getByRole('button',{name:type==='option'?'Option pricing':'Futures pricing',exact:true}));
}
function fill(){
  for(const [label,value] of [['Pricing date','2026-09-30'],['Expiry date','2027-09-30'],['Underlying spot price','100'],['Strike price','100'],['Annual volatility (%)','20'],['Interest rate (%)','5'],['Number of contracts','2'],['Market premium per unit (optional)','10.450583572185565']])edit(label,value);
}

describe('derivatives in Analytics Lab',()=>{
  it('prices European options manually with correct units and hides stale results',async()=>{
    const {user,requests}=setup();await open(user);fill();
    await user.click(screen.getByRole('button',{name:'Calculate option price'}));
    await screen.findByRole('table',{name:'Derivative price sensitivity'});
    expect(screen.getByText('European Greeks')).toBeTruthy();expect(screen.getByText('Vega / 1pp')).toBeTruthy();
    expect(within(screen.getByLabelText('Pricing summary')).getByText('$2,090.12')).toBeTruthy();
    expect(screen.getByText('20.000000%')).toBeTruthy();
    const body=requests.find(r=>r.url==='/api/analytics/option').body;
    expect(body).toMatchObject({spot:100,strike:100,contracts:2,contract_size:100,rate:5,volatility:20,dividend_yield:0,tree_steps:500});
    edit('Annual volatility (%)','25');expect(screen.queryByRole('table',{name:'Derivative price sensitivity'})).toBeNull();
    expect(screen.getByText(/Assumptions changed/)).toBeTruthy();
  });
  it('uses the American tree and convergence check without showing European Greeks',async()=>{
    const {user,requests}=setup();await open(user);fill();
    await user.selectOptions(screen.getByLabelText('Exercise style'),'american');
    await user.selectOptions(screen.getByLabelText('Option type'),'put');edit('Underlying spot price','80');
    await user.click(screen.getByRole('button',{name:'Calculate option price'}));
    await screen.findByRole('table',{name:'American tree convergence'});
    expect(screen.queryByText('European Greeks')).toBeNull();expect(screen.getByText('1,000 steps · reported price')).toBeTruthy();
    expect(requests.find(r=>r.url==='/api/analytics/option').body.exercise).toBe('american');
  });
  it('prices futures and sends only the carry assumptions for the selected asset',async()=>{
    const {user,requests}=setup();await open(user,'futures');
    edit('Income / dividend yield (%)','2');
    await user.selectOptions(screen.getByLabelText('Underlying asset'),'commodity');
    edit('Storage cost (%)','3');edit('Convenience yield (%)','1');
    await user.selectOptions(screen.getByLabelText('Underlying asset'),'fx');
    edit('Foreign interest rate (%)','2');edit('Domestic interest rate (%)','5');edit('Spot (domestic per foreign unit)','1.1');
    edit('Pricing date','2026-09-30');edit('Delivery date','2027-09-30');edit('Contract units / multiplier','125000');
    await user.selectOptions(screen.getByLabelText('Pricing currency'),'GBP');
    expect(screen.getByText('GBP · Your assumptions')).toBeTruthy();
    await user.click(screen.getByRole('button',{name:'Calculate futures price'}));
    await screen.findByRole('table',{name:'Derivative price sensitivity'});
    expect(screen.getByText('Theoretical delivery price')).toBeTruthy();expect(screen.getByText('Total notional')).toBeTruthy();
    const body=requests.find(r=>r.url==='/api/analytics/futures').body;
    expect(body).toMatchObject({asset:'fx',spot:1.1,income_yield:0,foreign_rate:2,storage_rate:0,convenience_yield:0,contract_size:125000,currency:'GBP',market_price:null});
    await user.selectOptions(screen.getByLabelText('Underlying asset'),'commodity');expect(screen.getByLabelText('Storage cost (%)').value).toBe('3');
  });
  it('preserves all three tools through draft recovery and named portfolio saves',async()=>{
    const {user,records,unmount}=setup();await user.click(screen.getByRole('tab',{name:'Analytics Lab'}));
    edit('Company / ticker','Equity thesis');edit('Diluted shares (millions)','12.123456789');
    await user.click(screen.getByRole('button',{name:'Option pricing',exact:true}));edit('Strike price','123.456789');edit('Pricing hypothesis','Option thesis');
    await user.click(screen.getByRole('button',{name:'Futures pricing',exact:true}));edit('Pricing hypothesis','Carry thesis');edit('Contract units / multiplier','50');
    unmount();const mounted=render(<App/>);expect(screen.getByLabelText('Pricing hypothesis').value).toBe('Carry thesis');
    edit('Portfolio name','All analytics');await user.click(screen.getByRole('button',{name:'Save portfolio'}));await screen.findByText('Portfolio saved to this device.');
    const [id,record]=[...records.entries()][0];expect(record.state.analytics.version).toBe(3);expect(record.state.analytics.shares).toBe('12.123456789');
    expect(record.state.analytics.option_pricing.strike).toBe('123.456789');expect(record.state.analytics.futures_pricing.spot).toBe('');
    mounted.unmount();localStorage.clear();sessionStorage.clear();render(<App/>);
    await screen.findByRole('option',{name:'All analytics'});await user.selectOptions(screen.getByLabelText('Saved portfolios'),id);await user.click(screen.getByRole('button',{name:'Load',exact:true}));
    await screen.findByLabelText('Pricing hypothesis');expect(screen.getByLabelText('Pricing hypothesis').value).toBe('Carry thesis');
    await user.click(screen.getByRole('button',{name:'Option pricing',exact:true}));expect(screen.getByLabelText('Strike price').value).toBe('123.456789');
    await user.click(screen.getByRole('button',{name:'Equity valuation',exact:true}));expect(screen.getByLabelText('Company / ticker').value).toBe('Equity thesis');
  });
  it('upgrades legacy equity drafts without changing their entered assumptions',()=>{
    const old=emptyAnalytics();old.version=1;delete old.tool;delete old.option_pricing;delete old.futures_pricing;old.company='Legacy';old.shares='123.000001';
    expect(validAnalytics(old)).toBe(true);const next=upgradeAnalytics(old);
    expect(next.version).toBe(3);expect(next.company).toBe('Legacy');expect(next.cases).toEqual(old.cases);expect(next.shares).toBe(old.shares);expect(validAnalytics(next)).toBe(true);
    expect(validAnalytics({...next,option_pricing:{...next.option_pricing,exercise:'invalid'}})).toBe(false);
    expect(derivativesPayload(next.option_pricing,'option').spot).toBeNull();
  });
  it('rejects an outdated in-flight response and preserves inputs after an error',async()=>{
    let finish;const {user}=setup(()=>new Promise(resolve=>{finish=resolve;}));await open(user);fill();
    await user.click(screen.getByRole('button',{name:'Calculate option price'}));edit('Underlying spot price','200');
    await act(async()=>finish(ok(fixture.european)));expect(screen.queryByRole('table',{name:'Derivative price sensitivity'})).toBeNull();
    await user.click(screen.getByRole('button',{name:'Calculate option price'}));
    await act(async()=>finish({ok:false,json:async()=>({error:'Check the entered dates.'})}));
    expect(screen.getByRole('alert').textContent).toBe('Check the entered dates.');expect(screen.getByLabelText('Underlying spot price').value).toBe('200');
  });
  it('exports the inputs and calculation audit and escapes text in CSV',async()=>{
    const save=vi.spyOn(helpers,'download').mockImplementation(()=>{});const {user}=setup();await open(user);fill();edit('Pricing hypothesis','=1+1');
    await user.click(screen.getByRole('button',{name:'Calculate option price'}));await screen.findByRole('table',{name:'Derivative price sensitivity'});
    await user.click(screen.getByRole('button',{name:'Download pricing CSV'}));expect(save.mock.calls[0][0].content).toContain("'=1+1");expect(save.mock.calls[0][0].content).toContain('Vega / 1pp');
    await user.click(screen.getByRole('button',{name:'Download full pricing model'}));const data=JSON.parse(save.mock.calls[1][0].content);
    expect(data.inputs.hypothesis).toBe('=1+1');expect(data.result.unit_price).toBe(fixture.european.unit_price);
  });
  it('displays a zero model price and unavailable Greeks without hiding the result',async()=>{
    const zero={...fixture.european,unit_price:0,per_contract:0,total_premium:0,market_gap:null,greeks:{delta:null,gamma:null,theta:null,vega:null,rho:null}};
    const {user}=setup(()=>ok(zero));await open(user);fill();await user.click(screen.getByRole('button',{name:'Calculate option price'}));await screen.findByRole('table',{name:'Derivative price sensitivity'});
    expect(within(screen.getByLabelText('Pricing summary')).getAllByText('$0.00')).toHaveLength(2);
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(5);
  });
});
