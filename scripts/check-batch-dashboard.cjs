// Read-only browser QA. It opens stored Sessions and creates only an unsaved draft row.
const {chromium}=require('/Users/william/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const base=process.env.MARKETLAB_TEST_URL||'http://127.0.0.1:9021';
(async()=>{
 const output=path.resolve('artifacts/batch-dashboard');await fs.mkdir(output,{recursive:true});
 const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1536,height:900}}),errors=[];page.on('pageerror',error=>errors.push(error.message));
 try{
  const source=await (await page.request.get(base+'/api/flow/batches?limit=100')).json();
  await page.goto(base+'/dashboard',{waitUntil:'domcontentloaded'});await page.locator('[data-tab="batches"]').click();
  await page.locator('.batch-lane[data-batch]').first().waitFor({timeout:30000});
  const state=await page.evaluate(()=>({lanes:document.querySelectorAll('.batch-lane[data-batch]').length,pageWidth:document.documentElement.scrollWidth,viewport:innerWidth,tab:document.querySelector('#batches').classList.contains('active'),timelineOverflow:[...document.querySelectorAll('.timeline-scroll')].some(row=>row.scrollWidth>row.clientWidth)}));
  assert.equal(state.lanes,source.batches.length);assert.equal(state.pageWidth,state.viewport);assert.equal(state.tab,true);assert.equal(state.timelineOverflow,true);
  const firstWithSession=page.locator('.timeline-node[data-session]').first();await firstWithSession.click();await page.locator('#sessionDetail[open]').waitFor();
  const detail=await page.locator('#detailContent').textContent();for(const label of ['第一層 · 技術 Agent','第一層 · 新聞 Agent','第二層 · 執行 Agent','第三層 · 自適應 Agent'])assert.ok(detail.includes(label),label);
  await page.screenshot({path:path.join(output,'session-detail.png')});
  await page.locator('#sessionDetail form button').click();
  await page.locator('#addBatchLane').click();const draft=page.locator('.batch-lane-draft').first();await draft.locator('[name="symbol"]').fill('AAPL');await draft.locator('[name="startDate"]').fill('2026-09-01');await draft.locator('[name="endDate"]').fill('2026-09-03');
  assert.equal(await draft.locator('[name="symbol"]').inputValue(),'AAPL');await page.screenshot({path:path.join(output,'batch-dashboard-1536.png'),fullPage:true});
  await page.setViewportSize({width:1280,height:800});await page.waitForTimeout(350);
  const narrow=await page.evaluate(()=>({pageWidth:document.documentElement.scrollWidth,viewport:innerWidth,draftWidth:document.querySelector('.batch-lane-draft').getBoundingClientRect().width,panelWidth:document.querySelector('.batch-board').getBoundingClientRect().width}));
  assert.equal(narrow.pageWidth,narrow.viewport);assert.ok(narrow.draftWidth<=narrow.panelWidth);await page.screenshot({path:path.join(output,'batch-dashboard-1280.png'),fullPage:true});
  let resolvePost;const postCaptured=new Promise(resolve=>resolvePost=resolve);
  await page.route('**/api/flow/batches*',async route=>{if(route.request().method()!=='POST')return route.continue();const body=route.request().postDataJSON();resolvePost(body);await route.fulfill({status:202,contentType:'application/json',body:JSON.stringify({id:'qa-only',status:'queued',symbol:body.symbol,anchors:[],rounds:[]})})});
  await draft.locator('button.primary').click();const submitted=await postCaptured;assert.deepEqual({symbol:submitted.symbol,startDate:submitted.startDate,endDate:submitted.endDate,maxHoldingDays:submitted.maxHoldingDays,holdThresholdPct:submitted.holdThresholdPct},{symbol:'AAPL',startDate:'2026-09-01',endDate:'2026-09-03',maxHoldingDays:5,holdThresholdPct:2});
  assert.equal((await (await page.request.get(base+'/api/flow/batches?limit=100')).json()).batches.length,source.batches.length);
  assert.deepEqual(errors,[]);const evidence={base,batches:source.batches.length,state,narrow,submitted,errors};await fs.writeFile(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));console.log('PASS',JSON.stringify(evidence));
 }catch(error){await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});throw error}finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
