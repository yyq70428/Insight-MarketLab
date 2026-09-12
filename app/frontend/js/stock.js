import {query} from "./api.js";
import {drawPrice} from "./price-chart.js";
import {money,escapeHtml} from "./util.js";

const $=selector=>document.querySelector(selector);
let symbol=localStorage.getItem("marketlab.symbol")||"0050.TW";
$("#stockSymbol").value=symbol;

async function load(){
  symbol=$("#stockSymbol").value.trim(); localStorage.setItem("marketlab.symbol",symbol);
  try{
    const [candles,analysis,profile,quote,news,tw]=await Promise.all([
      query("/api/candles",{symbol,interval:"1d",range:"2y"}), query("/api/analysis",{symbol,interval:"1d",range:"2y"}),
      query("/api/profile",{symbol}), query("/api/quote",{symbol}), query("/api/news",{symbol}).catch(()=>({items:[]})), query("/api/news-tw",{symbol,page:1}).catch(()=>({items:[]}))]);
    $("#stockName").textContent=profile.name; $("#exchange").textContent=profile.exchange||symbol;
    $("#stockMeta").textContent=`${profile.sector} · ${profile.industry}`; $("#stockPrice").textContent=money(quote.price);
    $("#stockChange").textContent=`${quote.changePct>=0?"+":""}${quote.changePct}%`; $("#stockChange").className=quote.changePct>=0?"bullish":"bearish";
    $("#profileData").innerHTML=`<div><dt>市場</dt><dd>${escapeHtml(profile.exchange||"—")}</dd></div><div><dt>幣別</dt><dd>${escapeHtml(profile.currency||"—")}</dd></div><div><dt>產業</dt><dd>${escapeHtml(profile.industry)}</dd></div><div><dt>市值</dt><dd>${profile.marketCap?new Intl.NumberFormat("zh-TW",{notation:"compact"}).format(profile.marketCap):"—"}</dd></div>`;
    $("#profileSummary").textContent=profile.summary; renderNews("#globalNews",news.items); renderNews("#twNews",tw.items);
    drawPrice($("#stockChart"),candles.candles,analysis,{harmonics:true,zones:true,zigzag:true});
  }catch(error){$("#stockName").textContent=error.message}
}
function renderNews(target,items){
  $(target).innerHTML=items?.length?items.map(item=>`<a class="news-item" href="${escapeHtml(item.url||"#")}" target="_blank" rel="noopener"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.publisher||"")} · ${escapeHtml(item.publishedAt||"")}</span></a>`).join(""):"<p class=muted>目前沒有可驗證新聞</p>";
}
$("#stockSearch").onsubmit=event=>{event.preventDefault();load()}; load();
