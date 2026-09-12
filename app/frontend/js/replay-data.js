export function replayRows(anchorRows, futureRows, count) {
  if (!anchorRows?.length) throw new Error('錨點行情尚未載入，不能開始回放');
  for (const rows of [anchorRows, futureRows]) {
    if (!rows || rows.some((r,i)=>!Number.isFinite(r.time)||(i>0&&r.time<=rows[i-1].time)))
      throw new Error('回放資料時間必須遞增且不可重複');
  }
  if (futureRows.length && futureRows[0].time <= anchorRows.at(-1).time)
    throw new Error('回放資料與錨點重疊，請等待正確的錨點行情載入');
  return [...anchorRows,...futureRows.slice(0,Math.max(0,count))];
}
