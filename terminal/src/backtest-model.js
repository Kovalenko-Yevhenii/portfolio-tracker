export const emptyBacktest=()=>({version:1,source:'market',strategy:'sma',start:'',end:'',capital:'10000',assets:[{ticker:'SPY',weight:'100'}],benchmark:'SPY',window:'50',commission_bps:'0',fee_per_order:'0',slippage_bps:'5',risk_free_percent:'0',hypothesis:''});
export function validBacktest(b){
  return !!b&&b.version===1&&['market','demo'].includes(b.source)&&['sma','buy_hold'].includes(b.strategy)
    &&Object.entries(emptyBacktest()).filter(([,v])=>typeof v==='string').every(([k])=>typeof b[k]==='string'&&b[k].length<=(k==='hypothesis'?3000:k==='benchmark'?40:100))
    &&Array.isArray(b.assets)&&b.assets.length>=1&&b.assets.length<=10&&b.assets.every(a=>typeof a.ticker==='string'&&a.ticker.length<=40&&typeof a.weight==='string'&&a.weight.length<=100);
}
export function backtestPayload(b){
  const {version,hypothesis,...values}=b;
  const numeric=['capital','window','commission_bps','fee_per_order','slippage_bps','risk_free_percent'];
  return {...values,...Object.fromEntries(numeric.map(k=>[k,b[k]===''?null:Number(b[k])])),window:b.strategy==='buy_hold'?50:(b.window===''?null:Number(b.window)),assets:b.assets.map(a=>({ticker:a.ticker.trim().toUpperCase(),weight:a.weight===''?null:Number(a.weight)})),benchmark:b.benchmark.trim().toUpperCase()};
}
export const backtestExample=()=>({...emptyBacktest(),source:'demo',start:'2024-01-02',end:'2025-12-31',assets:[{ticker:'DEMO-A',weight:'60'},{ticker:'DEMO-B',weight:'40'}],benchmark:'DEMO-MKT',hypothesis:'Fictional example: does a 50-session trend rule reduce declines compared with holding the same 60/40 basket? Test another date range before drawing conclusions.'});
