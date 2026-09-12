const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const source=fs.readFileSync(require('node:path').join(__dirname,'../js/execution-overlay.js'),'utf8');
const modulePromise=import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const session=(action='BUY')=>({id:'s1',batchId:'b1',anchor:'2026-09-01',candleSnapshot:[{time:100}],decision:{action,confidence:72},
 runs:{technical:[{role:'champion',report:{expectedSell:112,downside:98}}],execution:[{role:'champion',status:'running',decision:{action,confidence:72}}]}});
test('running BUY decision exposes target and stop before validation',async()=>{
 const {executionOverlay,outcomeLabel}=await modulePromise,view=executionOverlay(session(),{id:'b1',currentSessionId:'s1',currentRound:2,totalRounds:5});
 assert.deepEqual({target:view.target,stop:view.stop,phase:view.phase,round:view.round}, {target:112,stop:98,phase:'executing',round:2});
 assert.match(outcomeLabel(view),/正在紙上驗證/);
});
test('SELL reverses target and stop roles',async()=>{
 const {executionOverlay}=await modulePromise,view=executionOverlay(session('SELL'));
 assert.equal(view.target,98);assert.equal(view.stop,112);
});
test('public session can bind to the chart anchor time',async()=>{
 const {executionOverlay}=await modulePromise,s=session();delete s.candleSnapshot;
 assert.equal(executionOverlay(s,null,1788393600).anchorTime,1788393600);
});
test('completed result keeps backend target and signed net return',async()=>{
 const {executionOverlay,outcomeLabel}=await modulePromise,s=session();
 s.runs.execution[0]={role:'champion',status:'completed',report:{decision:s.decision,target:115,stop:97,replay:[{time:101}],validation:{complete:true,netReturnPct:-1.25,entryTime:101,exitTime:102}}};
 const view=executionOverlay(s);assert.equal(view.phase,'completed');assert.equal(view.target,115);assert.equal(view.replay.length,1);assert.equal(outcomeLabel(view),'虧損 -1.25%');
});
test('HOLD result describes prediction success rather than fabricated profit',async()=>{
 const {executionOverlay,outcomeLabel}=await modulePromise,s=session('HOLD');
 s.runs.execution[0]={role:'champion',report:{decision:s.decision,target:112,stop:98,replay:[],validation:{complete:true,success:false,netReturnPct:0}}};
 assert.equal(outcomeLabel(executionOverlay(s)),'預測未成功 · 淨報酬 0.00%');
});
test('no decision means no execution overlay',async()=>{
 const {executionOverlay}=await modulePromise,s=session();delete s.decision;s.runs.execution=[];
 assert.equal(executionOverlay(s),null);
});
