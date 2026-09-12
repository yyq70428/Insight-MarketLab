const champion = (session, agent) => session?.runs?.[agent]?.find(run => run.role === 'champion');

export function executionOverlay(session, batch = null, chartAnchorTime = null) {
  const technical = champion(session, 'technical')?.report;
  const execution = champion(session, 'execution');
  const report = execution?.report;
  const decision = report?.decision || execution?.decision || session?.decision;
  if (!session || !technical || !decision) return null;
  const target = report?.target ?? (decision.action === 'SELL' ? technical.downside : technical.expectedSell);
  const stop = report?.stop ?? (decision.action === 'SELL' ? technical.expectedSell : technical.downside);
  const validation = report?.validation || session.outcome || null;
  // Public Session responses intentionally omit the full candle snapshot. The
  // chart's final, anchor-guarded candle is the authoritative time coordinate.
  const anchorTime = chartAnchorTime ?? session.candleSnapshot?.at(-1)?.time;
  if (![target, stop, anchorTime].every(Number.isFinite)) return null;
  return {
    sessionId: session.id, batchId: batch?.id || session.batchId || null,
    round: batch?.currentSessionId === session.id ? batch.currentRound : null,
    totalRounds: batch?.totalRounds || null, anchor: session.anchor, anchorTime,
    action: decision.action, confidence: decision.confidence, target, stop,
    phase: report ? (validation?.complete ? 'completed' : 'waiting') : 'executing',
    validation, replay: report?.replay || [],
  };
}

export function outcomeLabel(view) {
  if (!view) return '';
  if (view.phase === 'executing') return '決策已凍結，正在紙上驗證';
  if (!view.validation?.complete) return `等待後續 K 線 ${view.validation?.bars || 0}/${view.validation?.requiredBars || 0}`;
  const value = view.validation.netReturnPct;
  if (view.action === 'HOLD') return `${view.validation.success ? '預測成功' : '預測未成功'} · 淨報酬 ${Number(value || 0).toFixed(2)}%`;
  return `${value > 0 ? '獲利' : value < 0 ? '虧損' : '損益兩平'} ${value > 0 ? '+' : ''}${Number(value).toFixed(2)}%`;
}
