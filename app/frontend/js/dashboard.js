import {query,request} from './api.js';
import {showToast,escapeHtml as esc,money} from './util.js';
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const post=(url,body)=>request(url,{method:'POST',body:JSON.stringify(body)});
let currentScope=localStorage.getItem('marketlab.dashboardScope')||'',curve=[],strategyData,detailTimer;
const names={technical:'技術面 Agent 判斷規則',news:'新聞面 Agent 判斷規則',execution:'執行 Agent 決策規則',adaptive:'自適應 Agent 採用規則'};
const labels={weights:'權重',harmonics:'諧波',supportResistance:'支撐壓力',macd:'MACD',rsi:'RSI',macdMode:'MACD 模式',macdFast:'MACD 快線',macdSlow:'MACD 慢線',macdSignal:'訊號週期',macdLookback:'回看根數',slopeWeight:'斜率權重',positionWeight:'位置權重',rsiMode:'RSI 模式',rsiPeriod:'RSI 週期',rsiSensitivity:'RSI 敏感度',harmonicMinScore:'最低諧波評分',formingDiscount:'形成中折減',harmonicHalfLife:'諧波半衰期',srMode:'支撐壓力模式',srDistanceScale:'距離尺度',lookbackDays:'新聞回看天數',rounds:'搜尋輪數',stockWeight:'標的新聞權重',minRelevance:'最低相關度',inferenceBias:'新聞推論模式',technicalWeight:'技術權重',minConfidence:'最低信心',maxHoldingBars:'最長持有根數',holdThresholdPct:'HOLD 波動門檻 %',minShadowSessions:'最少影子樣本',minImprovementPct:'最低改善百分點',faithfulnessThreshold:'忠實度門檻'};
Object.assign(labels,{macdPositionLookback:'波形位置回看根數',macdLookback:'動能斜率回看根數',slopeWeight:'波形模式斜率占比',positionWeight:'高低位追價折減'});
const badge=value=>'<span class="badge '+esc(value||'')+'">'+esc(value||'—')+'</span>';
const json=value=>'<pre>'+esc(JSON.stringify(value,null,2))+'</pre>';
const notice=message=>{$('#dbNotice').textContent=message;$('#dbNotice').classList.toggle('hidden',!message)};


$$('[data-tab]').forEach(button=>button.onclick=()=>{$$('[data-tab]').forEach(x=>x.classList.toggle('active',x===button));$$('.tab').forEach(x=>x.classList.toggle('active',x.id===button.dataset.tab));loadTab(button.dataset.tab)});
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
async function showSession(id){
 clearTimeout(detailTimer);const s=await request('/api/flow/sessions/'+id),dialog=$('#sessionDetail');
 $('#detailTitle').textContent=s.symbol+' · '+s.anchor+' · '+s.status;
 $('#detailContent').innerHTML='<p>Session '+esc(s.id)+' · 前一輪 '+esc(s.previousSessionId||'無')+'</p>'+(s.error?'<p class="negative">'+esc(s.error)+'</p>':'')+
 Object.entries(s.runs).map(([agent,runs])=>'<h3>'+names[agent]+'</h3>'+(runs.length?runs.map(run=>'<details><summary>'+esc(run.role)+' · '+esc(run.status)+' · '+esc(run.strategyVersionId||'')+'</summary>'+(run.error?'<p>'+esc(run.error)+'</p>':'')+'<h4>輸入參數</h4>'+json(run.params)+'<h4>報告</h4>'+json(run.report||run.decision)+'</details>').join(''):'等待執行')).join('')+
 '<details><summary>新聞品質評審</summary>'+json(s.newsEvaluations)+'</details><details><summary>版本與差異</summary>'+json(s.relatedVersions)+'</details><details><summary>事件時間軸</summary>'+json(s.events)+'</details>';
 if(!dialog.open)dialog.showModal();
 $('#openWorkbench').onclick=()=>{localStorage.removeItem('marketlab.lastBatch');localStorage.setItem('marketlab.lastSession',id);location.href='/'};
 if(!['completed','failed'].includes(s.status)&&dialog.open)detailTimer=setTimeout(()=>showSession(id).catch(e=>notice(e.message)),2000);
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
function loadTab(tab){notice('');({overview,sessions,strategies,versions,audit}[tab]||overview)().catch(e=>notice(e.message))}
$('#sessionForm').onsubmit=async event=>{
 event.preventDefault();const button=event.currentTarget.querySelector('button');button.disabled=true;
 try{const body=Object.fromEntries(new FormData(event.currentTarget));body.autoRun=true;const row=await post('/api/flow/sessions',body);showToast('Session '+row.id.slice(0,8)+' 已開始');await config();await overview();await showSession(row.id)}catch(e){showToast(e.message)}finally{button.disabled=false}
};
addEventListener('resize',drawCurve);config().then(overview).catch(e=>notice(e.message));
