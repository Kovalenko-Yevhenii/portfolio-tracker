import React from 'react';
import {describe,it,expect,vi} from 'vitest';
import {render,screen,fireEvent,within,act} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App.jsx';
import {emptyAnalytics,validAnalytics,analyticsPayload} from './analytics-model.js';
import fixture from './fixtures/analytics.json';
import * as helpers from './data.js';
const ok=data=>({ok:true,json:async()=>data});
const edit=(label,value)=>fireEvent.change(screen.getByLabelText(label),{target:{value}});
function setup(handler){
  const records=new Map(),requests=[];
  vi.stubGlobal('fetch',vi.fn(async(url,options={})=>{
    const body=options.body?JSON.parse(options.body):null;requests.push({url,body});
    if(url==='/api/portfolios')return ok({portfolios:[...records.values()]});
    if(url==='/api/portfolios/save'){const record={...body,revision:body.revision+1};records.set(body.id,record);return ok(record);}
    if(url.startsWith('/api/portfolios/'))return ok(records.get(url.split('/').at(-1)));
    if(url==='/api/analytics/valuation')return handler?handler(body):ok(fixture);
    throw Error('Unexpected external data request '+url);
  }));
  return {...render(<React.StrictMode><App/></React.StrictMode>),user:userEvent.setup(),records,requests};
}
async function fill(user){
  await user.click(screen.getByRole('tab',{name:'Analytics Lab'}));
  edit('Company / ticker','Example');edit('Valuation date','2026-09-30');edit('Diluted shares (millions)','10');edit('Current share price (optional)','50');
  edit('Base WACC (%)','10');edit('Base Terminal growth (%)','0');
  for(const [label,value] of [['EBIT','100'],['Tax %','20'],['D&A','10'],['Capital expenditure','10'],['Change in operating NWC','0']])edit('Base year 1 '+label,value);
  await user.click(screen.getByRole('button',{name:'Repeat year 1 across Base forecast'}));
}

describe('Analytics Lab',()=>{
  it('calculates a manual DCF and shows football field, sensitivity, and auditable cash flows',async()=>{
    const {user,requests}=setup();await fill(user);
    expect(screen.queryByRole('button',{name:'Refresh market data and analyze'})).toBeNull();
    await user.click(screen.getByRole('button',{name:'Calculate valuation'}));
    await screen.findByRole('img',{name:'Football field valuation ranges and current share price'});
    expect(screen.getByRole('table',{name:'DCF cash flow audit'})).toBeTruthy();expect(screen.getByRole('table',{name:'Sensitivity growth'})).toBeTruthy();
    const sent=requests.find(r=>r.url==='/api/analytics/valuation').body;
    expect(sent.cases).toHaveLength(1);expect(sent.cases[0].years).toHaveLength(5);expect(sent.cases[0].years[4].ebit).toBe('100');expect(sent.comps).toBeNull();
    edit('Base WACC (%)','11');expect(screen.queryByRole('table',{name:'Valuation ranges'})).toBeNull();expect(screen.getByText('Assumptions changed. Calculate again to refresh the valuation.')).toBeTruthy();
  });
  it('copies explicit Base assumptions into Bear and keeps their edits independent',async()=>{
    const {user,requests}=setup();await fill(user);
    await user.click(screen.getByRole('button',{name:'Bear',exact:true}));await user.click(screen.getByRole('button',{name:'Copy Base into Bear'}));
    expect(screen.getByLabelText('Bear WACC (%)').value).toBe('10');edit('Bear year 1 EBIT','80');
    await user.click(screen.getByRole('button',{name:'Base · included'}));expect(screen.getByLabelText('Base year 1 EBIT').value).toBe('100');
    await user.click(screen.getByRole('button',{name:'Calculate valuation'}));await screen.findByRole('table',{name:'Valuation ranges'});
    const sent=requests.find(r=>r.url==='/api/analytics/valuation').body;expect(sent.cases).toHaveLength(2);expect(sent.cases.find(c=>c.name==='Bear').years[0].ebit).toBe('80');
  });
  it('supports comps alone and omits blank peer rows from requests',async()=>{
    const {user,requests}=setup();await fill(user);await user.click(screen.getByLabelText('Include DCF'));await user.click(screen.getByLabelText('Include comps'));await user.click(screen.getByRole('button',{name:'Comparable companies'}));
    edit('Shared comparison period / basis','FY2027');edit('Target EBITDA','100');
    for(const i of [1,2]){edit(`Peer ${i} Peer name`,'Peer '+i);edit(`Peer ${i} Enterprise value`,String(i*1000));edit(`Peer ${i} EBITDA`,'100');}
    await user.click(screen.getByRole('button',{name:'Calculate valuation'}));await screen.findByRole('table',{name:'Valuation ranges'});
    const sent=requests.find(r=>r.url==='/api/analytics/valuation').body;expect(sent.cases).toEqual([]);expect(sent.comps.peers).toHaveLength(2);expect(sent.comps.peers[0].net_income).toBeNull();
  });
  it('restores incomplete analytics assumptions from drafts and named saves',async()=>{
    const {user,unmount,records}=setup();await user.click(screen.getByRole('tab',{name:'Analytics Lab'}));edit('Investment hypothesis','Margins recover');edit('Base WACC (%)','8.123456789123');edit('Portfolio name','Valuation draft');
    await user.click(screen.getByRole('button',{name:'Save portfolio'}));await screen.findByText('Portfolio saved to this device.');const record=[...records.values()][0];expect(record.state.analytics.hypothesis).toBe('Margins recover');
    unmount();const restored=render(<App/>);expect(screen.getByLabelText('Base WACC (%)').value).toBe('8.123456789123');expect(screen.getByLabelText('Base year 1 EBIT').value).toBe('');
    restored.unmount();localStorage.clear();sessionStorage.clear();render(<App/>);await screen.findByRole('option',{name:'Valuation draft'});await user.selectOptions(screen.getByLabelText('Saved portfolios'),record.id);await user.click(screen.getByRole('button',{name:'Load',exact:true}));
    await screen.findByLabelText('Investment hypothesis');expect(screen.getByLabelText('Investment hypothesis').value).toBe('Margins recover');expect(screen.queryByRole('table',{name:'Valuation ranges'})).toBeNull();
  });
  it('ignores a response if assumptions change while calculating and preserves inputs on failure',async()=>{
    let finish;const {user}=setup(()=>new Promise(resolve=>{finish=resolve;}));await fill(user);await user.click(screen.getByRole('button',{name:'Calculate valuation'}));edit('Base WACC (%)','12');
    await act(async()=>finish(ok(fixture)));expect(screen.queryByRole('table',{name:'Valuation ranges'})).toBeNull();
    await user.click(screen.getByRole('button',{name:'Calculate valuation'}));await act(async()=>finish({ok:false,json:async()=>({error:'Check terminal growth.'})}));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent','Check terminal growth.');expect(screen.getByLabelText('Base WACC (%)').value).toBe('12');
  });
  it('exports the calculation trail and full assumptions without formula injection',async()=>{
    const save=vi.spyOn(helpers,'download').mockImplementation(()=>{});const {user}=setup();await fill(user);edit('Investment hypothesis','=1+1');await user.click(screen.getByRole('button',{name:'Calculate valuation'}));await screen.findByRole('table',{name:'Valuation ranges'});
    await user.click(screen.getByRole('button',{name:'Download calculation CSV'}));expect(save.mock.calls[0][0].content).toContain('PV FCFF');expect(save.mock.calls[0][0].content).toContain("'=1+1");
    await user.click(screen.getByRole('button',{name:'Download full model'}));expect(JSON.parse(save.mock.calls[1][0].content).inputs.hypothesis).toBe('=1+1');
  });
  it('validates draft structure and preserves decimal input strings',()=>{
    const draft=emptyAnalytics();expect(validAnalytics(draft)).toBe(true);expect(validAnalytics({...draft,version:4})).toBe(false);expect(validAnalytics({...draft,cases:[]})).toBe(false);
    draft.shares='12.123456789123';expect(analyticsPayload(draft).shares).toBe('12.123456789123');expect(analyticsPayload(draft).cases[0].years[0].ebit).toBeNull();
  });
});
