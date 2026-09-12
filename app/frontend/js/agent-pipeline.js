import {request} from './api.js';
import {escapeHtml as esc, money, showToast, setStatus} from './util.js';
import {technicalReportHTML} from './technical-report.js';

const $ = selector => document.querySelector(selector);
const post = (url, body = {}) => request(url, {method: 'POST', body: JSON.stringify(body)});
const stageNames = {first_layer:'技術／新聞分析',creating_session:'建立輪次',technical:'技術分析',news:'新聞分析',execution:'決策與驗證',adaptive:'自適應審核',waiting_data:'等待後續行情',completed:'完成'};
const statusIds = {technical:'#techStatus',news:'#newsStatus',execution:'#executionStatus',adaptive:'#adaptiveStatus'};

export function initPipeline({getContext, selectSession, replay}) {
  let current = null, batch = null, sessionTimer, batchTimer, creating, busy = false, creatingKey;
  let rendered = new Map();
  const key = value => `${value.symbol}:${value.interval}:${value.anchor}`;
  const error = err => showToast(err.message);

  function params() {
    const weights = Object.fromEntries(['harmonics','supportResistance','macd','rsi'].map((name, i) => [name, Number(document.querySelectorAll('.weights input')[i].value)]));
    return {technical:{weights},news:{lookbackDays:Number($('.news-fields input').value),rounds:parseInt($('.news-fields select').value)},
      execution:{technicalWeight:Number($('#executionWeight').value)/100,minConfidence:Number($('#confidence').value),
      maxHoldingBars:Number($('#maxHold').value),holdThresholdPct:Number($('#holdThreshold').value)}};
  }

  function validForm(batchMode = false) {
    const fields = batchMode ? ['#batchStart','#batchEnd','#holdThreshold'] : ['.news-fields input'];
    for (const selector of fields) {
      const field = $(selector);
      if (!field.value || !field.reportValidity()) throw new Error('請填入有效的日期與參數');
    }
    if (!batchMode && !getContext().anchor) throw new Error('請先選擇歷史錨點');
    if (!Object.values(params().technical.weights).some(value=>value>0)) throw new Error('技術權重不可全部為零');
  }

  async function ensureSession(fresh = false) {
    validForm();
    const context = {...getContext()}, identity = key(context);
    if (current && key(current) === identity && !fresh && current.status !== 'failed') return current;
    if (creating && creatingKey === identity) return creating;
    creatingKey = identity;
    creating = post('/api/flow/sessions', {...context, symbolName:$('#newsName').value, params:params()}).then(row => {
      if (key(getContext()) === identity) { current = row; rendered.clear(); localStorage.setItem('marketlab.lastSession',row.id); renderSession(row); }
      return row;
    }).finally(()=>{creating=null;creatingKey=null});
    return creating;
  }

  function executionHTML(report) {
    const d=report.decision, v=report.validation;
    return `<strong>${esc(d.action)}</strong> · 信心 ${money(d.confidence)}% · ${d.modelUsed?'模型決策':'證據不足，依規則觀望'}
      <p>${esc(d.technicalReason)}<br>${esc(d.newsReason)}</p>
      <p>${v.complete ? `驗證${v.success?'成功':'未成功'} · 淨報酬 ${money(v.netReturnPct)}%` : `等待後續行情 · ${v.bars}/${v.requiredBars} 根（不計入成功率）`}</p>
      <small>${esc(d.risk)}</small>`;
  }

  function renderSession(s) {
    if (key(s) !== key(getContext())) return;
    current=s;
    $('#flowHint').textContent = `${s.anchor} · ${s.status==='failed' ? s.error : s.status==='completed' ? s.labelComplete?'整輪完成':'分析完成，驗證等待行情':'Session '+s.id.slice(0,8)}`;
    for (const [agent, selector] of Object.entries(statusIds)) {
      const status=s.stageStatus[agent]||'waiting'; setStatus(selector,status);
      const run=s.runs?.[agent]?.find(run=>run.role==='champion');
      if (!run) continue;
      const stamp=`${run.id}:${run.status}:${run.report?.validation?.bars}`;
      if (rendered.get(agent)===stamp) continue;
      rendered.set(agent,stamp);
      const host=$({technical:'#techReport',news:'#newsReport',execution:'#executionReport',adaptive:'#adaptiveReport'}[agent]);
      if (run.status==='failed') {host.textContent=run.error;continue}
      if (run.status==='running') {host.textContent='執行中，完成後立即更新…';continue}
      const r=run.report;
      if (agent==='technical') host.innerHTML=technicalReportHTML(r);
      if (agent==='news') {
        if (!r.evidenceSufficient) setStatus(selector,'completed','證據不足');
        host.innerHTML=`<strong>${r.evidenceSufficient?`多 ${money(r.bullishPct)}%／空 ${money(r.bearishPct)}%`:'證據不足'}</strong>
          <p>${esc(r.summary)}</p><small>驗證 ${r.sources.length} 篇 · 擷取 ${r.fetchSeconds}s · 模型 ${r.modelSeconds}s</small>
          <details><summary>來源與限制</summary>${r.sources.map(source=>`<p><a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">${esc(source.title)}</a><br>${esc(source.type)} · ${esc(source.publishedAt)}</p>`).join('')}
          ${(r.limitations||[]).map(text=>`<p>${esc(text)}</p>`).join('')}排除 ${(r.excluded||[]).length} 筆</details>`;
      }
      if (agent==='execution') host.innerHTML=executionHTML(r);
      if (agent==='adaptive') host.innerHTML=`<p>${esc(r.recommendation)}</p>新候選 ${(r.candidates||[]).length} 個 · 影子審核 ${(r.evaluations||[]).length} 個`;
    }
    const ready=s.stageStatus.technical==='completed'&&s.stageStatus.news==='completed';
    $('#runExecution').disabled=!ready||s.stageStatus.execution==='running'||s.stageStatus.execution==='completed'||s.status==='failed';
    $('#runExecution').textContent=s.stageStatus.execution==='completed'?'決策已完成':ready?'執行決策並紙上驗證':'等待兩份報告完成';
    $('#refreshValidation').classList.toggle('hidden',s.status!=='completed'||s.labelComplete);
    $('#playValidation').classList.toggle('hidden',!(s.runs.execution?.find(r=>r.role==='champion')?.report?.replay?.length));
    $('#playValidation').disabled=!getContext().chartReady;
    $('#restoreAnchor').classList.toggle('hidden',!s.decision);
  }

  async function pollSession(id) {
    clearTimeout(sessionTimer);
    try {
      const s=await request(`/api/flow/sessions/${id}`);
      if (current?.id!==id) return;
      renderSession(s);
      if (!['completed','failed'].includes(s.status) && (busy || s.jobActive || Object.values(s.stageStatus).includes('running'))) sessionTimer=setTimeout(()=>pollSession(id),1200);
    } catch(err) {error(err)}
  }

  async function runStages(agents) {
    if(busy)return;busy=true;
    try {
      const fresh=agents.some(agent=>agent!=='execution'&&current?.stageStatus[agent]==='completed');
      const s=await ensureSession(fresh); current=s; pollSession(s.id);
      const outcomes=await Promise.allSettled(agents.map(agent=>post(`/api/flow/sessions/${s.id}/stages/${agent}`,agent==='execution'?{params:params().execution,autoAdaptive:true}:{})));
      const failed=outcomes.find(r=>r.status==='rejected');if(failed)throw failed.reason;
    }catch(err){error(err)}finally{busy=false;if(current)pollSession(current.id)}
  }
  $('#runTech').onclick=()=>runStages(['technical']);
  $('#runNews').onclick=()=>runStages(['news']);
  $('#runFirst').onclick=()=>runStages(['technical','news']);
  $('#runExecution').onclick=()=>runStages(['execution']);
  $('#runFlow').onclick=async()=>{
    if(busy)return;busy=true;$('#runFlow').disabled=true;
    try {const s=await ensureSession(current?.status==='completed');current=s;await post(`/api/flow/sessions/${s.id}/run`);pollSession(s.id)}
    catch(err){error(err)}finally{busy=false;$('#runFlow').disabled=false}
  };
  $('#saveTech').onclick=()=>{
    localStorage.setItem('marketlab.agentParams',JSON.stringify(params()));
    current=null;rendered.clear();showToast('參數已儲存；下次執行會建立帶覆寫版本的新輪次');
  };

  function renderBatch(row) {
    batch=row; $('#batchProgress').classList.remove('hidden');
    const progress=$('#batchProgress progress');progress.classList.remove('hidden');progress.max=row.totalRounds||1;progress.value=row.completedRounds;
    const terminal=['completed','waiting_validation','failed','interrupted'].includes(row.status);
    $('#runBatch').disabled=!terminal;
    setStatus('#batchStatus',row.status==='completed'?'completed':row.status==='failed'||row.status==='interrupted'?'failed':row.status==='waiting_validation'?'waiting':'running',
      {queued:'排隊中',running:'執行中',completed:'完成',waiting_validation:'等待驗證資料',failed:'失敗',interrupted:'執行已中斷'}[row.status]);
    $('#batchSummary').textContent=`${row.symbol} · 分析完成 ${row.completedRounds}/${row.totalRounds} 輪 · ${row.currentAnchor||''} ${stageNames[row.currentStage]||row.currentStage}。
      已驗證 ${row.validatedRounds||0} 輪，成功 ${row.successCount||0} 輪（${row.successRate==null?'尚無完整樣本':row.successRate+'%'}），等待行情 ${row.pendingValidation||0} 輪。${row.error||''}`;
    $('#batchRounds').innerHTML=(row.rounds||[]).map(r=>`<button type="button" class="batch-round" data-session="${esc(r.sessionId)}"><span>${esc(r.anchor)} · ${esc(r.action||'—')} · ${money(r.confidence)}%</span><span>${r.validation?.complete?`${r.validation.success?'成功':'未成功'} · ${money(r.validation.netReturnPct)}%`:r.completed?'等待後續 K 線':'分析中'}</span></button>`).join('');
    $('#refreshBatch').classList.toggle('hidden',row.status!=='waiting_validation');
    document.querySelectorAll('.batch-round').forEach(button=>button.onclick=()=>adoptSession(button.dataset.session));
  }

  async function adoptSession(id) {
    const s=await request(`/api/flow/sessions/${id}`);current=s;rendered.clear();
    await selectSession(s);renderSession(s);localStorage.setItem('marketlab.lastSession',s.id);
  }

  async function pollBatch(id) {
    clearTimeout(batchTimer);
    try {
      const row=await request(`/api/flow/batches/${id}`);renderBatch(row);
      if(row.currentSessionId&&current?.id!==row.currentSessionId)await adoptSession(row.currentSessionId);
      else if(row.currentSessionId){const s=await request(`/api/flow/sessions/${row.currentSessionId}`);renderSession(s)}
      if(['queued','running'].includes(row.status))batchTimer=setTimeout(()=>pollBatch(id),1400);
    }catch(err){error(err);$('#runBatch').disabled=false}
  }

  $('#runBatch').onclick=async()=>{
    if($('#runBatch').disabled)return;
    try {
      validForm(true);$('#runBatch').disabled=true;
      const startDate=$('#batchStart').value,endDate=$('#batchEnd').value;
      if(endDate<startDate)throw new Error('結束日期不可早於開始日期');
      const row=await post('/api/flow/batches',{symbol:getContext().symbol,symbolName:$('#newsName').value,startDate,endDate,maxHoldingDays:Number($('#maxHold').value),holdThresholdPct:Number($('#holdThreshold').value),params:params()});
      localStorage.setItem('marketlab.lastBatch',row.id);renderBatch(row);pollBatch(row.id);
    }catch(err){error(err);$('#runBatch').disabled=false}
  };
  $('#refreshBatch').onclick=async()=>{
    if(!batch)return;$('#refreshBatch').disabled=true;
    try{renderBatch(await post(`/api/flow/batches/${batch.id}/refresh-validation`));if(current)await adoptSession(current.id)}
    catch(err){error(err)}finally{$('#refreshBatch').disabled=false}
  };
  $('#refreshValidation').onclick=async()=>{
    if(!current)return;$('#refreshValidation').disabled=true;
    try{rendered.delete('execution');renderSession(await post(`/api/flow/sessions/${current.id}/refresh-validation`))}
    catch(err){error(err)}finally{$('#refreshValidation').disabled=false}
  };
  $('#playValidation').onclick=()=>{
    const report=current?.runs.execution?.find(r=>r.role==='champion')?.report;
    if(report)replay(report);
  };
  $('#restoreAnchor').onclick=()=>current&&selectSession(current);

  function contextChanged() {
    const context=getContext();$('#techAnchor').textContent=context.anchor?`錨定 ${context.anchor}｜僅使用此前資料`:'請選擇錨定日期';
    $('.news-fields').previousElementSibling.textContent=context.anchor?`錨定 ${context.anchor}｜驗證原文發佈與修改時間`:'先選擇錨定日期';
    if(current&&key(current)===key(context)){renderSession(current);return}
    current=null;rendered.clear();clearTimeout(sessionTimer);
    Object.values(statusIds).forEach(id=>setStatus(id,'waiting'));
    ['#techReport','#newsReport','#executionReport','#adaptiveReport'].forEach(id=>$(id).textContent='請執行此錨點的分析');
    $('#runExecution').disabled=true;$('#flowHint').textContent=context.anchor?'可建立新輪次':'請選擇歷史錨點以建立 Session';
    ['#refreshValidation','#playValidation','#restoreAnchor'].forEach(id=>$(id).classList.add('hidden'));
  }

  async function restore() {
    try {
      const saved=JSON.parse(localStorage.getItem('marketlab.agentParams')||'null');
      if(saved){
        Object.values(saved.technical.weights).forEach((v,i)=>{const input=document.querySelectorAll('.weights input')[i];input.value=v;input.dispatchEvent(new Event('input'))});
        $('.news-fields input').value=saved.news.lookbackDays;$('.news-fields select').value=saved.news.rounds+' 輪';
        $('#executionWeight').value=saved.execution.technicalWeight*100;$('#executionWeight').dispatchEvent(new Event('input'));
        $('#confidence').value=saved.execution.minConfidence;$('#confidence').dispatchEvent(new Event('input'));
        $('#maxHold').value=saved.execution.maxHoldingBars;$('#holdThreshold').value=saved.execution.holdThresholdPct;
      }
      const batchId=localStorage.getItem('marketlab.lastBatch');
      if(batchId){const row=await request(`/api/flow/batches/${batchId}`);$('#batchStart').value=row.startDate;$('#batchEnd').value=row.endDate;$('#maxHold').value=row.maxHoldingDays;$('#holdThreshold').value=row.holdThresholdPct;renderBatch(row);await pollBatch(batchId)}
      else {const sessionId=localStorage.getItem('marketlab.lastSession');if(sessionId){await adoptSession(sessionId);pollSession(sessionId)}}
    }catch(err){error(err)}
  }
  return {contextChanged,restore};
}
