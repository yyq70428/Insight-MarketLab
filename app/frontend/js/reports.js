import {query, request} from './api.js';
import {escapeHtml as esc, showToast} from './util.js';

const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const GROUPS = [
  {key: 'tw-large', title: '台股 · 大型權值', match: r => r.market === '台股' && r.index < 50},
  {key: 'tw-small', title: '台股 · 中小潛力', match: r => r.market === '台股' && r.index >= 50},
  {key: 'us', title: '美股 · 大型股', match: r => r.market === '美股'},
];
const STORAGE_KEY = 'marketlab.reportSelection';
let universe = [], selected = new Set(), pollTimer = null, openRunId = null;

function saveSelection() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify([...selected])); } catch { /* private mode */ }
}

function renderSelection() {
  const count = selected.size;
  $('#selectionLabel').textContent = count ? `已選取 ${count} 檔` : '未選取任何標的';
  $('#selectionHint').textContent = count
    ? `執行時只會跑這 ${count} 檔，每檔約 20 秒。`
    : '直接執行就是系統預設：固定清單全部 70 檔。';
  $('#runNow').textContent = count ? `執行選取的 ${count} 檔` : '執行預設 70 檔';
  $$('.symbol-chip').forEach(chip => chip.classList.toggle('picked', selected.has(chip.dataset.symbol)));
  GROUPS.forEach(group => {
    const rows = universe.filter(group.match);
    const picked = rows.filter(r => selected.has(r.symbol)).length;
    const badge = document.querySelector(`[data-count="${group.key}"]`);
    if (badge) badge.textContent = `${picked}/${rows.length}`;
  });
  const minutes = Math.max(1, Math.round((count || universe.length) * 21 / 60));
  $('#runHint').textContent = `預估耗時約 ${minutes} 分鐘，每檔含一次 LLM 呼叫。`;
}

function renderGroups() {
  $('#groups').innerHTML = GROUPS.map(group => {
    const rows = universe.filter(group.match);
    const chips = rows.map(row =>
      `<button type="button" class="symbol-chip" data-symbol="${esc(row.symbol)}" title="${esc(row.sector)}">
         ${esc(row.symbol)}<span>${esc(row.name)}</span></button>`).join('');
    return `<section class="symbol-group">
      <header><h3>${esc(group.title)}</h3>
        <span class="group-count" data-count="${group.key}">0/${rows.length}</span>
        <button type="button" class="link-button" data-group="${group.key}">切換整組</button></header>
      <div class="chips">${chips}</div></section>`;
  }).join('');
  $$('.symbol-chip').forEach(chip => chip.onclick = () => {
    const symbol = chip.dataset.symbol;
    selected.has(symbol) ? selected.delete(symbol) : selected.add(symbol);
    saveSelection(); renderSelection();
  });
  $$('[data-group]').forEach(button => button.onclick = () => {
    const group = GROUPS.find(g => g.key === button.dataset.group);
    const rows = universe.filter(group.match);
    const allPicked = rows.every(r => selected.has(r.symbol));
    rows.forEach(r => allPicked ? selected.delete(r.symbol) : selected.add(r.symbol));
    saveSelection(); renderSelection();
  });
  renderSelection();
}

function describeDelivery(delivery) {
  if (!delivery) return '—';
  if (delivery.sent) return `已寄出 · ${(delivery.recipients || []).join(', ')}`;
  return delivery.reason || '未寄出';
}

function renderHistory(data) {
  $('#historyNote').textContent = data.persistent
    ? '紀錄存在 MongoDB，重啟後仍在。'
    : '目前沒有 MongoDB，紀錄只留在記憶體，重啟後會消失。';
  if (!data.runs.length) { $('#history').innerHTML = '<p class="muted">尚無執行紀錄。</p>'; return; }
  const rows = data.runs.map(run => {
    const stats = run.stats || {};
    const scope = run.requestedSymbols ? `自選 ${run.requestedSymbols.length} 檔` : `預設 ${run.total} 檔`;
    const state = run.status === 'running' ? '<span class="tag running">執行中</span>'
      : run.status === 'failed' ? '<span class="tag failed">失敗</span>'
      : '<span class="tag done">完成</span>';
    const signal = run.status === 'completed'
      ? `<span class="up">${stats.bullish ?? 0}</span> / <span class="down">${stats.bearish ?? 0}</span> / <span class="warn">${stats.conflicts ?? 0}</span>`
      : esc(run.error || '—');
    return `<tr>
      <td>${esc((run.startedAt || '').replace('T', ' ').slice(0, 16))}</td>
      <td>${state}${run.trigger === 'schedule' ? '<small>排程</small>' : '<small>手動</small>'}</td>
      <td>${esc(scope)}</td>
      <td class="signal">${signal}</td>
      <td>${run.elapsedSeconds == null ? '—' : Math.round(run.elapsedSeconds) + ' 秒'}</td>
      <td class="delivery">${esc(describeDelivery(run.delivery))}</td>
      <td>${run.status === 'completed'
        ? `<button type="button" class="link-button" data-run="${esc(run.id)}">查看報告</button>` : ''}</td>
    </tr>`;
  }).join('');
  $('#history').innerHTML = `<table class="history-table">
    <thead><tr><th>開始時間</th><th>狀態</th><th>範圍</th><th>偏多/偏空/衝突</th><th>耗時</th><th>寄送</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table>`;
  $$('[data-run]').forEach(button => button.onclick = () => openDetail(button.dataset.run));
}

async function loadHistory() {
  try { renderHistory(await query('/api/daily-report/history', {limit: 30})); }
  catch (error) { $('#history').innerHTML = `<p class="muted">${esc(error.message)}</p>`; }
}

async function openDetail(runId) {
  openRunId = runId;
  try {
    const record = await request(`/api/daily-report/history/${runId}`);
    const stats = record.stats || {};
    $('#detailTitle').textContent = `${record.reportDate || '報告'} · ${record.total} 檔`;
    $('#detailMeta').textContent =
      `技術面成功 ${stats.technicalOk ?? 0}／${record.total}　·　新聞面有效證據 ${stats.newsWithEvidence ?? 0}`
      + `　·　方向衝突 ${stats.conflicts ?? 0}　·　寄送：${describeDelivery(record.delivery)}`;
    // Sandboxed iframe: the report is a light-themed document and carries model-written text.
    $('#detailFrame').src = `/api/daily-report/history/${runId}/preview`;
    $('#detailPanel').classList.remove('hidden');
    $('#detailPanel').scrollIntoView({behavior: 'smooth', block: 'start'});
  } catch (error) { showToast(error.message); }
}

function renderProgress(status) {
  const box = $('#progress');
  if (!status.running) { box.classList.add('hidden'); return; }
  box.classList.remove('hidden');
  const progress = status.progress || {completed: 0, total: 0};
  const percent = progress.total ? Math.round(progress.completed / progress.total * 100) : 0;
  $('#progressBar').value = percent;
  $('#progressText').textContent =
    `${progress.completed}/${progress.total} 完成（${percent}%）${progress.symbol ? ' · 最近：' + progress.symbol : ''}`;
}

async function poll() {
  clearTimeout(pollTimer);
  let status;
  try { status = await request('/api/daily-report/status'); }
  catch { pollTimer = setTimeout(poll, 8000); return; }
  renderProgress(status);
  $('#runNow').disabled = status.running;
  if (status.running) { pollTimer = setTimeout(poll, 3000); return; }
  await loadHistory();
  if (status.lastError) showToast(status.lastError);
}

async function loadSchedule() {
  try {
    const status = await request('/api/daily-report/status');
    const missing = status.mailMissing || [];
    $('#scheduleNote').innerHTML = (status.enabled
      ? `排程已啟用 · 每日 ${esc(status.scheduledAt)}（${esc(status.timezone)}）${status.weekdaysOnly ? ' · 僅平日' : ''}`
      : '排程未啟用（DAILY_REPORT_ENABLED=false），可在此手動執行')
      + (missing.length ? `<br><span class="warn">郵件設定不完整，缺少 ${esc(missing.join('、'))}，執行後不會寄出。</span>` : '');
    renderProgress(status);
    $('#runNow').disabled = status.running;
    if (status.running) poll();
  } catch (error) { $('#scheduleNote').textContent = error.message; }
}

$('#selectAll').onclick = () => { universe.forEach(r => selected.add(r.symbol)); saveSelection(); renderSelection(); };
$('#selectNone').onclick = () => { selected.clear(); saveSelection(); renderSelection(); };
$('#closeDetail').onclick = () => { $('#detailPanel').classList.add('hidden'); $('#detailFrame').src = 'about:blank'; openRunId = null; };

$('#runNow').onclick = async () => {
  const symbols = [...selected];
  const scope = symbols.length ? `選取的 ${symbols.length} 檔` : `預設全部 ${universe.length} 檔`;
  const minutes = Math.max(1, Math.round((symbols.length || universe.length) * 21 / 60));
  if (!confirm(`將執行 ${scope}，預估約 ${minutes} 分鐘，每檔會呼叫一次 LLM。確定開始？`)) return;
  $('#runNow').disabled = true;
  try {
    // An empty list means "use the server default", so send null rather than [].
    const body = {symbols: symbols.length ? symbols : null, notify: $('#notify').checked};
    const result = await request('/api/daily-report/run', {method: 'POST', body: JSON.stringify(body)});
    showToast(`已開始執行 ${result.total} 檔${result.usedDefault ? '（系統預設）' : ''}`);
    poll();
  } catch (error) { showToast(error.message); $('#runNow').disabled = false; }
};

(async function start() {
  try {
    const data = await query('/api/daily-report/universe');
    universe = data.symbols.map((row, index) => ({...row, index}));
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
      // Drop anything that has since left the fixed universe.
      selected = new Set(saved.filter(symbol => universe.some(row => row.symbol === symbol)));
    } catch { selected = new Set(); }
    renderGroups();
  } catch (error) { $('#groups').innerHTML = `<p class="muted">${esc(error.message)}</p>`; }
  await loadSchedule();
  await loadHistory();
})();
