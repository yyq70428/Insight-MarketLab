export const money = value => value == null ? "—" : new Intl.NumberFormat("zh-TW", {maximumFractionDigits:2}).format(value);
export const compact = value => value == null ? "—" : new Intl.NumberFormat("zh-TW", {notation:"compact", maximumFractionDigits:1}).format(value);
export function showToast(message) { const el=document.querySelector("#toast"); el.textContent=message; el.classList.add("show"); clearTimeout(showToast.timer); showToast.timer=setTimeout(()=>el.classList.remove("show"),2800); }
export function setStatus(id, value, label) { const el=document.querySelector(id); el.className=`status ${value}`; el.textContent=label || ({waiting:"待命",running:"執行中",completed:"完成",failed:"失敗"}[value]); }
export function debounce(fn, wait=280){let timer;return(...args)=>{clearTimeout(timer);timer=setTimeout(()=>fn(...args),wait)}}
export function escapeHtml(value=""){const el=document.createElement("span");el.textContent=String(value);return el.innerHTML.replaceAll('"','&quot;').replaceAll("'",'&#39;')}
