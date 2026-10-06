import React from 'react';
import {describe,it,expect,vi} from 'vitest';
import {render,screen,fireEvent,within,act} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App.jsx';
import {emptyAnalytics,upgradeAnalytics,validAnalytics} from './analytics-model.js';
import {emptyBond,bondPayload,validBond} from './bond-model.js';
import fixture from './fixtures/bond.json';
import * as helpers from './data.js';
vi.mock('recharts',async()=>{const actual=await vi.importActual('recharts');return {...actual,ResponsiveContainer:({children})=><div>{React.cloneElement(children,{width:600,height:280})}</div>};});
const ok=data=>({ok:true,json:async()=>data});
const edit=(label,value)=>fireEvent.change(screen.getByLabelText(label),{target:{value}});
function setup(handler){
  const records=new Map(),requests=[];
  vi.stubGlobal('fetch',vi.fn(async(url,options={})=>{
    const body=options.body?JSON.parse(options.body):null;requests.push({url,body});
    if(url==='/api/portfolios')return ok({portfolios:[...records.values()]});
    if(url==='/api/portfolios/save'){const record={...body,revision:body.revision+1};records.set(body.id,structuredClone(record));return ok(record);}
    if(url.startsWith('/api/portfolios/'))return ok(records.get(url.split('/').at(-1)));
    if(url==='/api/analytics/bond')return handler?handler(body):ok(body.mode==='spread'?fixture.corporate:body.mode==='yield'?fixture.yield:fixture.government);
    throw Error('Unexpected market request '+url);
  }));
  return {...render(<React.StrictMode><App/></React.StrictMode>),user:userEvent.setup(),records,requests};
}
async function open(user){await user.click(screen.getByRole('tab',{name:'Analytics Lab'}));await user.click(screen.getByRole('button',{name:'Bond Analytics',exact:true}));}
async function example(user,kind='Government'){await user.click(screen.getByRole('button',{name:kind+' bond example'}));await user.click(screen.getByRole('button',{name:'Load example'}));}

describe('Bond Analytics',()=>{
  it('runs a fictional offline example and distinguishes price, accrued, cash and DV01',async()=>{
    const {user,requests}=setup();await open(user);await example(user);
    await user.click(screen.getByRole('button',{name:'Calculate bond'}));
    await screen.findByRole('table',{name:'Bond cash flows'});
    expect(screen.getByRole('img',{name:'Bond clean price versus yield'})).toBeTruthy();expect(screen.getByRole('table',{name:'Bond yield shocks'})).toBeTruthy();
    expect(within(screen.getByLabelText('Bond price summary')).getAllByText('100.0000')).toHaveLength(2);
    expect(within(screen.getByLabelText('Bond price summary')).getByText('0.0000')).toBeTruthy();
    expect(within(screen.getByLabelText('Bond risk summary')).getByText('$4.49')).toBeTruthy();
    const sent=requests.find(r=>r.url==='/api/analytics/bond').body;
    expect(sent).toMatchObject({settlement:'2026-10-01',maturity:'2031-10-01',coupon_rate:4,frequency:2,face_amount:10000,yield_percent:4,benchmark_yield:null,spread_bps:null,market_clean:null});
    edit('Annual yield to maturity (%)','5');expect(screen.queryByRole('table',{name:'Bond cash flows'})).toBeNull();expect(screen.getByText(/Assumptions changed/)).toBeTruthy();
  });
  it('keeps example loading explicit so existing input is not lost on a first click',async()=>{
    const {user}=setup();await open(user);edit('Bond name / identifier','My research');
    await user.click(screen.getByRole('button',{name:'Corporate bond example'}));expect(screen.getByLabelText('Bond name / identifier').value).toBe('My research');
    await user.click(screen.getByRole('button',{name:'Cancel'}));expect(screen.getByLabelText('Bond name / identifier').value).toBe('My research');
  });
  it('solves yield from clean price and excludes dormant yield and spread inputs',async()=>{
    const {user,requests}=setup();await open(user);await example(user,'Corporate');
    await user.selectOptions(screen.getByLabelText('Bond calculation'),'yield');edit('Market clean price per 100','99');
    await user.click(screen.getByRole('button',{name:'Calculate bond'}));await screen.findByRole('table',{name:'Bond cash flows'});
    expect(requests.find(r=>r.url==='/api/analytics/bond').body).toMatchObject({mode:'yield',market_clean:99,yield_percent:null,benchmark_yield:null,spread_bps:null});
    expect(within(screen.getByLabelText('Bond price summary')).getByText('4.2240%')).toBeTruthy();
    expect(screen.getByText('Market yield to maturity')).toBeTruthy();
    await user.selectOptions(screen.getByLabelText('Bond calculation'),'spread');expect(screen.getByLabelText('Yield spread (basis points)').value).toBe('150');
  });
  it('shows a corporate benchmark/spread matrix and propagates currency',async()=>{
    const {user,requests}=setup();await open(user);await example(user,'Corporate');await user.selectOptions(screen.getByLabelText('Bond currency'),'GBP');
    expect(screen.getByText('GBP · Your assumptions')).toBeTruthy();
    await user.click(screen.getByRole('button',{name:'Calculate bond'}));await screen.findByRole('table',{name:'Bond credit spread sensitivity'});
    expect(within(screen.getByLabelText('Bond price summary')).getByText('5.5000%')).toBeTruthy();
    expect(requests.find(r=>r.url==='/api/analytics/bond').body).toMatchObject({issuer_type:'corporate',currency:'GBP',mode:'spread',benchmark_yield:4,spread_bps:150,day_count:'30u360'});
  });
  it('saves incomplete bond drafts alongside equity and derivative inputs',async()=>{
    const {user,records,unmount}=setup();await user.click(screen.getByRole('tab',{name:'Analytics Lab'}));edit('Company / ticker','Equity notes');
    await user.click(screen.getByRole('button',{name:'Option pricing',exact:true}));edit('Strike price','123');
    await user.click(screen.getByRole('button',{name:'Bond Analytics',exact:true}));edit('Bond name / identifier','Corporate notes');edit('Annual coupon rate (%)','6.123456');
    unmount();const next=render(<App/>);expect(screen.getByLabelText('Annual coupon rate (%)').value).toBe('6.123456');
    edit('Portfolio name','Bond research');await user.click(screen.getByRole('button',{name:'Save portfolio'}));await screen.findByText('Portfolio saved to this device.');
    const [id,record]=[...records.entries()][0];expect(record.state.analytics.bond_pricing.maturity).toBe('');expect(record.state.analytics.option_pricing.strike).toBe('123');expect(record.state.analytics.company).toBe('Equity notes');
    next.unmount();localStorage.clear();sessionStorage.clear();render(<App/>);await screen.findByRole('option',{name:'Bond research'});
    await user.selectOptions(screen.getByLabelText('Saved portfolios'),id);await user.click(screen.getByRole('button',{name:'Load',exact:true}));await screen.findByLabelText('Bond name / identifier');
    expect(screen.getByLabelText('Annual coupon rate (%)').value).toBe('6.123456');expect(screen.getByLabelText('Bond maturity date').value).toBe('');
  });
  it('upgrades earlier lab drafts and validates the new bond draft',()=>{
    const old=emptyAnalytics();old.version=2;delete old.bond_pricing;old.tool='option';old.option_pricing.strike='123.456';
    expect(validAnalytics(old)).toBe(true);const next=upgradeAnalytics(old);expect(next.version).toBe(3);expect(next.bond_pricing).toEqual(emptyBond());expect(next.option_pricing.strike).toBe('123.456');expect(next.tool).toBe('option');
    expect(validAnalytics(next)).toBe(true);expect(validBond({...next.bond_pricing,frequency:'12'})).toBe(false);expect(bondPayload(emptyBond()).coupon_rate).toBeNull();
  });
  it('preserves input on errors and ignores results for superseded assumptions',async()=>{
    let finish;const {user}=setup(()=>new Promise(resolve=>{finish=resolve;}));await open(user);await example(user);
    await user.click(screen.getByRole('button',{name:'Calculate bond'}));edit('Annual yield to maturity (%)','5');
    await act(async()=>finish(ok(fixture.government)));expect(screen.queryByRole('table',{name:'Bond cash flows'})).toBeNull();
    await user.click(screen.getByRole('button',{name:'Calculate bond'}));await act(async()=>finish({ok:false,json:async()=>({error:'Check the settlement date.'})}));
    expect(screen.getByRole('alert').textContent).toBe('Check the settlement date.');expect(screen.getByLabelText('Annual yield to maturity (%)').value).toBe('5');
  });
  it('downloads an auditable model and CSV with escaped hypothesis text',async()=>{
    const save=vi.spyOn(helpers,'download').mockImplementation(()=>{});const {user}=setup();await open(user);await example(user);edit('Bond hypothesis','=1+1');
    await user.click(screen.getByRole('button',{name:'Calculate bond'}));await screen.findByRole('table',{name:'Bond cash flows'});
    await user.click(screen.getByRole('button',{name:'Download bond CSV'}));expect(save.mock.calls[0][0].content).toContain("'=1+1");expect(save.mock.calls[0][0].content).toContain('Discount factor');
    await user.click(screen.getByRole('button',{name:'Download bond model'}));const model=JSON.parse(save.mock.calls[1][0].content);expect(model.inputs.hypothesis).toBe('=1+1');expect(model.result.cashflows).toHaveLength(10);
  });
});
