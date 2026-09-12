const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../js/batch-timeline.js'),'utf8');
const modulePromise=import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const base=()=>({id:'b1',symbol:'0050.TW',status:'running',anchors:['2026-09-01','2026-09-02','2026-09-03'],currentAnchor:'2026-09-02',currentSessionId:'s2',currentStage:'execution',completedRounds:1,rounds:[{sessionId:'s1',anchor:'2026-09-01',completed:true,action:'BUY',confidence:66,validation:{complete:true,success:true,netReturnPct:2.345}}]});

test('timeline preserves every trading day and links available sessions',async()=>{
 const {batchNodes}=await modulePromise,nodes=batchNodes(base());
 assert.equal(nodes.length,3);assert.equal(nodes[0].sessionId,'s1');assert.equal(nodes[1].sessionId,'s2');assert.equal(nodes[2].sessionId,null);
});
test('active node exposes current agent layer',async()=>{
 const {batchNodes}=await modulePromise,node=batchNodes(base())[1];
 assert.equal(node.state,'running');assert.equal(node.detail,'第二層決策');
});
test('validated outcome keeps the signed paper return',async()=>{
 const {batchNodes,batchOutcome}=await modulePromise,round=base().rounds[0];
 assert.equal(batchNodes(base())[0].state,'success');assert.equal(batchOutcome(round),'獲利 +2.35%');
});
test('pending validation is distinct from a failed result',async()=>{
 const {batchNodes}=await modulePromise,row=base();row.rounds[0].validation={complete:false,bars:2,requiredBars:5};
 const node=batchNodes(row)[0];assert.equal(node.state,'waiting');assert.equal(node.detail,'等待後續 K 線');
});
test('interrupted current day is marked without fabricating a session result',async()=>{
 const {batchNodes}=await modulePromise,row=base();row.status='interrupted';row.currentAnchor='2026-09-02';row.rounds=[];row.completedRounds=0;
 const node=batchNodes(row)[0];assert.equal(node.state,'failed');assert.equal(node.detail,'執行中斷');assert.equal(node.sessionId,null);
});
