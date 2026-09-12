import{query,request}from './api.js';
import{escapeHtml as esc,money}from './util.js';
const $=s=>document.querySelector(s),metric=(label,value)=>'<article><span>'+label+'</span><strong>'+value+'</strong></article>';
let chartRows=[],benchmark=[];
$('#quantForm').onsubmit=async event=>{
 event.preventDefault();const button=event.currentTarget.querySelector('button');button.disabled=true;
 $('#quantStatus').textContent='正在取得行情、逐窗選參數與驗證…';
 try{
  const data=await query('/api/quant-scan',Object.fromEntries(new FormData(event.currentTarget))),r=data.result,w=data.walkForward;
  $('#quantStatus').textContent=(w.status==='completed'?'滾動驗證完成':'歷史不足，僅一般回測')+' · '+data.symbol+' · '+data.source+' · '+data.priceBasis;
  $('#metricGrid').innerHTML=metric('總報酬',r.totalReturnPct+'%')+metric('年化報酬',r.annualReturnPct+'%')+metric('年化夏普',r.sharpe)+metric('最大回撤',r.maxDrawdownPct+'%')+metric('交易次數',r.trades)+metric('勝率',r.winRatePct+'%');
  chartRows=r.equity;benchmark=w.benchmark?.equity||[];draw();
  $('#walkForward').innerHTML=w.status!=='completed'?esc(w.message):
   '<p>'+w.windows.length+' 個不重疊驗證窗 · 買入持有 '+w.benchmark.totalReturnPct+'%</p>'+
   (r.insufficientSamples?'<p>交易數少於 30，統計證據不足。</p>':'')+(w.overfitRisk?'<p>驗證夏普明顯低於訓練，存在過擬合風險。</p>':'')+
   '<details><summary>逐窗參數與結果</summary>'+w.windows.map(v=>'<p>'+esc(v.validationStart.slice(0,10))+' 至 '+esc(v.validationEndExclusive.slice(0,10))+'（不含） · '+v.returnPct+'%<br>'+esc(JSON.stringify(v.params))+'</p>').join('')+'</details>';
  $('#walkForward').insertAdjacentHTML('afterbegin','<p>'+esc(data.fallbackReason||data.sourceLimit||'')+'</p>'+
   (data.qualityChecks?.events||[]).map(v=>'<p>'+esc(v.date)+' 來源跨日 '+v.sourceGapPct+'% ／對照 '+v.referenceGapPct+'%</p>').join(''));
  const coverage=data.qualityChecks?.coverage;
  if(coverage)$('#walkForward').insertAdjacentHTML('afterbegin','<p>實際資料 '+esc(coverage.usedStart)+' ～ '+esc(coverage.usedEnd)+'；較原來源缺 '+coverage.missingSourceDays+' 個交易日，不填補。</p>');
  $('#robustness').innerHTML=w.robustness?'<p>訓練選定 '+esc(JSON.stringify(w.robustness.bestParams))+'</p><p>'+esc(w.robustness.criterion)+'：'+(w.robustness.robust?'通過':'未通過')+'</p><details><summary>'+w.robustness.perturbations.length+' 組擾動結果</summary>'+w.robustness.perturbations.map(v=>'<p>'+esc(JSON.stringify(v.params))+' · '+money(v.returnPct)+'% · 差 '+money(v.differencePct)+' 個百分點</p>').join('')+'</details>':'資料不足，未進行擾動驗證';
 }catch(e){$('#quantStatus').textContent=e.message}finally{button.disabled=false}
};
function draw(){
 const c=$('#equityChart'),b=c.getBoundingClientRect(),ratio=devicePixelRatio||1;c.width=b.width*ratio;c.height=b.height*ratio;
 const ctx=c.getContext('2d');ctx.scale(ratio,ratio);ctx.fillStyle='#8995a9';ctx.font='12px system-ui';ctx.strokeStyle='#2b3445';
 const values=[...chartRows,...benchmark].map(r=>r.value),min=Math.min(1,...values),max=Math.max(1,...values),span=max-min||1;
 for(let i=0;i<5;i++){const y=35+i*(b.height-65)/4;ctx.beginPath();ctx.moveTo(48,y);ctx.lineTo(b.width-20,y);ctx.stroke();if(values.length)ctx.fillText((max-i*span/4).toFixed(2),5,y)}
 if(!values.length)return;
 for(const [rows,color,label,x] of [[chartRows,'#316cff','策略',60],[benchmark,'#18b7a6','買入持有',130]]){
  ctx.fillStyle=color;ctx.fillText(label,x,18);ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();
  rows.forEach((r,i)=>{const px=48+i*(b.width-70)/Math.max(1,rows.length-1),py=35+(max-r.value)/span*(b.height-65);i?ctx.lineTo(px,py):ctx.moveTo(px,py)});ctx.stroke();
 }
 ctx.fillStyle='#8995a9';ctx.fillText('倍數',5,18);
 for(const fraction of [0,.5,1]){
  const row=chartRows[Math.round(fraction*(chartRows.length-1))];if(!row)continue;
  ctx.textAlign=fraction===0?'left':fraction===1?'right':'center';
  ctx.fillText(new Date(row.time*1000).toISOString().slice(0,10),48+fraction*(b.width-70),b.height-7);
 }
 ctx.textAlign='left';
}
addEventListener('resize',draw);
request('/api/backtest').then(data=>$('#snapshots').innerHTML=data.snapshots.length?data.snapshots.map(s=>'<details><summary>'+esc(s.file)+'</summary>'+esc(s.result.source||'')+' · '+esc(s.result.walkForward?.status||'')+'<br>生成 '+esc(s.result.generatedAt||'')+'</details>').join(''):'尚無離線研究快照').catch(e=>$('#snapshots').textContent=e.message);
