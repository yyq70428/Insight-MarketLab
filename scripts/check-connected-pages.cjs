const {chromium}=require('/Users/william/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const output=path.resolve('artifacts/flow-check');await fs.mkdir(output,{recursive:true});
 const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1536,height:850}}),errors=[],evidence={};page.on('pageerror',e=>{errors.push({message:e.message,stack:e.stack});console.error('BROWSER ERROR',e.stack)});
 try{
  await page.goto('http://127.0.0.1:9021/');await page.waitForFunction(()=>document.querySelector('#dataStatus').textContent.includes('已連線'),null,{timeout:60000});
  let sid=process.argv[2];
  if(sid){
   // Reproduce the restore race: persisted reports arrive before anchor candles.
   await page.evaluate(id=>localStorage.setItem('marketlab.lastSession',id),sid);
   let release;const gate=new Promise(resolve=>release=resolve);
   await page.route('**/api/candles?**',async route=>{if(new URL(route.request().url()).searchParams.get('anchor'))await gate;await route.continue()});
   try{
    await page.reload();await page.waitForFunction(()=>document.querySelector('#adaptiveStatus').textContent==='完成',null,{timeout:60000});
    assert.equal(await page.locator('#playValidation').isDisabled(),true);
    await page.locator('#playValidation').dispatchEvent('click');
    assert.doesNotMatch(await page.locator('#dataStatus').textContent(),/紙上驗證回放/);
   }finally{release()}
   await page.waitForFunction(()=>!document.querySelector('#playValidation').disabled,null,{timeout:60000});
   await page.unroute('**/api/candles?**');console.log('Delayed anchor/replay race guard passed');
  }
  else {
  await page.locator('#anchorDate').fill('2026-09-03');await page.locator('#anchorDate').dispatchEvent('change');
  await page.waitForFunction(()=>document.querySelector('#dataStatus').textContent.includes('錨點後資料已隔離'),null,{timeout:60000});
  await page.locator('#runFirst').click();
  await page.waitForFunction(()=>!document.querySelector('#runExecution').disabled,null,{timeout:300000});console.log('First layer complete');
  await page.locator('#runExecution').click();
  await page.waitForFunction(()=>document.querySelector('#adaptiveStatus').textContent==='完成',null,{timeout:300000});
  sid=await page.evaluate(()=>localStorage.getItem('marketlab.lastSession'));
  }
  const s=await (await page.request.get('http://127.0.0.1:9021/api/flow/sessions/'+sid)).json();
  assert.equal(s.status,'completed');assert.equal(s.labelComplete,true);assert.equal(s.decision.modelUsed,true);
  evidence.session={id:sid,stageStatus:s.stageStatus,decision:s.decision,outcome:s.outcome,versions:s.versions,newsEvaluation:s.newsEvaluations};
  await page.locator('#playValidation').click();await page.waitForFunction(()=>document.querySelector('#dataStatus').textContent.includes('紙上驗證回放'));
  await page.waitForTimeout(3500);await page.screenshot({path:path.join(output,'single-replay.png')});
  await page.locator('#restoreAnchor').click();await page.waitForFunction(()=>document.querySelector('#dataStatus').textContent.includes('錨點後資料已隔離'),null,{timeout:60000});
  await page.reload();await page.waitForFunction(()=>document.querySelector('#adaptiveStatus').textContent==='完成',null,{timeout:60000});
  assert.equal(await page.evaluate(()=>localStorage.getItem('marketlab.lastSession')),sid);console.log('Single flow, replay and reload passed',sid);
  await fs.writeFile(path.join(output,'single-flow.json'),JSON.stringify(evidence,null,2));
  await page.goto('http://127.0.0.1:9021/quant');await page.locator('#quantForm button').click();
  await page.waitForFunction(()=>!document.querySelector('#quantForm button').disabled,null,{timeout:180000});
  evidence.quant={status:await page.locator('#quantStatus').textContent(),windows:await page.locator('#walkForward').textContent(),robustness:await page.locator('#robustness').textContent()};
  assert.match(evidence.quant.status,/滾動驗證完成/);assert.match(evidence.quant.windows,/不重疊驗證窗/);assert.match(evidence.quant.robustness,/擾動結果/);
  await page.screenshot({path:path.join(output,'quant-live.png')});console.log('Quant page passed');
  await page.goto('http://127.0.0.1:9021/dashboard');await page.locator('[data-tab="sessions"]').click();
  await page.locator('[data-session="'+sid+'"]').click();await page.waitForSelector('#sessionDetail[open]');
  assert.match(await page.locator('#detailContent').textContent(),/champion/);await page.screenshot({path:path.join(output,'session-detail.png')});
  evidence.errors=errors;assert.deepEqual(errors,[]);await fs.writeFile(path.join(output,'connected-pages.json'),JSON.stringify(evidence,null,2));
  console.log('PASS',JSON.stringify({session:sid,quant:evidence.quant.status,errors}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
