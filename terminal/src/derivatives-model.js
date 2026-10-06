const common=()=>({symbol:'',hypothesis:'',currency:'USD',as_of:'',maturity:'',spot:'',rate:'0',contracts:'1',contract_size:''});
export const emptyOptionPricing=()=>({...common(),exercise:'european',kind:'call',strike:'',volatility:'',dividend_yield:'0',market_price:'',tree_steps:'500',contract_size:'100'});
export const emptyFuturesPricing=()=>({...common(),asset:'equity',income_yield:'0',foreign_rate:'0',storage_rate:'0',convenience_yield:'0',market_price:''});
export function validDerivative(d,type){
  if(!d||!['USD','CAD','EUR','GBP'].includes(d.currency))return false;
  const fields=Object.keys(type==='option'?emptyOptionPricing():emptyFuturesPricing());
  if(!fields.every(k=>typeof d[k]==='string'&&d[k].length<=(k==='hypothesis'?3000:k==='symbol'?80:100)))return false;
  return type==='option'?['european','american'].includes(d.exercise)&&['call','put'].includes(d.kind)&&['250','500','1000'].includes(d.tree_steps):['equity','fx','commodity'].includes(d.asset);
}
export function derivativesPayload(d,type){
  const text=['symbol','hypothesis','currency','as_of','maturity',...(type==='option'?['exercise','kind']:['asset'])];
  const numbers=['spot','rate','contracts','contract_size','market_price',...(type==='option'?['strike','volatility','dividend_yield','tree_steps']:['income_yield','foreign_rate','storage_rate','convenience_yield'])];
  const payload={...Object.fromEntries(text.map(k=>[k,d[k]])),...Object.fromEntries(numbers.map(k=>[k,d[k]===''?null:Number(d[k])]))};
  if(type==='futures'){
    if(d.asset!=='equity')payload.income_yield=0;
    if(d.asset!=='fx')payload.foreign_rate=0;
    if(d.asset!=='commodity'){payload.storage_rate=0;payload.convenience_yield=0;}
  }
  return payload;
}
