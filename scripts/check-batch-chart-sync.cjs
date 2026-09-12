// Read-only QA: reuses one completed paper-validation Session and creates no jobs.
const {chromium}=require('/Users/william/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const base=process.env.MARKETLAB_TEST_URL||'http://127.0.0.1:9021';
const sessionId=process.argv[2]||'cc7e8a2d6b384743b26dd5cad7c5529f';
(async()=>{
 const output=path.resolve('artifacts/batch-chart-sync');await fs.mkdir(output,{recursive:true});
 const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1536,height:980}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(id=>{localStorage.removeItem('marketlab.lastBatch');localStorage.setItem('marketlab.lastSession',id);localStorage.setItem('marketlab.symbol','0050.TW');},sessionId);
 try{
  const source=await (await page.request.get(base+'/api/flow/sessions/'+sessionId)).json();
  const execution=source.runs.execution.find(run=>run.role==='champion').report;
  await page.goto(base+'/',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(id=>localStorage.getItem('marketlab.lastSession')===id&&document.querySelector('#batchTradeOverlay')&&!document.querySelector('#batchTradeOverlay').classList.contains('hidden'),sessionId,{timeout:90000});
  await page.waitForFunction(()=>/區間回測|紙上驗證/.test(document.querySelector('#dataStatus').textContent),null,{timeout:30000});
  const widths=[];
  for(const [width,height] of [[1536,980],[1280,800]]){
   await page.setViewportSize({width,height});await page.waitForTimeout(500);
   const state=await page.evaluate(()=>({
    columns:getComputedStyle(document.querySelector('.first-layer')).gridTemplateColumns.split(' ').filter(Boolean),
    techX:document.querySelector('#techReport').closest('.agent-card').getBoundingClientRect().x,
    newsX:document.querySelector('#newsReport').closest('.agent-card').getBoundingClientRect().x,
    overlay:document.querySelector('#batchTradeOverlay').textContent,
    layer2:[...document.querySelectorAll('h3')].some(h=>h.textContent.includes('第二層 · 執行 Agent')),
    layer3:[...document.querySelectorAll('h3')].some(h=>h.textContent.includes('第三層 · 自適應 Agent')),
    pageWidth:document.documentElement.scrollWidth,viewport:innerWidth,rail:document.querySelector('.agent-sidebar').clientWidth,
  }));
   assert.equal(state.columns.length,2);assert.ok(state.newsX>state.techX);assert.ok(state.layer2&&state.layer3);
   assert.equal(state.pageWidth,state.viewport);assert.ok(state.rail<=540);
   for(const text of ['2026-09-03','賣出','目標','停損','虧損','-1.59%'])assert.ok(state.overlay.includes(text),text);
   widths.push(state);await page.screenshot({path:path.join(output,'sync-'+width+'.png')});
  }
  assert.equal(source.anchor,'2026-09-03');assert.equal(source.decision.action,'SELL');
  assert.equal(execution.validation.complete,true);assert.ok(execution.validation.entryTime&&execution.validation.exitTime);
  assert.ok(execution.replay.at(-1).time>=execution.validation.exitTime);
  assert.deepEqual(errors,[]);
  await fs.writeFile(path.join(output,'evidence.json'),JSON.stringify({base,sessionId,target:execution.target,stop:execution.stop,validation:execution.validation,widths,errors},null,2));
  console.log('PASS',JSON.stringify({sessionId,action:source.decision.action,target:execution.target,stop:execution.stop,net:execution.validation.netReturnPct,widths:widths.map(x=>({viewport:x.viewport,columns:x.columns,rail:x.rail})),errors}));
 }catch(error){await page.screenshot({path:path.join(output,'failure.png')});throw error}finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
