// Real HTTP/model smoke test. Creates persisted paper-backtest sessions, never orders.
const {chromium}=require('/Users/william/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const output=path.resolve('artifacts/flow-check');await fs.mkdir(output,{recursive:true});
 const start=process.argv[2]||'2026-09-09',end=process.argv[3]||'2026-09-12';
 const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1536,height:850}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto('http://127.0.0.1:9021/',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.querySelector('#dataStatus').textContent.includes('已連線'),null,{timeout:60000});
  await page.locator('#batchStart').fill(start);await page.locator('#batchEnd').fill(end);
  const createdPromise=page.waitForResponse(r=>r.url().endsWith('/api/flow/batches')&&r.request().method()==='POST');
  await page.locator('#runBatch').click();const response=await createdPromise,created=await response.json();assert.equal(response.status(),202,JSON.stringify(created));
  console.log('CREATED',created.id,created.anchors);
  await page.reload({waitUntil:'domcontentloaded'});
  let batch,previous='';const deadline=Date.now()+600000;
  while(Date.now()<deadline){
   const response=await page.request.get('http://127.0.0.1:9021/api/flow/batches/'+created.id);batch=await response.json();
   const status=[batch.status,batch.currentRound,batch.currentStage,batch.completedRounds].join(' ');
   if(status!==previous){console.log(status);previous=status}
   if(!['queued','running'].includes(batch.status))break;
   await new Promise(resolve=>setTimeout(resolve,2000));
  }
  const sessions=[];for(const id of batch.sessionIds)sessions.push(await (await page.request.get('http://127.0.0.1:9021/api/flow/sessions/'+id)).json());
  await page.waitForFunction(()=>['完成','等待驗證資料','失敗','執行已中斷'].includes(document.querySelector('#batchStatus').textContent),null,{timeout:15000});
  await page.screenshot({path:path.join(output,start+'-batch.png')});
  const evidence={start,end,batch,sessions,errors,reloadedBatch:await page.evaluate(()=>localStorage.getItem('marketlab.lastBatch')),uiSummary:await page.locator('#batchSummary').textContent()};
  await fs.writeFile(path.join(output,start+'-result.json'),JSON.stringify(evidence,null,2));
  assert.ok(['completed','waiting_validation'].includes(batch.status),batch.error||batch.status);assert.equal(errors.length,0,errors.join('\n'));
  assert.equal(batch.completedRounds,batch.totalRounds);assert.equal(evidence.reloadedBatch,created.id);
  for(let i=0;i<sessions.length;i++){
   const s=sessions[i];assert.equal(s.status,'completed');assert.ok(Object.values(s.stageStatus).every(x=>x==='completed'));
   if(i){assert.equal(s.previousSessionId,sessions[i-1].id);assert.ok(s.createdAt>=sessions[i-1].completedAt)}
   const actions=s.events.map(e=>e.action);assert.ok(actions.indexOf('decision_frozen')<actions.indexOf('future_data_requested'));
   if(!s.labelComplete){assert.equal(s.outcome.success,null);assert.equal(s.outcome.netReturnPct,null)}
  }
  await page.goto('http://127.0.0.1:9021/dashboard',{waitUntil:'networkidle'});
  for(const tab of ['sessions','strategies','versions','audit','overview']){await page.locator('[data-tab="'+tab+'"]').click();await page.waitForTimeout(400);assert.equal(await page.locator('#dbNotice').isVisible(),false,await page.locator('#dbNotice').textContent())}
  await page.screenshot({path:path.join(output,start+'-dashboard.png')});
  console.log('PASS',JSON.stringify({id:batch.id,status:batch.status,rounds:batch.completedRounds,validated:batch.validatedRounds,pending:batch.pendingValidation,models:sessions.map(s=>s.decision.modelUsed),articles:sessions.map(s=>s.articleCount),errors}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
