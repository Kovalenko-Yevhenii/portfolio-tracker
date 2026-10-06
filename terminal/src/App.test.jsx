import React from 'react';
import {describe,it,expect,vi} from 'vitest';
import {render,screen,waitFor,fireEvent,act} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {Tracker as App} from './App.jsx';
import fixture from './fixtures/analysis.json';

vi.mock('recharts',async importOriginal=>{
  const actual=await importOriginal();
  return {...actual,ResponsiveContainer:({children})=>React.cloneElement(children,{width:700,height:280})};
});
const identity={ticker:'AAA',name:'Example AAA',exchange:'NYSE',currency:'USD'};
const success=data=>({ok:true,json:async()=>data});
function setup(handler=()=>success(fixture)) {
  const requests=[];
  vi.stubGlobal('fetch',vi.fn(async(url,options={})=>{
    const body=options.body?JSON.parse(options.body):undefined;requests.push({url,body});
    if(url.startsWith('/api/search'))return success({matches:[identity]});
    if(url.startsWith('/api/instrument'))return success(identity);
    return handler(url,body);
  }));
  render(<App/>);return {user:userEvent.setup(),requests};
}
async function addHolding(user) {
  await user.type(screen.getByPlaceholderText('AAPL or Apple'),'Example');
  await user.click(screen.getByRole('button',{name:'Search tickers'}));
  await user.click(await screen.findByRole('button',{name:'Add selected ticker'}));
  await screen.findByRole('button',{name:'Remove AAA'});
}
function edit(label,value) {fireEvent.change(screen.getByLabelText(label),{target:{value}});}

describe('terminal workflows',()=>{
  it('starts with real entry controls and no invented portfolio values',()=>{
    setup();expect(screen.getByRole('button',{name:'Analyze'}).disabled).toBe(true);
    expect(screen.queryByText('$124,850')).toBeNull();
    expect(screen.getByRole('textbox',{name:'Ticker or company name'})).toBeTruthy();
  });

  it('verifies a selected ticker, sends fractional holdings, and shows downloadable analysis',async()=>{
    const {user,requests}=setup();await addHolding(user);
    edit('AAA quantity','2.125');edit('AAA purchase price','80');edit('Uninvested cash (USD)','100');
    await user.click(screen.getByRole('button',{name:'Analyze portfolio'}));
    await screen.findByText('Portfolio vs. benchmark');
    const request=requests.find(r=>r.url==='/api/analyze').body;
    expect(request.positions).toEqual([{ticker:'AAA',qty:2.125,avg_cost:80}]);
    expect(request.cash_balance).toBe(100);
    expect(requests.some(r=>r.url==='/api/instrument?symbol=AAA')).toBe(true);
    expect(screen.getByRole('button',{name:'positions_with_prices.csv'})).toBeTruthy();
    await user.click(screen.getByRole('tab',{name:'Risk'}));
    expect(screen.getByRole('table',{name:'Risk contributions'})).toBeTruthy();
    expect(screen.getByRole('table',{name:'Correlation matrix'})).toBeTruthy();
  });

  it('discards an in-flight result when holdings change',async()=>{
    let finish;
    const {user}=setup(()=>new Promise(resolve=>{finish=resolve;}));
    await addHolding(user);edit('AAA quantity','2');edit('AAA purchase price','80');
    await user.click(screen.getByRole('button',{name:'Analyze portfolio'}));
    edit('AAA quantity','5');
    await act(async()=>finish(success(fixture)));
    await screen.findByText('Inputs changed during calculation. Analyze again to use the latest values.');
    expect(screen.queryByText('Portfolio vs. benchmark')).toBeNull();
    expect(screen.queryByRole('button',{name:'portfolio_timeseries.csv'})).toBeNull();
  });

  it('keeps quantity, percent and dollar entry values separate',async()=>{
    const {user}=setup((url,body)=>url==='/api/allocation'?success({positions:[],cash_balance:body.total_invested,preview:{columns:[],index:[],data:[]}}):success(fixture));
    await addHolding(user);edit('AAA quantity','7.25');edit('AAA purchase price','80');
    await user.click(screen.getByRole('button',{name:'Allocation',exact:true}));
    edit('AAA allocation','30');edit('AAA purchase price','90');
    await user.selectOptions(screen.getByLabelText('Allocate by'),'dollars');edit('AAA allocation','250');
    await user.selectOptions(screen.getByLabelText('Allocate by'),'percent');expect(screen.getByLabelText('AAA allocation').value).toBe('30');
    await user.selectOptions(screen.getByLabelText('Allocate by'),'dollars');expect(screen.getByLabelText('AAA allocation').value).toBe('250');
    await user.click(screen.getByRole('button',{name:'Quantity',exact:true}));expect(screen.getByLabelText('AAA quantity').value).toBe('7.25');
    expect(screen.getByLabelText('AAA purchase price').value).toBe('80');
  });

  it('research uses independent tickers and changed settings hide previous exports',async()=>{
    const research={...fixture,mode:'research',metrics:null,positions:null,diversification:null};
    const {user,requests}=setup(()=>success(research));
    await user.click(screen.getByRole('tab',{name:'Research'}));await addHolding(user);
    await user.click(screen.getByRole('tab',{name:'Settings'}));
    await user.selectOptions(screen.getByLabelText(/^Return basis/),'total');
    await user.selectOptions(screen.getByLabelText('Observation interval'),'1wk');
    fireEvent.change(screen.getByLabelText(/^Annual risk-free rate/),{target:{value:'4'}});
    await user.click(screen.getByRole('button',{name:'Analyze with these settings'}));
    await screen.findByRole('heading',{name:'Research comparison'});
    const request=requests.find(r=>r.url==='/api/analyze').body;
    expect(request).toMatchObject({mode:'research',tickers:['AAA'],positions:[],return_basis:'total',interval:'1wk',annual_risk_free_rate:.04});
    await user.click(screen.getByRole('tab',{name:'Settings'}));
    await user.selectOptions(screen.getByLabelText('History period'),'5y');
    await user.click(screen.getByRole('tab',{name:'Overview'}));
    expect(screen.queryByRole('button',{name:'comparison_normalized_price.csv'})).toBeNull();
    expect(screen.getByText('Inputs have changed. Analyze again to update charts and downloads.')).toBeTruthy();
  });

  it('a bad CSV replaces neither the accepted input nor the displayed result',async()=>{
    const {user}=setup((url,body)=>url==='/api/import'?(body.text==='valid'?success({positions:[{ticker:'AAA',qty:2,avg_cost:80}]}):{ok:false,json:async()=>({error:'Invalid holdings on CSV row 2.'})}):success(fixture));
    await user.click(screen.getByRole('button',{name:'CSV upload'}));
    const file=new File(['valid'],'holdings.csv',{type:'text/csv'});file.text=async()=> 'valid';
    await user.upload(screen.getByLabelText('Upload holdings CSV'),file);
    await screen.findByText('holdings.csv · 1 holdings imported');
    await user.click(screen.getByRole('button',{name:'Analyze portfolio'}));await screen.findByText('Portfolio vs. benchmark');
    await user.click(screen.getByRole('tab',{name:'Holdings'}));
    const bad=new File(['invalid'],'bad.csv',{type:'text/csv'});bad.text=async()=> 'invalid';
    await user.upload(screen.getByLabelText('Upload holdings CSV'),bad);
    await screen.findByText('Invalid holdings on CSV row 2.');
    expect(screen.getByRole('button',{name:'Analyze'}).disabled).toBe(true);
    await user.click(screen.getByRole('tab',{name:'Overview'}));
    expect(screen.queryByText('Portfolio vs. benchmark')).toBeNull();
  });
});
