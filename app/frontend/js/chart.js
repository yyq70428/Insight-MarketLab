const COLORS = {grid:"#202839",text:"#737d91",blue:"#3474ff",purple:"#b49adc",orange:"#f0a43a",up:"#15978c",down:"#9e3842"};

function surface(canvas) {
  const ratio=devicePixelRatio||1, box=canvas.getBoundingClientRect();
  canvas.width=Math.max(1,Math.round(box.width*ratio)); canvas.height=Math.max(1,Math.round(box.height*ratio));
  const ctx=canvas.getContext("2d"); ctx.setTransform(ratio,0,0,ratio,0,0); ctx.clearRect(0,0,box.width,box.height);
  return {ctx,width:box.width,height:box.height};
}

function format(value) {
  if (Math.abs(value)>=100) return value.toFixed(0);
  if (Math.abs(value)>=10) return value.toFixed(1);
  return value.toFixed(2);
}

export function drawLine(canvas, values, key, color=COLORS.purple, bounds=null) {
  if (!values?.length) return;
  const {ctx,width,height}=surface(canvas), pad={left:43,right:55,top:28,bottom:13};
  const view=values.slice(-260), raw=view.map(row=>Number(row[key])).filter(Number.isFinite);
  if (!raw.length) return;
  let min=bounds?.[0]??Math.min(...raw), max=bounds?.[1]??Math.max(...raw);
  if (key==="macd") {
    const signal=view.map(row=>Number(row.signal)).filter(Number.isFinite);
    const histogram=view.map(row=>Number(row.histogram)).filter(Number.isFinite);
    const magnitude=Math.max(...raw.map(Math.abs),...signal.map(Math.abs),...histogram.map(Math.abs),.001);
    min=-magnitude*1.12; max=magnitude*1.12;
  }
  const span=max-min||1, plotWidth=width-pad.left-pad.right, plotHeight=height-pad.top-pad.bottom;
  const x=index=>pad.left+index*plotWidth/Math.max(1,view.length-1);
  const y=value=>pad.top+(max-value)/span*plotHeight;
  ctx.font="11px Inter, system-ui, sans-serif"; ctx.textAlign="left"; ctx.textBaseline="middle";
  const gridValues=bounds?[0,30,50,70,100]:[min,0,max];
  [...new Set(gridValues)].forEach(value=>{
    const yy=y(value); ctx.strokeStyle=value===0?"#50596b":COLORS.grid; ctx.lineWidth=1;
    ctx.setLineDash(bounds&&[30,70].includes(value)?[6,6]:[]); ctx.beginPath();ctx.moveTo(pad.left,yy);ctx.lineTo(width-pad.right,yy);ctx.stroke();ctx.setLineDash([]);
    if ((bounds&&[0,30,70,100].includes(value))||(!bounds)) {ctx.fillStyle=COLORS.text;ctx.fillText(format(value),width-pad.right+7,yy)}
  });
  if (key==="macd") {
    const zero=y(0), barWidth=Math.max(1,plotWidth/view.length*.72);
    view.forEach((row,index)=>{const value=Number(row.histogram);if(!Number.isFinite(value))return;ctx.fillStyle=value>=0?COLORS.up:COLORS.down;const yy=y(value);ctx.fillRect(x(index)-barWidth/2,Math.min(zero,yy),barWidth,Math.max(1,Math.abs(yy-zero)))});
  }
  const draw=(field,stroke,widthPx=2)=>{ctx.strokeStyle=stroke;ctx.lineWidth=widthPx;ctx.lineJoin="round";ctx.lineCap="round";ctx.beginPath();let started=false;view.forEach((row,index)=>{const value=Number(row[field]);if(!Number.isFinite(value))return;started?ctx.lineTo(x(index),y(value)):ctx.moveTo(x(index),y(value));started=true});ctx.stroke()};
  draw(key,color,2);
  if (key==="macd") draw("signal",COLORS.orange,1.8);
  const latest=Number(view.at(-1)[key]);
  if(Number.isFinite(latest)){const yy=y(latest);ctx.fillStyle=color;ctx.fillRect(width-pad.right,yy-9,pad.right,18);ctx.fillStyle="#111722";ctx.font="bold 11px Inter, system-ui, sans-serif";ctx.fillText(format(latest),width-pad.right+6,yy)}
}
