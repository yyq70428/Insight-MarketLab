// Read-only browser QA against real, anchored 2330.TW candles.
const {chromium}=require('/Users/william/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const base=process.env.MARKETLAB_TEST_URL||'http://127.0.0.1:9021';
(async()=>{
 const output=path.resolve('artifacts/zone-history');await fs.mkdir(output,{recursive:true});
 const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1920,height:1200}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 // Capture the real chart only in the test browser; no production debug globals.
 await page.addInitScript(()=>{
  localStorage.setItem('marketlab.symbol','2330.TW');
  let library;
  Object.defineProperty(window,'LightweightCharts',{configurable:true,get:()=>library,set:api=>{
   library={...api,createChart:(...args)=>{
    const chart=api.createChart(...args),add=chart.addCandlestickSeries.bind(chart);
    chart.addCandlestickSeries=(...options)=>{
     const series=add(...options),attach=series.attachPrimitive.bind(series);
     series.attachPrimitive=primitive=>{window.__zoneQA={chart,series,primitive};return attach(primitive)};
     return series;
    };
    return chart;
   }};
  }});
 });
 try{
  await page.goto(base+'/');
  await page.waitForFunction(()=>document.querySelector('#dataStatus').textContent.includes('已連線'),null,{timeout:60000});
  const response=page.waitForResponse(r=>r.url().includes('/api/analysis?')&&r.url().includes('anchor=2026-09-03'));
  await page.locator('#anchorDate').fill('2026-09-03');await page.locator('#anchorDate').dispatchEvent('change');
  const analysis=await (await response).json();
  await page.waitForFunction(()=>document.querySelector('#dataStatus').textContent.includes('錨點後資料已隔離'),null,{timeout:60000});
  assert.ok(analysis.zones.length<=6&&analysis.historicalZones.length>6&&analysis.historicalZones.length<=96);
  const cutoff=new Date('2026-09-04T00:00:00+08:00').getTime()/1000;
  assert.ok(analysis.historicalZones.every(z=>z.asOfTime<cutoff&&z.lastTime<=z.asOfTime));
  const capture=async(name)=>{
   await page.waitForTimeout(500);
   const state=await page.evaluate(()=>({range:__zoneQA.chart.timeScale().getVisibleRange(),zones:__zoneQA.primitive.displayed,
    width:innerWidth,pageWidth:document.documentElement.scrollWidth,railWidth:document.querySelector('.agent-sidebar').clientWidth}));
   assert.equal(state.width,state.pageWidth);assert.ok(state.railWidth<=540);assert.ok(state.zones.length<=8);
   await page.screenshot({path:path.join(output,name+'.png')});return state;
  };
  const current=await capture('current');
  assert.ok(await page.evaluate(()=>__zoneQA.primitive.rows.length>1000),'Requested long history must not silently become a short scanner series');
  assert.equal(await page.evaluate(()=>__zoneQA.primitive.rows.at(-1).close),2390,'2330 anchor quote verified against a separate source request');
  assert.ok(current.zones.some(z=>z.historical&&z.midpoint<1800),'Older, lower historical zones are visible alongside current prices');
  // Move the actual chart viewport back roughly two years, without another API call.
  await page.evaluate(()=>{const {chart,primitive}=__zoneQA,rows=primitive.rows;chart.timeScale().setVisibleRange({from:rows[360].time,to:rows[620].time})});
  const older=await capture('older');
  assert.ok(older.zones.length>=2&&older.zones.every(z=>z.historical));
  assert.ok(older.zones.every(z=>z.asOfTime<=older.range.to));
  assert.notDeepEqual(older.zones.map(z=>z.midpoint),current.zones.map(z=>z.midpoint));
  await page.evaluate(()=>__zoneQA.chart.timeScale().fitContent());
  const full=await capture('full-history');
  assert.ok(full.zones.some(z=>z.historical&&z.midpoint<1000));
  await page.locator('[data-toggle="zones"]').click();await page.waitForTimeout(300);
  assert.equal(await page.evaluate(()=>__zoneQA.primitive.displayed.length),0);
  assert.equal(await page.locator('#zoneHistoryNote').isVisible(),false);
  await page.locator('[data-toggle="zones"]').click();await page.waitForTimeout(300);
  assert.ok(await page.evaluate(()=>__zoneQA.primitive.displayed.length>0));
  const widths=[];
  for(const width of [1536,1280]){await page.setViewportSize({width,height:850});widths.push(await capture('history-'+width))}
  assert.deepEqual(errors,[]);
  await fs.writeFile(path.join(output,'evidence.json'),JSON.stringify({base,symbol:analysis.symbol,anchor:analysis.anchor,historyCount:analysis.historicalZones.length,current,older,full,widths,errors},null,2));
  console.log('PASS',JSON.stringify({historyCount:analysis.historicalZones.length,current:current.zones.map(z=>z.midpoint),older:older.zones.map(z=>z.midpoint),full:full.zones.map(z=>z.midpoint),errors}));
 }catch(error){await page.screenshot({path:path.join(output,'failure.png')});throw error}
 finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
