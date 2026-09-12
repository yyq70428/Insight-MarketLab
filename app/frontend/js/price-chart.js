import { SupportZones } from './support-zones.js';

const instances = new WeakMap();
const COLORS = {
  bullish: "#18b7a6", bearish: "#ff525c", resistance: "#ff535c",
  support: "#18b7a6", prz: "#e6a13a", text: "#9ca6b9",
};

function ensure(host) {
  let instance = instances.get(host);
  if (instance) {
    instance.chart.resize(host.clientWidth, host.clientHeight);
    instance.extras.forEach(series => instance.chart.removeSeries(series));
    instance.extras = [];
    return instance;
  }
  if (!window.LightweightCharts) throw new Error("本地圖表資產未載入");
  const chart = window.LightweightCharts.createChart(host, {
    width: host.clientWidth, height: host.clientHeight,
    layout: { background: { color: "#0f1521" }, textColor: "#737d91", fontFamily: "Inter, system-ui, sans-serif" },
    grid: { vertLines: { color: "#202839" }, horzLines: { color: "#202839" } },
    crosshair: { mode: 0, vertLine: { color: "#6f7788", style: 2 }, horzLine: { color: "#6f7788", style: 2 } },
    rightPriceScale: { borderColor: "#283142", scaleMargins: { top: .08, bottom: .20 } },
    timeScale: { borderColor: "#283142", timeVisible: true, secondsVisible: false, rightOffset: 3, barSpacing: 5 },
    handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true },
    handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true },
  });
  const candles = chart.addCandlestickSeries({
    upColor: "#17b7a4", downColor: "#ef4d58", borderVisible: false,
    wickUpColor: "#17b7a4", wickDownColor: "#ef4d58", priceLineColor: "#8a93a4",
  });
  const volume = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "", lastValueVisible: false, priceLineVisible: false });
  volume.priceScale().applyOptions({ scaleMargins: { top: .82, bottom: 0 } });
  const zones = new SupportZones();
  candles.attachPrimitive(zones);
  const observer=new ResizeObserver(() => chart.resize(host.clientWidth, host.clientHeight));
  instance = { chart, candles, volume, zones, extras: [], observer };
  instances.set(host, instance);
  observer.observe(host);
  return instance;
}

function line(instance, data, options = {}) {
  if (data.length < 2 || data.some(point => !Number.isFinite(point.value))) return null;
  const series = instance.chart.addLineSeries({
    color: options.color || COLORS.text, lineWidth: options.width || 1, lineStyle: options.style || 0,
    lineType: options.lineType || 0, priceLineVisible: false, crosshairMarkerVisible: false,
    lastValueVisible: false,
  });
  series.setData(data);
  if (options.label) series.setMarkers([{time: data.at(-1).time, position: 'inBar',
    color: options.color || COLORS.text, shape: 'circle', size: 0, text: options.label}]);
  instance.extras.push(series); return series;
}

function rgba(hex, alpha) {
  const value = hex.replace("#", "");
  const number = Number.parseInt(value, 16);
  return `rgba(${number >> 16},${(number >> 8) & 255},${number & 255},${alpha})`;
}

function ratioLabel(pattern, pointLabel) {
  const keys = {B:"ab_xa", C:"bc_ab", D:pattern.name === "Cypher" ? "cd_xc" : "ad_xa"};
  const value = pattern.ratios?.[keys[pointLabel]];
  return Number.isFinite(value) ? ` ${value.toFixed(3)}` : "";
}

function drawPattern(instance, rows, pattern) {
  const color = pattern.direction === "bullish" ? COLORS.bullish : COLORS.bearish;
  const points = pattern.points.map(point => ({time:point.time,value:point.price}));
  const series = line(instance, points, {color:rgba(color,.92),width:2});
  if (!series) return;
  const direction = pattern.direction === "bullish" ? "看漲" : "看跌";
  series.setMarkers(pattern.points.map((point, index) => ({
    time: point.time,
    position: point.kind === "high" ? "aboveBar" : "belowBar",
    color,
    shape: index === pattern.points.length - 1 ? (pattern.direction === "bullish" ? "arrowUp" : "arrowDown") : "circle",
    text: index === pattern.points.length - 1
      ? `${point.label}${ratioLabel(pattern, point.label)} · ${direction} ${pattern.name} ${Math.round(pattern.score)}`
      : `${point.label}${ratioLabel(pattern, point.label)}`,
  })));

  const d = pattern.points.at(-1), c = pattern.points.at(-2);
  const lastStep = Math.max(86400, rows.at(-1).time - rows.at(-2).time);
  const end = Math.max(d.time + lastStep * 10, c.time + lastStep);
  line(instance, [{time:d.time,value:pattern.prz.low},{time:end,value:pattern.prz.low}], {color:COLORS.prz,width:1,style:2});
  line(instance, [{time:d.time,value:pattern.prz.high},{time:end,value:pattern.prz.high}], {color:COLORS.prz,width:1,style:2,label:"PRZ"});
  pattern.targets?.slice(0,2).forEach((target, index) => line(instance,
    [{time:d.time,value:target},{time:end,value:target}], {color:rgba(color,index ? .42 : .65),width:1,style:2,label:`T${index+1}`}));
}

function drawExecution(instance, rows, view) {
  if (!view || !rows.length) return;
  const anchorIndex=rows.findIndex(row=>row.time===view.anchorTime);
  const anchor=anchorIndex>=0?rows[anchorIndex]:rows.findLast(row=>row.time<=view.anchorTime);
  if (!anchor) return;
  const step=rows.length>1?Math.max(1,rows.at(-1).time-rows.at(-2).time):86400;
  const lastTime=Math.max(rows.at(-1).time,anchor.time+step*Math.max(3,view.validation?.bars||3));
  const action={BUY:'買進',SELL:'賣出',HOLD:'觀望'}[view.action]||view.action;
  if (view.action!=='HOLD') {
    line(instance,[{time:anchor.time,value:view.target},{time:lastTime,value:view.target}],{color:COLORS.bullish,width:1,style:2,label:`目標 ${view.target.toLocaleString('zh-TW')}`});
    line(instance,[{time:anchor.time,value:view.stop},{time:lastTime,value:view.stop}],{color:COLORS.bearish,width:1,style:2,label:`停損 ${view.stop.toLocaleString('zh-TW')}`});
  }
  const markers=[{time:anchor.time,position:view.action==='SELL'?'aboveBar':'belowBar',color:'#4388ff',
    shape:view.action==='SELL'?'arrowDown':view.action==='BUY'?'arrowUp':'circle',text:`${view.anchor} ${action}決策`}];
  const validation=view.validation;
  if (validation?.entryTime && validation.entryTime<=rows.at(-1).time) markers.push({time:validation.entryTime,
    position:view.action==='SELL'?'aboveBar':'belowBar',color:'#79a5ff',shape:'circle',text:`進場 ${validation.entry?.toLocaleString('zh-TW')}`});
  if (validation?.complete&&validation.exitTime<=rows.at(-1).time) markers.push({time:validation.exitTime,
    position:view.action==='SELL'?'belowBar':'aboveBar',color:validation.netReturnPct>0?COLORS.bullish:COLORS.bearish,
    shape:view.action==='SELL'?'arrowUp':'arrowDown',text:`${validation.netReturnPct>0?'+':''}${validation.netReturnPct.toFixed(2)}% · ${validation.exitReason||validation.reason}`});
  markers.sort((a,b)=>a.time-b.time);
  instance.candles.setMarkers(markers);
}

export function drawPrice(host, rows, analysis = {}, flags = {}, execution = null) {
  if (!rows?.length) return;
  if (rows.some((row,i)=>!Number.isFinite(row.time)||(i>0&&row.time<=rows[i-1].time)))
    throw new Error('圖表行情時間必須遞增且不可重複');
  const existing = instances.get(host);
  const visibleRange = existing?.rows === rows ? existing.chart.timeScale().getVisibleRange() : null;
  const instance = ensure(host);
  instance.candles.setMarkers([]);
  instance.candles.setData(rows.map(({time,open,high,low,close}) => ({time,open,high,low,close})));
  instance.volume.setData(rows.map(row => ({time:row.time,value:row.volume,color:row.close>=row.open?"#123d3db8":"#42252eb8"})));
  const visibleStart = rows[Math.max(0, rows.length - 260)].time;
  if (flags.zigzag && analysis.pivots?.length) {
    line(instance, analysis.pivots.filter(point => point.time >= visibleStart).map(point => ({time:point.time,value:point.price})),
      {color:"#78859d",width:1,style:2});
  }
  instance.zones.setZones(flags.zones ? [...(analysis.zones || []), ...(analysis.historicalZones || [])] : [], rows);
  host.title = flags.zones
    ? '支撐壓力隨平移、縮放顯示最多 8 區；淡框為歷史區間，類型依視窗末價。歷史區間由各段 K 線回看整理，起點不是當時已確認的交易訊號。'
    : '';
  const historyNote = host.parentElement.querySelector('#zoneHistoryNote');
  if (historyNote) historyNote.hidden = !(flags.zones && analysis.historicalZones?.length);
  if (flags.harmonics) analysis.harmonics?.filter(pattern => pattern.points.at(-1).time >= visibleStart).slice(0,3)
    .forEach(pattern => drawPattern(instance, rows, pattern));
  drawExecution(instance,rows,execution);
  // Preserve the user's zoom when switching overlays or resizing the sidebar.
  instance.chart.timeScale().setVisibleRange(visibleRange || {from: visibleStart, to: rows.at(-1).time});
  instance.rows = rows;
}

export function drawReplayMarkers(host, report, until) {
  const instance=instances.get(host),v=report.validation,action=report.decision.action;
  if(!instance||!v.entryTime)return;
  const markers=[{time:v.entryTime,position:'belowBar',color:'#4388ff',shape:'arrowUp',text:`${action} 驗證起點`}];
  if(v.complete&&v.exitTime<=until)markers.push({time:v.exitTime,position:'aboveBar',color:v.success?'#18b7a6':'#ff525c',shape:'arrowDown',text:`${v.reason} ${v.netReturnPct}%`});
  instance.candles.setMarkers(markers.filter(m=>m.time<=until));
}
