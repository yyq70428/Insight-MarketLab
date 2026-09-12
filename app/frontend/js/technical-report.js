import {escapeHtml as esc} from './util.js';

const fixed=(value,digits=2)=>Number.isFinite(value)?value.toFixed(digits):'—';
const percent=(value,digits=2)=>Number.isFinite(value)?`${value>0?'+':''}${fixed(value,digits)}%`:'—';
const names={harmonics:'諧波',supportResistance:'支撐壓力',macd:'MACD',rsi:'RSI'};

export function technicalReportHTML(report) {
  const r=report,m=r.macdContext,t=r.expectedTime||{};
  const recommendation=({'偏多':'買進','偏空':'賣出','中性':'觀望'})[r.recommendation]||r.recommendation||'尚無建議';
  const target=t.afterBars??r.targetBars;
  const date=t.date?`｜約 ${esc(t.date.replaceAll('-','/'))}`:'';
  const down=Number.isFinite(r.downsidePct)?-Math.abs(r.downsidePct):null;
  const macd=m?`MACD ${m.fast}/${m.slow}/${m.signalPeriod}；波形位置 ${fixed(m.positionPct,1)}%；模式 ${esc(m.mode)}。`:
    '此為舊版報告，未記錄 MACD 波形位置；請重新分析建立新輪次。';
  return `<section class="technical-result" aria-label="技術分析完整報告">
    <div class="technical-odds">
      <div><span>看多</span><strong class="bullish">${fixed(r.bullishPct,1)}%</strong></div>
      <div><span>看空</span><strong class="bearish">${fixed(r.bearishPct,1)}%</strong></div>
    </div>
    <h4>建議：${esc(recommendation)}</h4>
    <dl class="technical-prices">
      <dt>預期買入</dt><dd>${fixed(r.expectedBuy)}</dd>
      <dt>預期賣出</dt><dd>${fixed(r.expectedSell)}</dd>
      <dt>預期上漲</dt><dd>${percent(r.upsidePct)}</dd>
      <dt>預期下跌</dt><dd>${percent(down)}</dd>
    </dl>
    <div class="technical-target">目標時間 約 ${esc(target??'—')} ${esc(t.unit||'根 K 線')}${date}</div>
    <ul class="technical-components">${Object.entries(names).map(([key,label])=>{
      const component=r.components?.[key];
      return `<li>${label} ${Number.isFinite(component?.score)?Math.round(component.score):'—'}分｜${esc(component?.reason||'尚無分析內容')}</li>`;
    }).join('')}</ul>
    <aside class="technical-macd">${macd}${m?`<br>${esc(m.riskNote)}<small>最近 ${m.positionSamples} 根有效 MACD（設定 ${m.positionLookback} 根）之高低區間位置。${esc(m.interpretation)}；基礎 ${fixed(m.baseScore,1)} → 採用 ${fixed(m.score,1)} 分。</small>`:''}</aside>
    <p class="technical-caveat">${esc(r.disclaimer||'方向比例是規則加權分數，不是上漲機率或勝率。所有指標與判斷只使用時間錨定點當日及以前的 K 線資料。')}</p>
    <details class="technical-assumptions"><summary>價格與時間估算依據</summary><p>${esc(r.priceBasis||'舊報告漲跌幅以錨點參考價計算，保留原始值。')}</p><p>下檔參考價 ${fixed(r.downside)}。${esc(t.basis||'目標根數不是保證達標時間。')}</p></details>
  </section>`;
}
