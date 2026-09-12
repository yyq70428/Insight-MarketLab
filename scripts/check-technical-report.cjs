// Real market data + technical-only Sessions. No news/model requests or real trades.
const {chromium}=require('/Users/william/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const output=path.resolve('artifacts/technical-report');await fs.mkdir(output,{recursive:true});
 const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1536,height:1300}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto('http://127.0.0.1:9021/');
  await page.waitForFunction(()=>document.querySelector('#dataStatus').textContent.includes('已連線'),null,{timeout:60000});
  await page.locator('#anchorDate').fill('2026-09-01');await page.locator('#anchorDate').dispatchEvent('change');
  await page.waitForFunction(()=>document.querySelector('#dataStatus').textContent.includes('錨點後資料已隔離'),null,{timeout:60000});
  await page.locator('#runTech').click();
  await page.waitForFunction(()=>document.querySelector('#techStatus').textContent==='完成',null,{timeout:120000});
  const id=await page.evaluate(()=>localStorage.getItem('marketlab.lastSession'));
  const original=await (await page.request.get('http://127.0.0.1:9021/api/flow/sessions/'+id)).json();
  const report=original.runs.technical.find(r=>r.role==='champion').report;
  assert.equal(report.engineVersion,'technical-2.1-position-aware');
  const text=await page.locator('#techReport').textContent();
  for(const expected of ['看多','看空','建議：','預期買入','預期賣出','預期上漲','預期下跌','目標時間','諧波','支撐壓力','MACD','RSI','波形位置','低位不代表已落底','高位不代表已見頂','不是上漲機率或勝率'])assert.ok(text.includes(expected),expected);
  for(const value of [report.expectedBuy,report.expectedSell,report.upsidePct,report.downsidePct])assert.ok(text.includes(value.toFixed(2)));
  assert.ok(text.includes(report.bullishPct.toFixed(1)+'%')&&text.includes(report.bearishPct.toFixed(1)+'%'));
  assert.ok(![0,6].includes(new Date(report.expectedTime.date+'T00:00:00Z').getUTCDay()));
  const security=await page.evaluate(async report=>{
   const {technicalReportHTML}=await import('/static/js/technical-report.js');
   const host=document.createElement('div');
   host.innerHTML=technicalReportHTML({...report,components:{macd:{score:60,reason:'<img src=x onerror="alert(1)">'}},recommendation:'<script>alert(1)</script>'});
   const legacy=technicalReportHTML({...report,macdContext:null});
   return {unsafe:host.querySelectorAll('img,script').length,escaped:host.textContent.includes('<img'),legacy:legacy.includes('舊版報告')};
  },report);
  assert.deepEqual(security,{unsafe:0,escaped:true,legacy:true});
  await page.locator('.agent-card').first().screenshot({path:path.join(output,'technical-card.png')});
  const sizes=[];
  for(const [width,height] of [[2048,1006],[1536,850],[1280,720]]){
   await page.setViewportSize({width,height});await page.waitForTimeout(300);
   const size=await page.evaluate(()=>{const card=document.querySelector('#techReport'),rail=document.querySelector('.agent-sidebar');return {width:innerWidth,pageWidth:document.documentElement.scrollWidth,cardWidth:card.clientWidth,cardScrollWidth:card.scrollWidth,railWidth:rail.clientWidth}});
   assert.equal(size.width,size.pageWidth);assert.ok(size.cardScrollWidth<=size.cardWidth);assert.ok(size.railWidth<=540);sizes.push(size);
  }
  await page.locator('#runTech').click();
  await page.waitForFunction(old=>localStorage.getItem('marketlab.lastSession')!==old&&document.querySelector('#techStatus').textContent==='完成',id,{timeout:120000});
  const next=await page.evaluate(()=>localStorage.getItem('marketlab.lastSession'));assert.notEqual(next,id);
  const preserved=await (await page.request.get('http://127.0.0.1:9021/api/flow/sessions/'+id)).json();
  assert.deepEqual(preserved.runs.technical,original.runs.technical);
  assert.deepEqual(errors,[]);
  await fs.writeFile(path.join(output,'evidence.json'),JSON.stringify({id,next,report,sizes,errors,security},null,2));
  console.log('PASS',JSON.stringify({id,next,macd:report.macdContext,expectedTime:report.expectedTime,sizes,errors}));
 }catch(error){await page.screenshot({path:path.join(output,'failure.png')});throw error}
 finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
