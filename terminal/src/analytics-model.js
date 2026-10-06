import {emptyBond,validBond} from './bond-model.js';
import {emptyOptionPricing,emptyFuturesPricing,validDerivative} from './derivatives-model.js';
export const yearFields=['ebit','tax_rate','depreciation','capex','change_nwc'];
export const peerFields=['name','enterprise_value','equity_value','revenue','ebitda','net_income'];
export const blankYear=()=>Object.fromEntries(yearFields.map(k=>[k,'']));
export const blankPeer=()=>Object.fromEntries(peerFields.map(k=>[k,'']));
export const emptyAnalytics=()=>({version:3,bond_pricing:emptyBond(),tool:'equity',option_pricing:emptyOptionPricing(),futures_pricing:emptyFuturesPricing(),company:'',hypothesis:'',valuation_date:'',currency:'USD',units:'millions',shares:'',current_price:'',cash:'0',debt:'0',preferred:'0',minority:'0',nonoperating:'0',dcf_enabled:true,comps_enabled:false,tax_benefit:false,terminal_method:'growth',cases:['Bear','Base','Bull'].map(name=>({name,enabled:name==='Base',wacc:'',growth:'',exit_multiple:'',years:Array.from({length:5},blankYear)})),period:'',revenue:'',ebitda:'',net_income:'',peers:Array.from({length:3},blankPeer)});
export function validAnalytics(a){
  if(!a||![1,2,3].includes(a.version)||!['USD','CAD','EUR','GBP'].includes(a.currency)||!['units','thousands','millions','billions'].includes(a.units)||!['growth','multiple','both'].includes(a.terminal_method))return false;
  if(a.version>=2&&(!(a.version===2?['equity','option','futures']:['equity','option','futures','bond']).includes(a.tool)||!validDerivative(a.option_pricing,'option')||!validDerivative(a.futures_pricing,'futures')))return false;
  if(a.version===3&&!validBond(a.bond_pricing))return false;
  const strings=['company','valuation_date','shares','current_price','cash','debt','preferred','minority','nonoperating','period','revenue','ebitda','net_income'];
  const text=(v,n=100)=>typeof v==='string'&&v.length<=n;
  return strings.every(k=>text(a[k]))&&text(a.hypothesis,3000)&&['dcf_enabled','comps_enabled','tax_benefit'].every(k=>typeof a[k]==='boolean')&&Array.isArray(a.cases)&&a.cases.length===3&&['Bear','Base','Bull'].every(name=>a.cases.filter(c=>c.name===name).length===1)&&a.cases.every(c=>typeof c.enabled==='boolean'&&['wacc','growth','exit_multiple'].every(k=>text(c[k]))&&Array.isArray(c.years)&&c.years.length>=1&&c.years.length<=10&&c.years.every(y=>yearFields.every(k=>text(y[k]))))&&Array.isArray(a.peers)&&a.peers.length>=1&&a.peers.length<=30&&a.peers.every(p=>peerFields.every(k=>text(p[k],k==='name'?80:100)));
}
// Keep numerical input as text so Decimal on the server receives exactly what was entered.
const value=s=>s===''?null:s;
export function analyticsPayload(a){
  return {...Object.fromEntries(['company','hypothesis','valuation_date','currency','units','tax_benefit','terminal_method'].map(k=>[k,a[k]])),...Object.fromEntries(['shares','current_price','cash','debt','preferred','minority','nonoperating'].map(k=>[k,value(a[k])])),
    cases:a.dcf_enabled?a.cases.filter(c=>c.enabled).map(c=>({name:c.name,wacc:value(c.wacc),growth:a.terminal_method==='multiple'?null:value(c.growth),exit_multiple:a.terminal_method==='growth'?null:value(c.exit_multiple),years:c.years.map(y=>Object.fromEntries(yearFields.map(k=>[k,value(y[k])]))) })):[],
    comps:a.comps_enabled?{period:a.period,...Object.fromEntries(['revenue','ebitda','net_income'].map(k=>[k,value(a[k])])),peers:a.peers.filter(p=>peerFields.some(k=>p[k]!=='')).map(p=>({...p,...Object.fromEntries(peerFields.filter(k=>k!=='name').map(k=>[k,value(p[k])] ))}))}:null};
}

export const upgradeAnalytics=a=>a?{...emptyAnalytics(),...a,version:3,bond_pricing:{...emptyBond(),...a.bond_pricing},option_pricing:{...emptyOptionPricing(),...a.option_pricing},futures_pricing:{...emptyFuturesPricing(),...a.futures_pricing}}:emptyAnalytics();
