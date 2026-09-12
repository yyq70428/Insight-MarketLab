import {query,request} from './api.js';
import {showToast,escapeHtml as esc,money} from './util.js';
import {batchNodes,batchStatusLabel} from './batch-timeline.js?v=1';
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const post=(url,body)=>request(url,{method:'POST',body:JSON.stringify(body)});
let currentScope=localStorage.getItem('marketlab.dashboardScope')||'',curve=[],strategyData,detailTimer,batchPollTimer,batchRows=[],batchDrafts=[];
const names={technical:'第一層 · 技術 Agent',news:'第一層 · 新聞 Agent',execution:'第二層 · 執行 Agent',adaptive:'第三層 · 自適應 Agent'};
const labels={weights:'權重',harmonics:'諧波',supportResistance:'支撐壓力',macd:'MACD',rsi:'RSI',macdMode:'MACD 模式',macdFast:'MACD 快線',macdSlow:'MACD 慢線',macdSignal:'訊號週期',macdLookback:'回看根數',slopeWeight:'斜率權重',positionWeight:'位置權重',rsiMode:'RSI 模式',rsiPeriod:'RSI 週期',rsiSensitivity:'RSI 敏感度',harmonicMinScore:'最低諧波評分',formingDiscount:'形成中折減',harmonicHalfLife:'諧波半衰期',srMode:'支撐壓力模式',srDistanceScale:'距離尺度',lookbackDays:'新聞回看天數',rounds:'搜尋輪數',stockWeight:'標的新聞權重',minRelevance:'最低相關度',inferenceBias:'新聞推論模式',technicalWeight:'技術權重',minConfidence:'最低信心',maxHoldingBars:'最長持有根數',holdThresholdPct:'HOLD 波動門檻 %',minShadowSessions:'最少影子樣本',minImprovementPct:'最低改善百分點',faithfulnessThreshold:'忠實度門檻'};
Object.assign(labels,{macdPositionLookback:'波形位置回看根數',macdLookback:'動能斜率回看根數',slopeWeight:'波形模式斜率占比',positionWeight:'高低位追價折減'});
const badge=value=>'<span class="badge '+esc(value||'')+'">'+esc(value||'—')+'</span>';
const json=value=>'<pre>'+esc(JSON.stringify(value,null,2))+'</pre>';
const notice=message=>{$('#dbNotice').textContent=message;$('#dbNotice').classList.toggle('hidden',!message)};


$$('[data-tab]').forEach(button=>button.onclick=()=>{clearTimeout(batchPollTimer);$$('[data-tab]').forEach(x=>x.classList.toggle('active',x===button));$$('.tab').forEach(x=>x.classList.toggle('active',x.id===button.dataset.tab));loadTab(button.dataset.tab)});
$('#scope').onchange=e=>{currentScope=e.target.value;localStorage.setItem('marketlab.dashboardScope',currentScope);loadTab($('.dashboard-tabs .active').dataset.tab)};
async function config(){
 const data=await request('/api/flow/config');$('#ragas').textContent=data.ragasEnabled?'啟用':'未啟用';$('#engineName').textContent=data.engine;$('#modelName').textContent='模型 '+data.model;
 if(!data.databaseAvailable)throw new Error('MongoDB 無法連線；Flow 與策略版本不會降級成瀏覽器暫存。請檢查資料庫服務。');
 const result=await request('/api/flow/scopes'),scopes=[...new Set(['0050.TW:1d',...result.scopes])];
 $('#scope').innerHTML='<option value="">全部</option>'+scopes.map(s=>'<option value="'+esc(s)+'">'+esc(s)+'</option>').join('');
 if(!scopes.includes(currentScope))currentScope='';$('#scope').value=currentScope;
}
async function overview(){
 const data=await query('/api/flow/overview',{scope:currentScope});notice('');
 $('#totalSessions').textContent=data.total;$('#completedSessions').textContent='完成 '+data.completed+'　待驗證 '+data.waitingValidation+'　失敗 '+data.failed;
 $('#onlineRounds').textContent=data.onlineRounds;$('#pendingCandidates').textContent=data.pendingCandidates;
 for(const [id,key] of [['firstReturn','firstHalf'],['secondReturn','secondHalf'],['returnDiff','difference']])$('#'+id).textContent=data.returnSummary[key]==null?'—':money(data.returnSummary[key])+'%';
 curve=data.curve;drawCurve();
 $('#recentEvents').innerHTML=data.recentEvents.length?data.recentEvents.map(e=>'<div class="event-row">'+badge(e.agent||'策略')+' '+esc(e.action)+' '+esc(e.createdAt)+'</div>').join(''):'<div class="event-row">尚無策略事件</div>';
 $('#scopeRows').innerHTML='<tr><td>'+esc(currentScope||'全部')+'</td><td>'+data.total+'</td><td>依策略頁查閱</td><td>'+data.pendingCandidates+'</td></tr>';
}
function drawCurve(){
 const canvas=$('#returnChart'),box=canvas.getBoundingClientRect(),ratio=devicePixelRatio||1;if(!box.width)return;
 canvas.width=box.width*ratio;canvas.height=box.height*ratio;const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);ctx.strokeStyle='#303849';ctx.fillStyle='#8c97aa';ctx.font='12px system-ui';
 const values=curve.map(x=>x.value),min=Math.min(0,...values),max=Math.max(0,...values),span=max-min||1;
 for(let i=0;i<5;i++){const y=25+i*(box.height-60)/4;ctx.beginPath();ctx.moveTo(60,y);ctx.lineTo(box.width-30,y);ctx.stroke();if(curve.length)ctx.fillText((max-i*span/4).toFixed(2)+'%',5,y+4)}
 if(!curve.length){ctx.fillText('尚無完整的紙上驗證資料',70,65);return}
 ctx.strokeStyle='#316cff';ctx.lineWidth=2;ctx.beginPath();curve.forEach((r,i)=>{const x=60+i*(box.width-90)/Math.max(1,curve.length-1),y=25+(max-r.value)/span*(box.height-60);i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();
 ctx.fillText(curve[0].anchor,60,box.height-10);ctx.fillText(curve.at(-1).anchor,Math.max(60,box.width-110),box.height-10);
}
async function sessions(){
 const data=await query('/api/flow/sessions',{scope:currentScope,limit:100});$('#sessionCount').textContent='('+data.sessions.length+' 輪)';
 $('#sessionsRows').innerHTML=data.sessions.length?data.sessions.map(s=>'<tr><td><button class="session-link" data-session="'+esc(s.id)+'">'+esc(s.anchor)+'</button></td><td>'+esc(s.symbol)+' '+esc(s.interval)+'</td><td>'+badge(s.status)+(s.status==='completed'&&!s.labelComplete?'<br>等待行情':'')+'</td><td>'+money(s.technicalBullish)+'</td><td>'+money(s.newsBullish)+'</td><td>'+(s.articleCount??'—')+'</td><td>'+money(s.faithfulness)+'</td><td>'+esc(s.decision?.action||'—')+'</td><td>'+(s.labelComplete?money(s.outcome?.netReturnPct):'—')+'</td><td>'+(s.paramChanges??0)+'</td><td>'+esc(s.adaptiveConclusion||s.error||'尚無結論')+'</td></tr>').join(''):'<tr><td colspan="11">尚無 Session</td></tr>';
 $$('[data-session]').forEach(button=>button.onclick=()=>showSession(button.dataset.session).catch(e=>showToast(e.message)));
}
const today=()=>new Date().toISOString().slice(0,10);
const newBatchDraft=()=>({id:globalThis.crypto?.randomUUID?.()||String(Date.now()),symbol:(currentScope.split(':')[0]||'0050.TW'),startDate:'',endDate:'',maxHoldingDays:5,holdThresholdPct:2});
function batchDraftHTML(draft){
 return `<form class="batch-lane batch-lane-draft" data-draft="${esc(draft.id)}"><div class="batch-lane-head"><div class="batch-settings">
  <label>標的<input name="symbol" value="${esc(draft.symbol)}" maxlength="30" placeholder="0050.TW" required></label>
  <label>開始日<input name="startDate" type="date" value="${esc(draft.startDate)}" max="${today()}" required></label>
  <label>結束日<input name="endDate" type="date" value="${esc(draft.endDate)}" max="${today()}" required></label>
  <label>最長持有<select name="maxHoldingDays">${[1,2,3,4,5,6,7].map(value=>`<option ${value===Number(draft.maxHoldingDays)?'selected':''} value="${value}">${value} 日</option>`).join('')}</select></label>
  <label>HOLD 門檻<input name="holdThresholdPct" type="number" min="0.1" max="20" step="0.1" value="${esc(draft.holdThresholdPct)}" required></label>
  </div><div class="batch-lane-actions"><span class="badge draft">尚未執行</span><button type="button" class="secondary" data-remove-draft="${esc(draft.id)}">移除</button><button class="primary">執行</button></div></div>
  <div class="timeline timeline-empty"><span>設定完成後按「執行」，系統會依實際交易日建立節點。</span></div></form>`;
}
function batchLaneHTML(batch){
 const nodes=batchNodes(batch),active=['queued','running'].includes(batch.status),status=batchStatusLabel(batch.status);
 const statusClass=batch.status==='completed'?'completed':batch.status==='failed'||batch.status==='interrupted'?'failed':batch.status==='waiting_validation'?'waiting':'running';
 return `<article class="batch-lane" data-batch="${esc(batch.id)}"><div class="batch-lane-head"><div><h3>${esc(batch.symbol)} <span>${esc(batch.startDate)} → ${esc(batch.endDate)}</span></h3>
  <p>日線 · 最長持有 ${Number(batch.maxHoldingDays)} 日 · HOLD 門檻 ${money(batch.holdThresholdPct)}% · ${Number(batch.completedRounds||0)}/${Number(batch.totalRounds||0)} 輪</p></div>
  <div class="batch-lane-actions"><span class="badge ${statusClass}">${esc(status)}</span>${batch.status==='waiting_validation'?`<button type="button" class="secondary" data-refresh-batch="${esc(batch.id)}">更新驗證</button>`:''}</div></div>
  <div class="timeline-scroll"><div class="timeline" role="list" aria-label="${esc(batch.symbol)} 區間回測交易日">
  ${nodes.map(node=>node.sessionId?`<a role="listitem" class="timeline-node ${esc(node.state)}" href="/prediction?session=${encodeURIComponent(node.sessionId)}" title="${esc(node.anchor+' · 開啟預測詳情')}"><i></i><strong>${esc(node.anchor.slice(5).replace('-','/'))}</strong><span>${esc(node.action)}${Number.isFinite(node.confidence)?' · '+money(node.confidence)+'%':''}</span><small>${esc(node.detail)}</small></a>`:`<button type="button" role="listitem" class="timeline-node ${esc(node.state)}" disabled title="${esc(node.anchor+' · '+node.detail)}"><i></i><strong>${esc(node.anchor.slice(5).replace('-','/'))}</strong><span>${esc(node.action)}${Number.isFinite(node.confidence)?' · '+money(node.confidence)+'%':''}</span><small>${esc(node.detail)}</small></button>`).join('')}
  </div></div><footer><span>買進 ${Number(batch.stats?.BUY||0)} · 賣出 ${Number(batch.stats?.SELL||0)} · 觀望 ${Number(batch.stats?.HOLD||0)}</span><span>已驗證 ${Number(batch.validatedRounds||0)} · 成功 ${Number(batch.successCount||0)} · 成功率 ${batch.successRate==null?'—':money(batch.successRate)+'%'}</span>${batch.error?`<span class="negative">${esc(batch.error)}</span>`:''}${active?'<span>資料自動更新中</span>':''}</footer></article>`;
}
function renderBatchBoard(){
 $('#batchLaneList').innerHTML=batchDrafts.map(batchDraftHTML).join('')+batchRows.map(batchLaneHTML).join('')||'<div class="batch-empty">尚無區間回測。按右上角「新增回測列」開始設定。</div>';
 $$('[data-draft]').forEach(form=>{
  form.oninput=()=>{const draft=batchDrafts.find(row=>row.id===form.dataset.draft);if(!draft)return;for(const [key,value] of new FormData(form))draft[key]=value};
  form.onsubmit=event=>submitBatchDraft(event,form.dataset.draft);
 });
 $$('[data-remove-draft]').forEach(button=>button.onclick=()=>{batchDrafts=batchDrafts.filter(row=>row.id!==button.dataset.removeDraft);renderBatchBoard()});
 $$('#batchLaneList [data-session]').forEach(button=>button.onclick=()=>showSession(button.dataset.session).catch(error=>showToast(error.message)));
 $$('[data-refresh-batch]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{await post(`/api/flow/batches/${button.dataset.refreshBatch}/refresh-validation`,{});await batches()}catch(error){showToast(error.message)}finally{button.disabled=false}});
}
async function submitBatchDraft(event,id){
 event.preventDefault();const form=event.currentTarget,button=form.querySelector('button.primary');button.disabled=true;
 try{
  const body=Object.fromEntries(new FormData(form));
  if(body.endDate<body.startDate)throw new Error('結束日期不可早於開始日期');
  body.maxHoldingDays=Number(body.maxHoldingDays);body.holdThresholdPct=Number(body.holdThresholdPct);body.params={};
  const row=await post('/api/flow/batches',body);batchDrafts=batchDrafts.filter(draft=>draft.id!==id);localStorage.setItem('marketlab.lastBatch',row.id);showToast(`${row.symbol} 區間回測已開始`);await batches();
 }catch(error){showToast(error.message);button.disabled=false}
}
async function batches(){
 clearTimeout(batchPollTimer);const data=await query('/api/flow/batches',{limit:100});batchRows=data.batches||[];renderBatchBoard();
 if(batchRows.some(batch=>['queued','running'].includes(batch.status))&&$('#batches').classList.contains('active'))batchPollTimer=setTimeout(()=>batches().catch(error=>notice(error.message)),1800);
}
$('#addBatchLane').onclick=()=>{batchDrafts.unshift(newBatchDraft());renderBatchBoard();$('#batchLaneList form:first-child input').focus()};
async function showSession(id){
 clearTimeout(detailTimer);const s=await request('/api/flow/sessions/'+id),dialog=$('#sessionDetail');
 const sessionStatus={first_layer:'第一層分析',execution:'第二層決策',adaptive:'第三層審核',completed:'完成',failed:'失敗'}[s.status]||s.status;
 $('#detailTitle').textContent=s.symbol+' · '+s.anchor+' · '+sessionStatus;
 $('#detailContent').innerHTML='<p>Session '+esc(s.id)+' · 前一輪 '+esc(s.previousSessionId||'無')+'</p>'+
 '<p><a class="primary" href="/prediction?session='+encodeURIComponent(id)+'" target="_blank" rel="noopener noreferrer">開啟預測流程視覺化</a></p>'+(s.error?'<p class="negative">'+esc(s.error)+'</p>':'')+
 Object.entries(s.runs).map(([agent,runs])=>'<h3>'+names[agent]+'</h3>'+agentOverview(agent,runs)+(runs.length?runs.map(run=>'<details><summary>'+esc(run.role==='champion'?'主報告':run.role.replace('shadow:','影子候選 · '))+' · '+esc({completed:'完成',running:'執行中',failed:'失敗'}[run.status]||run.status)+' · '+esc(run.strategyVersionId||'')+'</summary>'+(run.error?'<p>'+esc(run.error)+'</p>':'')+'<h4>輸入參數</h4>'+json(run.params)+'<h4>完整報告</h4>'+json(run.report||run.decision)+'</details>').join(''):'')).join('')+
 '<details><summary>新聞品質評審</summary>'+json(s.newsEvaluations)+'</details><details><summary>版本與差異</summary>'+json(s.relatedVersions)+'</details><details><summary>事件時間軸</summary>'+json(s.events)+'</details>';
 if(!dialog.open)dialog.showModal();
 $('#openWorkbench').onclick=()=>{localStorage.removeItem('marketlab.lastBatch');localStorage.setItem('marketlab.lastSession',id);location.href='/'};
 if(!['completed','failed'].includes(s.status)&&dialog.open)detailTimer=setTimeout(()=>showSession(id).catch(e=>notice(e.message)),2000);
}
function agentOverview(agent,runs){
 const run=runs.find(row=>row.role==='champion');if(!run)return '<p class="agent-overview waiting">尚未執行</p>';
 if(run.status==='running')return '<p class="agent-overview running">正在執行，完成後自動更新</p>';
 if(run.status==='failed')return '<p class="agent-overview negative">'+esc(run.error||'執行失敗')+'</p>';
 const report=run.report||{},decision=report.decision||run.decision||{};
 if(agent==='technical')return `<p class="agent-overview">看多 ${money(report.bullishPct)}% · 看空 ${money(report.bearishPct)}% · ${esc(report.recommendation||'完成')}</p>`;
 if(agent==='news')return `<p class="agent-overview">看多 ${money(report.bullishPct)}% · 看空 ${money(report.bearishPct)}% · 驗證 ${Number(report.sources?.length||0)} 篇 · ${esc(report.summary||'完成')}</p>`;
 if(agent==='execution')return `<p class="agent-overview">${esc(decision.action||'—')} · 信心 ${money(decision.confidence)}% · 目標 ${money(report.target)} · 停損 ${money(report.stop)} · ${report.validation?.complete?`淨報酬 ${Number(report.validation.netReturnPct)>0?'+':''}${money(report.validation.netReturnPct)}%`:'等待後續行情'}</p>`;
 return `<p class="agent-overview">${esc(report.recommendation||'審核完成')} · 候選 ${Number(report.candidates?.length||0)} · 影子評估 ${Number(report.evaluations?.length||0)}</p>`;
}
$('#sessionDetail').addEventListener('close',()=>clearTimeout(detailTimer));
function field(path,value,schema){
 const key=path.split('.').at(-1),attrs='data-param="'+esc(path)+'" data-type="'+esc(schema.type||'string')+'"';
 const control=schema.enum?'<select '+attrs+'>'+schema.enum.map(v=>'<option '+(v===value?'selected':'')+'>'+esc(v)+'</option>').join('')+'</select>':
 '<input '+attrs+' type="'+(typeof value==='number'?'number':'text')+'" value="'+esc(value)+'" '+(schema.minimum!=null?'min="'+schema.minimum+'"':'')+' '+(schema.maximum!=null?'max="'+schema.maximum+'"':'')+' step="'+(schema.type==='integer'?'1':'any')+'" required>';
 return '<label>'+esc(labels[key]||key)+control+'<small>'+(schema.enum?'限定列舉值':schema.minimum!=null?schema.minimum+' 至 '+schema.maximum:'依規格驗證')+'</small></label>';
}
async function strategies(){
 const scope=currentScope||'0050.TW:1d';$('#strategyScope').textContent='('+scope+')';strategyData=await query('/api/flow/strategies',{scope});
 $('#strategyForms').innerHTML=Object.entries(strategyData.params).map(([agent,params])=>{
  const model=strategyData.models[agent];return '<form class="strategy-card" data-agent="'+agent+'"><header><h2>'+names[agent]+'</h2><span>revision '+strategyData.revision+' · '+esc(strategyData.head.versions[agent].slice(0,8))+'</span></header><div class="parameter-grid">'+Object.entries(params).flatMap(([key,value])=>{
   const schema=model.properties[key];return typeof value==='object'?Object.entries(value).map(([sub,v])=>field(key+'.'+sub,v,model.$defs[schema.$ref.split('/').at(-1)].properties[sub])):field(key,value,schema);
  }).join('')+'</div><div class="strategy-actions"><input name="hypothesis" placeholder="這次修改的假設（至少 3 字）" minlength="3" maxlength="500" required><button class="primary">儲存為新版本</button></div></form>';
 }).join('');
 $$('[data-agent]').forEach(form=>form.onsubmit=async event=>{
  event.preventDefault();const button=form.querySelector('button');button.disabled=true;
  try{
   const params={};form.querySelectorAll('[data-param]').forEach(input=>{const keys=input.dataset.param.split('.');let target=params;for(const k of keys.slice(0,-1))target=target[k]??={};target[keys.at(-1)]=['number','integer'].includes(input.dataset.type)?Number(input.value):input.value});
   await post('/api/flow/strategies/'+form.dataset.agent,{scope:strategyData.scope,params,expectedRevision:strategyData.revision,hypothesis:form.elements.hypothesis.value});
   showToast('新版本已發布；已建立的輪次不會被改寫');await strategies();
  }catch(e){showToast(e.message);notice(e.message+'；請切換頁籤重新載入最新版本後再修改。')}finally{button.disabled=false}
 });
}
async function versions(){
 const scope=currentScope||'0050.TW:1d';$('#versionScope').textContent='('+scope+')';
 const [data,head]=await Promise.all([query('/api/flow/versions',{scope}),query('/api/flow/strategies',{scope})]);
 $('#versionsRows').innerHTML=data.versions.length?data.versions.map(v=>'<tr><td>'+esc(v.createdAt)+'<br><small>生效 '+esc(v.effectiveAt)+'</small></td><td>'+esc(v.agent)+'</td><td>'+badge(v.status)+(head.head.versions[v.agent]===v.id?' 目前指標':'')+'</td><td>'+esc(v.hypothesis)+'</td><td><details><summary>'+Object.keys(v.diff||{}).length+' 項差異</summary>'+json(v.diff)+'</details></td><td>'+esc(v.kind||'—')+'</td><td>'+(v.status==='active'?'<button class="secondary" data-rollback="'+v.id+'">回滾到此版本</button>':'不適用')+'</td></tr>').join(''):'<tr><td colspan="7">尚無版本</td></tr>';
 $$('[data-rollback]').forEach(button=>button.onclick=async()=>{
  if(!confirm('將此版本重新發布為新的正式版本？既有輪次與原版本都會保留。'))return;
  button.disabled=true;try{await post('/api/flow/versions/'+button.dataset.rollback+'/rollback',{expectedRevision:head.revision,hypothesis:'後台人工回滾'});showToast('回滾已建立新版本');await versions()}catch(e){showToast(e.message)}finally{button.disabled=false}
 });
}
async function audit(){const data=await query('/api/flow/events',{scope:currentScope});$('#auditRows').innerHTML=data.events.length?data.events.map(e=>'<tr><td>'+esc(e.createdAt)+'</td><td>'+esc(e.scope)+'</td><td>'+esc(e.agent)+'</td><td>'+esc(e.action)+'</td><td class="id-cell">'+esc(e.sessionId||'—')+'</td><td class="id-cell">'+esc(e.versionId||'—')+'</td></tr>').join(''):'<tr><td colspan="6">尚無事件</td></tr>'}
function loadTab(tab){notice('');({overview,sessions,batches,strategies,versions,audit}[tab]||overview)().catch(e=>notice(e.message))}
$('#sessionForm').onsubmit=async event=>{
 event.preventDefault();const button=event.currentTarget.querySelector('button');button.disabled=true;
 try{const body=Object.fromEntries(new FormData(event.currentTarget));body.autoRun=true;const row=await post('/api/flow/sessions',body);showToast('Session '+row.id.slice(0,8)+' 已開始');await config();await overview();await showSession(row.id)}catch(e){showToast(e.message)}finally{button.disabled=false}
};
addEventListener('resize',drawCurve);config().then(overview).catch(e=>notice(e.message));
