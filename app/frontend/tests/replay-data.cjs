const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const source=fs.readFileSync(require('node:path').join(__dirname,'../js/replay-data.js'),'utf8');
const modulePromise=import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
test('replay only appends requested future bars without mutating input',async()=>{
 const {replayRows}=await modulePromise,a=[{time:1},{time:2}],f=[{time:3},{time:4}];
 assert.deepEqual(replayRows(a,f,1),[{time:1},{time:2},{time:3}]);assert.equal(a.length,2);
});
test('live timeline overlapping restored replay is rejected',async()=>{
 const {replayRows}=await modulePromise;
 assert.throws(()=>replayRows([{time:1},{time:2},{time:3}],[{time:2},{time:3}],1),/重疊/);
});
test('empty anchor is not ready',async()=>{
 const {replayRows}=await modulePromise;assert.throws(()=>replayRows([],[{time:2}],1),/尚未載入/);
});
test('unsorted or duplicate future rows are rejected',async()=>{
 const {replayRows}=await modulePromise;
 assert.throws(()=>replayRows([{time:1}],[{time:3},{time:2}],2),/不可重複/);
 assert.throws(()=>replayRows([{time:1}],[{time:2},{time:2}],2),/不可重複/);
});
