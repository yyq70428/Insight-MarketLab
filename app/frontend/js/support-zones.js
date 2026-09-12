// Presentation only: keep the complete backend zone list for Agent analysis.
export function primaryZones(zones, price) {
  return ['support', 'resistance'].flatMap(type => {
    const ranked = zones.filter(zone => zone.type === type &&
      [zone.low, zone.high, zone.midpoint, zone.startTime].every(Number.isFinite))
      .sort((a, b) => Math.abs(a.midpoint - price) - Math.abs(b.midpoint - price) || b.strength - a.strength);
    const selected = [];
    for (const zone of ranked) {
      if (selected.some(other => zone.low <= other.high && zone.high >= other.low)) continue;
      selected.push(zone);
      if (selected.length === 2) break;
    }
    return selected;
  });
}

// Coordinates are supplied by the chart, so the budget follows the visible
// price/time range, not the latest quote. Exported for deterministic QA.
export function visibleZones(projected, { width, height, price, limit = 8 }) {
  const candidates = projected.filter(item =>
    [item.high, item.low, item.mid, item.start].every(Number.isFinite) &&
    item.start < width - 10 && item.mid >= 12 && item.mid <= height - 12);
  const selected = [];
  const separated = item => !selected.some(other =>
    Math.abs(item.mid - other.mid) < 30 ||
    (item.zone.low <= other.zone.high && item.zone.high >= other.zone.low));
  const add = item => { if (selected.length < limit && separated(item)) selected.push(item); };
  // Reserve up to four current zones; use the remaining room for older levels.
  for (const zone of primaryZones(candidates.filter(item => !item.zone.historical).map(item => item.zone), price)) {
    add(candidates.find(item => item.zone === zone));
  }
  while (selected.length < limit) {
    const remaining = candidates.filter(item => !selected.includes(item) && separated(item));
    if (!remaining.length) break;
    // Farthest-point sampling retains older price regions when zoomed out.
    // Strength and recent confirmations resolve ties within the same region.
    const priority = item => {
      const spacing = selected.length ? Math.min(...selected.map(other => Math.abs(item.mid - other.mid))) : height / 2;
      return spacing + Math.min(100, item.zone.strength || 0) * .15 + (item.last >= 0 ? 10 : 0);
    };
    remaining.sort((a, b) => priority(b) - priority(a) || (b.zone.asOfTime || 0) - (a.zone.asOfTime || 0));
    add(remaining[0]);
  }
  return selected;
}

export class SupportZones {
  constructor() {
    this.zones = [];
    this.rows = [];
    this.view = { zOrder: () => 'top', renderer: () => ({ draw: target => this.draw(target) }) };
  }

  attached({ chart, series, requestUpdate }) {
    Object.assign(this, { chart, series, requestUpdate });
  }

  detached() {
    this.chart = this.series = this.requestUpdate = null;
  }

  paneViews() { return [this.view]; }

  setZones(zones, rows = []) {
    this.zones = zones;
    this.rows = rows;
    this.requestUpdate?.();
  }

  draw(target) {
    if (!this.chart || !this.series) return;
    target.useMediaCoordinateSpace(({ context: ctx, mediaSize: { width, height } }) => {
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, width, height);
      ctx.clip();
      ctx.font = '11px Inter, system-ui, sans-serif';
      ctx.textBaseline = 'middle';
      const labels = [];
      const scale = this.chart.timeScale(), range = scale.getVisibleRange();
      const lastVisible = range && this.rows.findLast(row => row.time <= range.to);
      const price = lastVisible?.close ?? this.rows.at(-1)?.close;
      const visibleRows = range ? this.rows.filter(row => row.time >= range.from && row.time <= range.to) : [];
      const visibleLow = Math.min(...visibleRows.map(row => row.low ?? row.close));
      const visibleHigh = Math.max(...visibleRows.map(row => row.high ?? row.close));
      const margin = Math.max((visibleHigh - visibleLow) * .03, Math.abs(price || 0) * .003);
      const projected = this.zones.filter(zone =>
        [zone.low, zone.high, zone.midpoint, zone.startTime].every(Number.isFinite) &&
        zone.low < zone.high && zone.midpoint >= zone.low && zone.midpoint <= zone.high &&
        zone.high >= visibleLow - margin && zone.low <= visibleHigh + margin &&
        range && (zone.asOfTime || this.rows.at(-1)?.time) <= range.to
      ).map(zone => ({
        zone: { ...zone, type: zone.midpoint < price ? 'support' : 'resistance' },
        high: this.series.priceToCoordinate(zone.high), low: this.series.priceToCoordinate(zone.low),
        mid: this.series.priceToCoordinate(zone.midpoint), start: scale.timeToCoordinate(zone.startTime),
        last: scale.timeToCoordinate(zone.lastTime),
      }));
      const displayed = visibleZones(projected, { width, height, price, limit: Math.min(8, Math.max(2, Math.floor(height / 65))) });
      this.displayed = displayed.map(item => item.zone);
      for (const { zone, high, low, mid, start } of displayed) {
        const top = Math.min(high, low), bottom = Math.max(high, low);
        if (bottom < 0 || top > height || start > width) continue;
        const left = Math.max(0, start), right = width - 6;
        const color = zone.type === 'support' ? '#18b7a6' : '#ff535c';
        // One outline with a faint fill replaces three parallel lines per zone.
        ctx.fillStyle = `${color}${zone.historical ? '06' : '0c'}`;
        ctx.strokeStyle = `${color}${zone.historical ? '50' : '80'}`;
        ctx.lineWidth = 1;
        ctx.fillRect(left, top, right - left, Math.max(1, bottom - top));
        ctx.strokeRect(left + .5, top + .5, right - left, Math.max(1, bottom - top));
        const price = zone.midpoint.toLocaleString('zh-TW', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
        labels.push({ color, mid, text: `${zone.historical ? '歷史' : ''}${zone.type === 'support' ? '支撐' : '壓力'} ${price} · ${zone.touches}次` });
      }
      // Keep nearby price labels separated without moving the actual zone.
      labels.sort((a, b) => a.mid - b.mid);
      let previous = -Infinity;
      labels.forEach(label => { label.y = Math.max(12, label.mid, previous + 24); previous = label.y; });
      for (let i = labels.length - 1; i >= 0; i--) {
        labels[i].y = Math.min(labels[i].y, i === labels.length - 1 ? height - 12 : labels[i + 1].y - 24);
      }
      for (const { color, mid, y, text } of labels) {
        if (y < 10) continue;
        const labelWidth = ctx.measureText(text).width + 16, x = width - labelWidth - 7;
        ctx.strokeStyle = `${color}80`;
        if (Math.abs(y - mid) > 2) {
          ctx.beginPath(); ctx.moveTo(x - 6, mid); ctx.lineTo(x, y); ctx.stroke();
        }
        ctx.fillStyle = '#101923';
        ctx.fillRect(x, y - 10, labelWidth, 20);
        ctx.strokeRect(x + .5, y - 9.5, labelWidth, 20);
        ctx.fillStyle = color;
        ctx.fillText(text, x + 8, y);
      }
      ctx.restore();
    });
  }
}
