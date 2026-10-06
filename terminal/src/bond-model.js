export const emptyBond=()=>({name:'',hypothesis:'',issuer_type:'government',currency:'USD',settlement:'',maturity:'',face_amount:'10000',coupon_rate:'',frequency:'2',day_count:'actual_actual',date_roll:'maturity_day',discounting:'compound',mode:'price',yield_percent:'',benchmark_yield:'',spread_bps:'',market_clean:''});
export function validBond(b){
  if(!b||!Object.keys(emptyBond()).every(k=>typeof b[k]==='string'&&b[k].length<=(k==='hypothesis'?3000:100)))return false;
  return Object.entries({issuer_type:['government','corporate'],currency:['USD','CAD','EUR','GBP'],frequency:['1','2','4'],day_count:['actual_actual','30u360'],date_roll:['maturity_day','month_end'],discounting:['compound','simple_final'],mode:['price','yield','spread']}).every(([key,values])=>values.includes(b[key]));
}
export function bondPayload(b){
  const numeric=['face_amount','coupon_rate','frequency','yield_percent','benchmark_yield','spread_bps','market_clean'];
  const out={...b,...Object.fromEntries(numeric.map(k=>[k,b[k]===''?null:Number(b[k])]))};
  if(b.mode!=='price')out.yield_percent=null;
  if(b.mode!=='spread'){out.benchmark_yield=null;out.spread_bps=null;}
  return out;
}
// Fictional, reproducible examples. No quotes, credentials or market API required.
export const bondExample=type=>({...emptyBond(),name:type==='corporate'?'Example Corporate 6% 2031':'Example Government 4% 2031',hypothesis:type==='corporate'?'Fictional example: how does a wider credit spread affect this five-year bond? All payments assumed made.':'Fictional example: a five-year 4% bond priced at a 4% yield on a coupon date.',issuer_type:type,settlement:'2026-10-01',maturity:'2031-10-01',coupon_rate:type==='corporate'?'6':'4',yield_percent:'4',mode:type==='corporate'?'spread':'price',benchmark_yield:type==='corporate'?'4':'',spread_bps:type==='corporate'?'150':'',day_count:type==='corporate'?'30u360':'actual_actual'});
