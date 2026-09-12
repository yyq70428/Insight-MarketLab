const stageLabels = {
  waiting: '等待執行', creating_session: '建立輪次', first_layer: '第一層分析',
  technical: '第一層技術', news: '第一層新聞', execution: '第二層決策',
  adaptive: '第三層審核', waiting_data: '等待行情', completed: '完成',
};

export function batchOutcome(round) {
  if (!round) return '';
  if (!round.completed) return '執行中';
  const validation = round.validation || {};
  if (!validation.complete) return '等待後續 K 線';
  if (round.action === 'HOLD') return validation.success ? '預測成功' : '預測未成功';
  const value = Number(validation.netReturnPct);
  if (!Number.isFinite(value)) return '驗證完成';
  return `${value > 0 ? '獲利' : value < 0 ? '虧損' : '損益兩平'} ${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
}

export function batchNodes(batch) {
  const rounds = new Map((batch.rounds || []).map(round => [round.anchor, round]));
  return (batch.anchors || []).map((anchor, index) => {
    const round = rounds.get(anchor);
    const current = batch.currentAnchor === anchor && ['queued', 'running'].includes(batch.status);
    const sessionId = round?.sessionId || (current ? batch.currentSessionId : null);
    let state = 'pending', detail = '待執行';
    if (round) {
      state = round.completed ? (round.validation?.complete ? (round.validation?.success ? 'success' : 'loss') : 'waiting') : 'running';
      detail = batchOutcome(round);
    } else if (current) {
      state = 'running'; detail = stageLabels[batch.currentStage] || batch.currentStage || '執行中';
    } else if (batch.status === 'failed' && index === Number(batch.completedRounds || 0)) {
      state = 'failed'; detail = '執行失敗';
    } else if (batch.status === 'interrupted' && index === Number(batch.completedRounds || 0)) {
      state = 'failed'; detail = '執行中斷';
    }
    return {anchor, index: index + 1, state, detail, sessionId, action: round?.action || (current ? '…' : '—'), confidence: round?.confidence};
  });
}

export function batchStatusLabel(status) {
  return ({queued:'排隊中',running:'執行中',completed:'完成',waiting_validation:'等待驗證',failed:'失敗',interrupted:'已中斷'})[status] || status || '—';
}
