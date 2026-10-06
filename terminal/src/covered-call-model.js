export const emptyCoveredCall=()=>({version:1,source:'market',ticker:'AAPL',start:'',end:'',capital:'25000',contracts:'1',tenor_sessions:'20',otm_percent:'5',strike_increment:'1',roll_before:'0',volatility_mode:'fixed',volatility_percent:'25',volatility_window:'30',volatility_premium:'5',rate_percent:'0',dividend_yield_percent:'0',stock_fee_bps:'1',stock_slippage_bps:'5',option_fee:'.65',option_half_spread_percent:'5',assignment_fee:'0',hypothesis:''});
export function validCoveredCall(s){return !!s&&s.version===1&&['market','demo'].includes(s.source)&&['fixed','trailing'].includes(s.volatility_mode)&&Object.entries(emptyCoveredCall()).filter(([,v])=>typeof v==='string').every(([k])=>typeof s[k]==='string'&&s[k].length<=(k==='hypothesis'?3000:k==='ticker'?40:100));}
export function coveredCallPayload(s){
  const {version,hypothesis,...out}=s;
  for(const k of Object.keys(out))if(!['source','ticker','start','end','volatility_mode'].includes(k))out[k]=s[k]===''?null:Number(s[k]);
  out.ticker=s.ticker.trim().toUpperCase();
  if(s.volatility_mode==='fixed'){out.volatility_window=30;out.volatility_premium=5;}else out.volatility_percent=25;
  return out;
}
export const coveredCallExample=()=>({...emptyCoveredCall(),source:'demo',ticker:'DEMO-CC',start:'2024-01-02',end:'2024-12-31',hypothesis:'Fictional example: compare a covered call with holding the same 100 stock units. Check how assumed volatility and transaction costs change the outcome.'});
