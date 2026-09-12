const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const source=fs.readFileSync(require('node:path').join(__dirname,'../js/support-zones.js'),'utf8');
const modulePromise=import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const projected=(mid,historical=true,start=10)=>({high:mid-2,low:mid+2,mid,start,last:start+50,
 zone:{low:1000-mid-2,high:1000-mid+2,midpoint:1000-mid,startTime:1,lastTime:2,asOfTime:3,historical,type:'support',strength:80,touches:3}});
test('wide view retains both current levels and much older price regions',async()=>{
 const {visibleZones}=await modulePromise;
 const selected=visibleZones([projected(60,false),projected(110,false),...[160,200,250,300,350,400,450,500,550].map(x=>projected(x))],{width:1000,height:600,price:960});
 assert.ok(selected.some(x=>!x.zone.historical));assert.ok(selected.some(x=>x.mid>450));assert.ok(selected.length<=8);
 for(const a of selected)for(const b of selected)if(a!==b)assert.ok(Math.abs(a.mid-b.mid)>=30);
});
test('panning to old candles selects historical levels instead of offscreen recent zones',async()=>{
 const {visibleZones}=await modulePromise;
 const selected=visibleZones([projected(80,false,1200),projected(160),projected(320)],{width:800,height:500,price:900});
 assert.equal(selected.length,2);assert.ok(selected.every(x=>x.zone.historical));
});
test('overlapping historical windows do not duplicate bands or labels',async()=>{
 const {visibleZones}=await modulePromise;
 const selected=visibleZones([projected(100),projected(101),projected(102),projected(300)],{width:1000,height:500,price:950});
 assert.equal(selected.length,2);
});
test('out of range or invalid coordinates are excluded and budget respected',async()=>{
 const {visibleZones}=await modulePromise;
 const selected=visibleZones([projected(-100),projected(600),projected(null),projected(100),projected(300),projected(400)],{width:1000,height:500,price:950,limit:2});
 assert.equal(selected.length,2);assert.ok(selected.every(x=>Number.isFinite(x.mid)&&x.mid>=12&&x.mid<=488));
});
test('primitive redraw changes historical selection as time range changes, without reloading data',async()=>{
 const {SupportZones}=await modulePromise;
 const primitive=new SupportZones();let end=100;
 primitive.attached({chart:{timeScale:()=>({getVisibleRange:()=>({from:1,to:end}),timeToCoordinate:t=>t})},
  series:{priceToCoordinate:p=>500-p},requestUpdate:()=>{}});
 primitive.setZones([{...projected(100).zone,low:198,high:202,midpoint:200,asOfTime:50},
  {...projected(200).zone,low:298,high:302,midpoint:300,asOfTime:150}], [{time:100,close:250,low:190,high:310},{time:200,close:350,low:190,high:360}]);
 const ctx=new Proxy({measureText:()=>({width:100})},{get:(target,key)=>target[key]||(()=>{}),set:(target,key,value)=>(target[key]=value,true)});
 const target={useMediaCoordinateSpace:fn=>fn({context:ctx,mediaSize:{width:800,height:500}})};
 primitive.draw(target);assert.equal(primitive.displayed.length,1);assert.equal(primitive.displayed[0].type,'support');
 end=200;primitive.draw(target);assert.equal(primitive.displayed.length,2);
 primitive.setZones([]);primitive.draw(target);assert.deepEqual(primitive.displayed,[]);
});
