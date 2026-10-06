import {emptyOptions,blankLeg,setupSnapshot} from './options-model.js';

export function keepAndTransfer(current,next){
  const occupied=!!(current.symbol||current.spot||current.scenario_price||current.legs.some(l=>l.premium!==''||l.strike!==''));
  if(occupied&&current.scenarios.length>=12)throw Error('All 12 kept-scenario slots are full. Save a portfolio copy or remove a kept scenario before transferring.');
  const scenarios=[...current.scenarios];
  if(occupied)scenarios.push({id:crypto.randomUUID(),name:(current.scenario_name||'Before Analytics transfer').slice(0,80),state:setupSnapshot(current)});
  return {...next,finder:current.finder,scenarios};
}
function currency(value){if(!['USD','CAD'].includes(value))throw Error('Options Lab currently supports USD and CAD. No currency conversion is inferred.');}
function ticker(value){const s=value.trim().toUpperCase();if(!/^[A-Z0-9^][A-Z0-9.^=-]{0,39}$/.test(s))throw Error('Enter an exact ticker for the strategy. A company name is not a verified ticker.');return s;}
export function equityTransfer(a,choice,symbol,targetDate){
  currency(a.currency);
  if(!Number.isFinite(choice?.price)||choice.price<=0)throw Error('Select a positive fair-value estimate.');
  if(!/^\d{4}-\d{2}-\d{2}$/.test(targetDate)||targetDate<=a.valuation_date)throw Error('Choose a target date after the valuation date.');
  const next=emptyOptions();
  return {...next,currency:a.currency,symbol:ticker(symbol),spot:a.current_price,as_of:a.valuation_date,
    target_date:targetDate,scenario_price:String(choice.price),scenario_name:`DCF ${choice.case} · ${choice.method}`.slice(0,80),
    legs:[{...blankLeg(),quote_note:`DCF ${choice.case} / ${choice.method} on ${a.valuation_date}: target ${choice.price} ${a.currency} at a user-selected horizon. Not a market quote.`.slice(0,500)}]};
}
export function optionTransfer(a,result,symbol){
  currency(a.currency);
  if(a.exercise!=='european')throw Error('The dated strategy engine is European. American pricing cannot be transferred as an equivalent model.');
  if(!Number.isInteger(Number(a.contract_size))||Number(a.contract_size)>1000000)throw Error('Options Lab requires a whole-number contract multiplier up to 1,000,000.');
  return {...emptyOptions(),symbol:ticker(symbol),currency:a.currency,strategy:a.kind==='call'?'long_call':'long_put',
    spot:a.spot,as_of:a.as_of,target_date:a.maturity,rate:a.rate,dividend_yield:a.dividend_yield,
    probability_iv:a.volatility,scenario_name:'Analytics option hypothesis',
    legs:[{...blankLeg(a.kind,'buy',a.contracts),multiplier:a.contract_size,strike:a.strike,expiration:a.maturity,iv:a.volatility,
      premium:a.market_price,quote_note:`Analytics ${result.model}: model value ${result.unit_price} ${a.currency}/unit on ${a.as_of}. Entry premium is only the separately entered market quote.`.slice(0,500)}]};
}
