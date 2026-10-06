import React from 'react';
import {describe,it,expect,vi} from 'vitest';
import {render,screen,fireEvent,act,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App.jsx';

const identity={ticker:'AAA',name:'Example AAA',exchange:'NYSE',currency:'USD'};
const ok=data=>({ok:true,json:async()=>data});
const fail=message=>({ok:false,json:async()=>({error:message})});
function setup({records=new Map(),saveHandler,loadHandler}={}) {
  vi.stubGlobal('fetch',vi.fn(async(url,options={})=>{
    const body=options.body?JSON.parse(options.body):null;
    if(url==='/api/portfolios')return ok({portfolios:[...records.values()]});
    if(url==='/api/portfolios/save'){
      if(saveHandler)return saveHandler(body);
      const old=records.get(body.id);
      if(old&&old.revision!==body.revision)return fail('This portfolio was changed elsewhere. Save a copy.');
      // The real API returns model fields in schema order, not request order.
      const state=Object.fromEntries(Object.entries(body.state).sort(([a],[b])=>a.localeCompare(b)));
      const record={...body,state,revision:(old?.revision||0)+1};records.set(body.id,structuredClone(record));return ok(record);
    }
    if(url.startsWith('/api/portfolios/'))return loadHandler?loadHandler(url):ok(records.get(url.split('/').at(-1)));
    if(url.startsWith('/api/search'))return ok({matches:[identity]});
    if(url.startsWith('/api/instrument'))return ok(identity);
    if(url==='/api/allocation')return ok({positions:[],cash_balance:body.total_invested,preview:{columns:[],index:[],data:[]}});
    throw new Error('Unexpected request: '+url);
  }));
  const mounted=render(<React.StrictMode><App/></React.StrictMode>);return {...mounted,user:userEvent.setup(),records};
}
const edit=(label,value)=>fireEvent.change(screen.getByLabelText(label),{target:{value}});
async function add(user) {
  await user.type(screen.getByPlaceholderText('AAPL or Apple'),'Example');
  await user.click(screen.getByRole('button',{name:'Search tickers'}));
  await user.click(await screen.findByRole('button',{name:'Add selected ticker'}));
  await screen.findByLabelText('AAA quantity');
}

describe('saved portfolios and recovery',()=>{
  it('automatically restores incomplete inputs and separate allocation amounts after a refresh',async()=>{
    const {user,unmount}=setup();await add(user);
    edit('AAA purchase price','80.125');edit('Uninvested cash (USD)','345.67');edit('Portfolio name','Retirement draft');
    await user.click(screen.getByRole('button',{name:'Allocation',exact:true}));
    edit('AAA allocation','35');edit('AAA purchase price','100');
    await user.selectOptions(screen.getByLabelText('Allocate by'),'dollars');edit('AAA allocation','1234.56');
    unmount();render(<App/>);
    expect(screen.getByLabelText('Portfolio name').value).toBe('Retirement draft');
    expect(screen.getByLabelText('AAA allocation').value).toBe('1234.56');
    await user.selectOptions(screen.getByLabelText('Allocate by'),'percent');expect(screen.getByLabelText('AAA allocation').value).toBe('35');
    await user.click(screen.getByRole('button',{name:'Quantity',exact:true}));
    expect(screen.getByLabelText('AAA quantity').value).toBe('');
    expect(screen.getByLabelText('AAA purchase price').value).toBe('80.125');
    expect(screen.getByLabelText('Uninvested cash (USD)').value).toBe('345.67');
    expect(screen.queryByText('Portfolio vs. benchmark')).toBeNull();
  });

  it('loads named portfolios from device storage even after browser drafts are cleared',async()=>{
    const {user,unmount,records}=setup();await add(user);edit('AAA quantity','2.125');edit('AAA purchase price','80');edit('Portfolio name','Growth');
    await user.click(screen.getByRole('button',{name:'Save portfolio'}));await screen.findByText('Portfolio saved to this device.');
    expect(records.size).toBe(1);const id=[...records.keys()][0];
    unmount();localStorage.clear();sessionStorage.clear();render(<App/>);
    await screen.findByRole('option',{name:'Growth'});
    await user.selectOptions(screen.getByLabelText('Saved portfolios'),id);await user.click(screen.getByRole('button',{name:'Load',exact:true}));
    await screen.findByLabelText('AAA quantity');expect(screen.getByLabelText('AAA quantity').value).toBe('2.125');
    expect(screen.queryByText('Portfolio vs. benchmark')).toBeNull();
    expect(screen.getByText('Saved to this device')).toBeTruthy();
  });

  it('keeps edits made while saving and includes them in the next save',async()=>{
    let finish;let sent;
    const {user}=setup({saveHandler:body=>{sent=body;return new Promise(resolve=>{finish=resolve;});}});
    edit('Uninvested cash (USD)','100');edit('Portfolio name','Cash');
    await user.click(screen.getByRole('button',{name:'Save portfolio'}));edit('Uninvested cash (USD)','200');
    await act(async()=>finish(ok({...sent,revision:1})));
    expect(screen.getByLabelText('Uninvested cash (USD)').value).toBe('200');
    await screen.findByText('Portfolio saved. Newer edits remain in your recovery draft; save again to include them.');
    await user.click(screen.getByRole('button',{name:'Save portfolio'}));
    expect(sent.state.cash).toBe('200');expect(sent.revision).toBe(1);
    await act(async()=>finish(ok({...sent,revision:2})));
  });

  it('failed saves and loads keep inputs and allow saving a separate copy',async()=>{
    const records=new Map();const {user}=setup({records});
    edit('Uninvested cash (USD)','100');edit('Portfolio name','Original');
    await user.click(screen.getByRole('button',{name:'Save portfolio'}));await screen.findByText('Portfolio saved to this device.');
    const saved=[...records.values()][0];records.set(saved.id,{...saved,revision:2});
    edit('Uninvested cash (USD)','200');await user.click(screen.getByRole('button',{name:'Save portfolio'}));
    await screen.findByText('This portfolio was changed elsewhere. Save a copy.');
    expect(screen.getByLabelText('Uninvested cash (USD)').value).toBe('200');
    await user.click(screen.getByRole('button',{name:'Make a copy'}));
    expect(screen.getByLabelText('Portfolio name').value).toBe('Original copy');
    await user.click(screen.getByRole('button',{name:'Save portfolio'}));await screen.findByText('Portfolio saved to this device.');
    expect(records.size).toBe(2);expect(records.get(saved.id).state.cash).toBe('100');
  });

  it('reports unavailable draft storage while named saves still work',async()=>{
    const {user,records}=setup();
    vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw new DOMException('Quota exceeded','QuotaExceededError');});
    edit('Uninvested cash (USD)','100');edit('Portfolio name','Safe copy');
    expect(screen.getByText('Browser draft recovery is unavailable. Use Save portfolio before closing.')).toBeTruthy();
    await user.click(screen.getByRole('button',{name:'Save portfolio'}));await screen.findByText('Portfolio saved to this device.');
    expect(records.size).toBe(1);
  });

  it('retains earlier drafts when starting a new portfolio',async()=>{
    const {user}=setup();edit('Uninvested cash (USD)','123');edit('Portfolio name','Unfinished');
    await user.click(screen.getByRole('button',{name:'New portfolio'}));
    expect(screen.getByLabelText('Uninvested cash (USD)').value).toBe('0');
    const summary=screen.getByText('Draft recovery');await user.click(summary);
    const option=await screen.findByRole('option',{name:/Unfinished ·/});
    await user.selectOptions(screen.getByLabelText('Recovery draft'),option.value);
    await user.click(screen.getByRole('button',{name:'Restore draft'}));
    expect(screen.getByLabelText('Uninvested cash (USD)').value).toBe('123');
    expect(screen.getByLabelText('Portfolio name').value).toBe('Unfinished');
  });
});
