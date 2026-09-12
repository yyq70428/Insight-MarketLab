export async function request(path, options = {}) {
  const response = await fetch(path, {headers:{"Content-Type":"application/json", ...(options.headers||{})}, ...options});
  let body = null;
  try { body = await response.json(); } catch { body = {}; }
  if (!response.ok) throw new Error(Array.isArray(body.detail)?body.detail.map(item=>`${(item.loc||[]).join('.')}：${item.msg}`).join('；'):body.detail || `請求失敗 (${response.status})`);
  return body;
}
export const query = (path, params={}) => request(`${path}?${new URLSearchParams(Object.entries(params).filter(([,v])=>v!==""&&v!=null))}`);
