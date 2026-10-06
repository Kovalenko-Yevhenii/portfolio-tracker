export async function api(path, body, signal) {
  let response;
  try {
    response = await fetch('/api' + path, {method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? {} : {'Content-Type': 'application/json'},
      body: body === undefined ? undefined : JSON.stringify(body), signal});
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('Cannot reach the tracker. Check that it is running, then retry.');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || 'The request failed. Please retry.');
  return data;
}
export const num = value => value === '' || value === null || value === undefined ? null : Number(value);
export const finite = value => typeof value === 'number' && Number.isFinite(value);
export const decimal = (value, digits=2) => finite(value) ? value.toLocaleString('en-US', {maximumFractionDigits:digits,minimumFractionDigits:digits}) : '—';
export const money = value => finite(value) ? value.toLocaleString('en-US', {style:'currency',currency:'USD',maximumFractionDigits:2}) : '—';
export const percent = value => finite(value) ? decimal(value*100) + '%' : '—';
export const date = value => value ? value.slice(0,10) : 'Unavailable';
export const rows = frame => frame ? frame.data.map((values,i)=>Object.fromEntries([['label',frame.index[i]], ...frame.columns.map((key,j)=>[key,values[j]])])) : [];
export function download(file) {
  const url = URL.createObjectURL(new Blob([file.content], {type:file.mime + ';charset=utf-8'}));
  const anchor = document.createElement('a'); anchor.href=url; anchor.download=file.name;
  document.body.appendChild(anchor); anchor.click(); anchor.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
