import {query,request} from "./api.js";import {drawLine} from "./chart.js";import {drawPrice,drawReplayMarkers} from "./price-chart.js?v=5";import {analysisSummary} from "./overlays.js";import {assertAnchor} from "./anchor-guard.js";import {money,compact,showToast,debounce,escapeHtml} from "./util.js";
import {initPipeline} from './agent-pipeline.js?v=5';
import {replayRows} from './replay-data.js';
import {executionOverlay,outcomeLabel} from './execution-overlay.js?v=1';
const state={symbol:localStorage.getItem("marketlab.symbol")||"0050.TW",interval:"1d",range:"5y",anchor:"",rows:[],analysis:null,toggles:{harmonics:true,zones:true,zigzag:false,rsi:true,macd:true},searchIndex:0};
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
async function load(){
 const version=Symbol();state.loadVersion=version;clearTimeout(state.replayTimer);state.replaying=false;state.loading=true;state.anchorRows=[];state.executionView=null;$('#batchTradeOverlay').classList.add('hidden');
 pipeline.contextChanged();$('#chartLoading').classList.remove('hidden');$('#chartLoading').textContent='正在載入行情與分析…';
 try{
  const params={symbol:state.symbol,interval:state.interval,range:state.range,anchor:state.anchor};
  const[candles,analysis,quote,profile]=await Promise.all([query('/api/candles',params),query('/api/analysis',params),state.anchor?Promise.resolve(null):query('/api/quote',{symbol:state.symbol}).catch(()=>null),query('/api/profile',{symbol:state.symbol}).catch(()=>null)]);
  if(state.loadVersion!==version)return;
  state.rows=assertAnchor(candles.candles,state.anchor);state.analysis=analysis;state.anchorRows=state.rows;
  $('#activeSymbol').textContent=state.symbol;$('#chartSymbol').textContent=state.symbol;$('#companyName').textContent=`${profile?.name||state.symbol} · ${state.interval}`;$('#newsName').value=profile?.name||'';
  const last=state.rows.at(-1),previous=state.rows.at(-2);if(!last)throw new Error('此錨點沒有可用行情');
  $('#ohlcLine').textContent=`開 ${money(last.open)}　高 ${money(last.high)}　低 ${money(last.low)}　收 ${money(last.close)}　量 ${compact(last.volume)}`;
  $('#lastPrice').textContent=money(quote?.price??last.close);
  const change=quote?.changePct??(previous?(last.close/previous.close-1)*100:null);
  $('#priceChange').textContent=change==null?'—':`${change>=0?'+':''}${change.toFixed(2)}%`;$('#priceChange').className=change>=0?'positive':'negative';
  $('#analysisCards').innerHTML=analysisSummary(analysis);const ind=analysis.indicators.at(-1);$('#rsiValue').textContent=ind?.rsi?.toFixed(1)??'—';$('#macdValue').textContent=ind?`MACD ${ind.macd.toFixed(2)}　訊號 ${ind.signal.toFixed(2)}`:'—';
  $('#dataStatus').textContent=`已連線　資料來源：Yahoo Finance · ${candles.policy.count} 根${state.anchor?' · 錨點後資料已隔離':''}`;
  render();state.loading=false;state.dataKey=`${state.symbol}:${state.interval}:${state.anchor}`;pipeline.contextChanged();$('#chartLoading').classList.add('hidden');
 }catch(error){if(state.loadVersion!==version)return;state.loading=false;state.dataKey=null;pipeline.contextChanged();$('#chartLoading').textContent=error.message;$('#dataStatus').textContent='資料連線失敗';showToast(error.message)}
}
function render(){drawPrice($("#priceChart"),state.rows,state.analysis,state.toggles,state.executionView);drawLine($("#rsiChart"),state.analysis?.indicators,"rsi","#b39bd9",[0,100]);drawLine($("#macdChart"),state.analysis?.indicators,"macd","#3474ff")}
function syncExecution(session,batch){
 if(state.loading||state.dataKey!==`${session.symbol}:${session.interval}:${session.anchor}`)return;
 const view=executionOverlay(session,batch,state.anchorRows.at(-1)?.time),host=$('#batchTradeOverlay');state.executionView=view;
 state.rows=view?.replay?.length?replayRows(state.anchorRows,view.replay,view.replay.length):state.anchorRows;
 if(!view){host.classList.add('hidden');render();return}
 const action={BUY:'買進',SELL:'賣出',HOLD:'觀望'}[view.action]||view.action;
 const result=outcomeLabel(view),signed=view.validation?.netReturnPct;
 const round=view.round?`第 ${view.round}/${view.totalRounds} 輪 · `:'';
 host.innerHTML=`<strong>${round}${escapeHtml(view.anchor)} · ${escapeHtml(action)}</strong>　信心 ${money(view.confidence)}%<br>${view.action==='HOLD'?'觀望，不設交易目標':`目標 ${money(view.target)}　停損 ${money(view.stop)}`}<small class="${signed>0?'trade-positive':signed<0?'trade-negative':''}">${escapeHtml(result)}</small>`;
 host.classList.remove('hidden');render();
 $('#dataStatus').textContent=`${view.batchId?'區間回測':'紙上驗證'} ${view.anchor} · ${result} · 分析僅使用錨點當日及以前資料`;
}
async function selectSession(session){state.symbol=session.symbol;state.interval=session.interval;state.anchor=session.anchor;$('#anchorDate').value=session.anchor;$$('[data-interval]').forEach(b=>b.classList.toggle('active',b.dataset.interval===session.interval));await load()}
function replay(report){
 if(!report.decision?.frozenAt||!report.replay?.length)return;
 if(state.loading||state.dataKey!==`${state.symbol}:${state.interval}:${state.anchor}`){showToast('錨點行情載入中，請稍候再回放');return}
 try{replayRows(state.anchorRows,report.replay,0)}catch(error){showToast(error.message);return}
 clearTimeout(state.replayTimer);const version=state.loadVersion;let count=0;state.replaying=true;
 function step(){if(version!==state.loadVersion)return;count++;state.rows=replayRows(state.anchorRows,report.replay,count);render();drawReplayMarkers($('#priceChart'),report,state.rows.at(-1).time);$('#dataStatus').textContent=`紙上驗證回放 ${count}/${report.replay.length} 根 · 原始決策已凍結，指標維持錨點資料`;if(count<report.replay.length)state.replayTimer=setTimeout(step,550)}
 step();
}
$$('[data-interval]').forEach(btn=>btn.onclick=()=>{state.interval=btn.dataset.interval;$$('[data-interval]').forEach(x=>x.classList.toggle("active",x===btn));load()});
$$('[data-toggle]').forEach(btn=>btn.onclick=()=>{const key=btn.dataset.toggle;state.toggles[key]=!state.toggles[key];btn.classList.toggle("active",state.toggles[key]);if(key==="rsi")$("#rsiPanel").classList.toggle("hidden",!state.toggles[key]);else if(key==="macd")$("#macdPanel").classList.toggle("hidden",!state.toggles[key]);applyPanelHeights();render()});
$$('[data-close]').forEach(btn=>btn.onclick=()=>document.querySelector(`[data-toggle="${btn.dataset.close}"]`).click());
$("#anchorDate").onchange=e=>{state.anchor=e.target.value;load()};$("#clearAnchor").onclick=()=>{$("#anchorDate").value="";state.anchor="";load()};
const dialog=$("#searchDialog"),input=$("#searchInput"),results=$("#searchResults");function openSearch(){dialog.showModal();input.value="";results.innerHTML="<p>輸入關鍵字搜尋美股、台股與加密資產</p>";setTimeout(()=>input.focus(),10)}$("#openSearch").onclick=openSearch;document.addEventListener("keydown",e=>{if(e.key==="/"&&!dialog.open){e.preventDefault();openSearch()}if(dialog.open&&["ArrowDown","ArrowUp"].includes(e.key)){e.preventDefault();const rows=$$(".search-result");if(!rows.length)return;state.searchIndex=(state.searchIndex+(e.key==="ArrowDown"?1:-1)+rows.length)%rows.length;rows.forEach((r,i)=>r.classList.toggle("active",i===state.searchIndex))}if(dialog.open&&e.key==="Enter"){const row=$$(".search-result")[state.searchIndex];if(row){e.preventDefault();row.click()}}});
input.oninput=debounce(async()=>{if(!input.value.trim())return;results.innerHTML="<p>搜尋中…</p>";try{const data=await query("/api/search",{q:input.value.trim()});state.searchIndex=0;results.innerHTML=data.results.length?data.results.map((r,i)=>`<button type="button" class="search-result ${i===0?"active":""}" data-symbol="${escapeHtml(r.symbol)}"><strong>${escapeHtml(r.symbol)}<br><span>${escapeHtml(r.name)}</span></strong><span>${escapeHtml(r.exchange)} · ${escapeHtml(r.type)}</span></button>`).join(""):"<p>找不到可交易標的</p>";$$('.search-result').forEach(row=>row.onclick=()=>{state.symbol=row.dataset.symbol;localStorage.setItem("marketlab.symbol",state.symbol);dialog.close();load()})}catch(e){results.innerHTML=`<p>${escapeHtml(e.message)}</p>`}},300);
$$('.weights input').forEach(input=>input.oninput=()=>input.parentElement.querySelector("output").textContent=`${Number(input.value).toFixed(1)}%`);$("#executionWeight").oninput=e=>e.target.parentElement.querySelector("output").textContent=`技術 ${e.target.value}% / 新聞 ${100-e.target.value}%`;$("#confidence").oninput=e=>e.target.parentElement.querySelector("output").textContent=`${e.target.value}%`;
[["#harmonicMaxAge"," 根"],["#harmonicHalfLife"," 根"],["#macdPositionLookback"," 根"],["#positionWeight","%"]].forEach(([id,unit])=>{const input=$(id);if(!input)return;input.oninput=()=>input.parentElement.querySelector("output").textContent=`${input.value}${unit}`;input.dispatchEvent(new Event("input"))});
// Indicator panel heights: seeded from the stylesheet, then pinned once the user drags one.
// The inline track list is rebuilt from the VISIBLE panels, so hiding RSI no longer leaves the
// footer stretched into an indicator-sized row.
const chartColumn=document.querySelector(".chart-column");
const PANEL_KEYS=["rsi","macd"],PANEL_MIN=90,PANEL_MAX=360,PANEL_DEFAULT=160,CHART_MIN=240,FOOTER_HEIGHT=27;
const panelHeights={rsi:PANEL_DEFAULT,macd:PANEL_DEFAULT};
const panelVisible=key=>!$(`#${key}Panel`).classList.contains("hidden");
function panelCeiling(key){
  const partner=key==="rsi"?"macd":"rsi",used=panelVisible(partner)?panelHeights[partner]:0;
  return Math.max(PANEL_MIN,Math.min(PANEL_MAX,chartColumn.clientHeight-FOOTER_HEIGHT-CHART_MIN-used));
}
function applyPanelHeights(){
  PANEL_KEYS.forEach(key=>{panelHeights[key]=Math.round(Math.max(PANEL_MIN,Math.min(panelCeiling(key),panelHeights[key])))});
  const rows=["minmax(0,1fr)",...PANEL_KEYS.filter(panelVisible).map(key=>`${panelHeights[key]}px`),`${FOOTER_HEIGHT}px`];
  chartColumn.style.gridTemplateRows=rows.join(" ");
}
function savePanelHeights(){try{localStorage.setItem("marketlab.panelHeights",JSON.stringify(panelHeights))}catch{}}
function resizePanel(key,height){panelHeights[key]=height;applyPanelHeights();render()}
function initPanelResize(){
  if(!chartColumn)return;
  let saved={};try{saved=JSON.parse(localStorage.getItem("marketlab.panelHeights")||"{}")}catch{}
  PANEL_KEYS.forEach(key=>{panelHeights[key]=Number(saved[key])||Math.round($(`#${key}Panel`).getBoundingClientRect().height)||PANEL_DEFAULT});
  applyPanelHeights();  // load() renders straight after, so no redraw is needed here.
  $$(".panel-resizer").forEach(handle=>{
    const key=handle.dataset.resize;let lastPress=0;
    handle.addEventListener("pointerdown",event=>{
      // preventDefault() on pointerdown can swallow dblclick, so detect the double press here.
      const doublePress=event.timeStamp-lastPress<350;lastPress=event.timeStamp;
      if(doublePress){event.preventDefault();resizePanel(key,PANEL_DEFAULT);savePanelHeights();return}
      event.preventDefault();handle.setPointerCapture(event.pointerId);
      handle.classList.add("dragging");chartColumn.classList.add("resizing");
      const startY=event.clientY,startHeight=panelHeights[key];
      const move=e=>resizePanel(key,startHeight-(e.clientY-startY));
      const finish=()=>{
        handle.classList.remove("dragging");chartColumn.classList.remove("resizing");savePanelHeights();render();
        handle.removeEventListener("pointermove",move);handle.removeEventListener("pointerup",finish);handle.removeEventListener("pointercancel",finish);
      };
      handle.addEventListener("pointermove",move);handle.addEventListener("pointerup",finish);handle.addEventListener("pointercancel",finish);
    });
    handle.addEventListener("keydown",event=>{
      const step={ArrowUp:12,ArrowDown:-12,PageUp:48,PageDown:-48}[event.key];
      if(step===undefined&&event.key!=="Home")return;
      event.preventDefault();
      resizePanel(key,event.key==="Home"?PANEL_DEFAULT:panelHeights[key]+step);savePanelHeights();
    });
  });
}
const pipeline=initPipeline({getContext:()=>({symbol:state.symbol,interval:state.interval,anchor:state.anchor,chartReady:!state.loading&&state.dataKey===`${state.symbol}:${state.interval}:${state.anchor}`}),selectSession,replay,syncSession:syncExecution});
async function loadWatchlist(){try{const data=await request("/api/watchlist");localStorage.setItem("marketlab.watchlist",JSON.stringify(data.items.map(x=>x.symbol)));renderWatch(data.items.map(x=>x.symbol))}catch{renderWatch(JSON.parse(localStorage.getItem("marketlab.watchlist")||"[]"))}}function renderWatch(items){$("#watchlistItems").innerHTML=items.length?items.map(s=>`<button class="analysis-chip watch-symbol" data-symbol="${s}">${s}</button>`).join(""):"尚無自選標的";$$('.watch-symbol').forEach(b=>b.onclick=()=>{state.symbol=b.dataset.symbol;load()})}$("#addWatchlist").onclick=async()=>{try{await request("/api/watchlist",{method:"POST",body:JSON.stringify({symbol:state.symbol})})}catch{const list=JSON.parse(localStorage.getItem("marketlab.watchlist")||"[]");if(!list.includes(state.symbol))list.push(state.symbol);localStorage.setItem("marketlab.watchlist",JSON.stringify(list))}loadWatchlist()};
$("#toggleSidebar").onclick=()=>$("#agentSidebar").classList.toggle("open");document.querySelector(".topbar").onclick=e=>{if(innerWidth<=900&&e.target===e.currentTarget)$("#agentSidebar").classList.toggle("open")};addEventListener("resize",debounce(()=>{applyPanelHeights();render()},100));$("#clearDrawings").onclick=()=>showToast("手動畫線已清除");loadWatchlist();initPanelResize();load().then(()=>pipeline.restore());
