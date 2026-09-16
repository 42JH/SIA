import styles from './DashboardHome.module.css';

const colors = ['#f5f8ff', '#88a6d0', '#31ddf2'];

export function LineChart({ buckets, series }) {
  const width = 1000; const height = 300; const left = 56; const top = 24; const bottom = 42;
  const innerW = width - left - 20; const innerH = height - top - bottom;
  const x = (i) => left + (buckets.length < 2 ? innerW / 2 : i * innerW / (buckets.length - 1));
  const y = (v) => top + (1 - v) * innerH;
  return <svg className={styles.chart} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="인식 정확도 추이">
    {[0, .25, .5, .75, 1].map((v) => <g key={v}><line x1={left} x2={width - 20} y1={y(v)} y2={y(v)} /><text x="8" y={y(v) + 4}>{Math.round(v * 100)}%</text></g>)}
    {buckets.map((bucket, i) => <line key={`grid-${bucket.key}`} x1={x(i)} x2={x(i)} y1={top} y2={height - bottom} />)}
    {series.map((item, s) => {
      const segments = []; let current = [];
      buckets.forEach((bucket, i) => { const value = bucket[item.key]; if (value == null) { if (current.length) segments.push(current); current = []; } else current.push(`${x(i)},${y(value)}`); });
      if (current.length) segments.push(current);
      return <g key={item.key}>{segments.map((points, i) => <polyline key={i} points={points.join(' ')} fill="none" stroke={colors[s]} strokeWidth="3" strokeDasharray={s === 1 ? '8 6' : s === 2 ? '2 5' : undefined} />)}{buckets.map((bucket, i) => bucket[item.key] == null ? null : <circle key={bucket.key} cx={x(i)} cy={y(bucket[item.key])} r="4" fill={s === 0 ? colors[s] : '#102d57'} stroke={colors[s]} strokeWidth="2" />)}</g>;
    })}
    {buckets.map((bucket, i) => <text key={bucket.key} x={x(i)} y={height - 12} textAnchor="middle">{bucket.label}</text>)}
  </svg>;
}

export function BarChart({ buckets, series, lineKey = null, minimumMax = 1, valueFormatter = (v) => v }) {
  const values = buckets.flatMap((bucket) => [...series.map((seriesItem) => bucket[seriesItem.key]), lineKey ? bucket[lineKey] : null].filter((value) => value != null));
  const max = Math.max(minimumMax, ...values); const width = 1000; const height = 300; const left = 54; const top = 26; const bottom = 44; const innerH = height - top - bottom;
  const groupW = (width - left - 20) / Math.max(buckets.length, 1); const barW = Math.min(54, groupW / (series.length + .8));
  const center = (i) => left + i * groupW + groupW / 2;
  const y = (value) => top + innerH - value / max * innerH;
  const linePoints = lineKey ? buckets.map((bucket, index) => Number.isFinite(bucket[lineKey]) ? `${center(index)},${y(bucket[lineKey])}` : null).filter(Boolean).join(' ') : '';
  return <svg className={styles.chart} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="기간별 막대그래프">
    {[0, .25, .5, .75, 1].map((ratio) => { const value = max * ratio; const yy = top + (1 - ratio) * innerH; return <g key={ratio}><line x1={left} x2={width - 20} y1={yy} y2={yy} /><text x="8" y={yy + 4}>{valueFormatter(value)}</text></g>; })}
    {buckets.map((bucket, i) => <g key={bucket.key}>{series.map((item, s) => { const value = bucket[item.key]; if (value == null) return null; const h = value / max * innerH; const xx = left + i * groupW + (groupW - barW * series.length) / 2 + s * barW; return <rect key={item.key} x={xx} y={top + innerH - h} width={barW - 5} height={h} fill={colors[s]} />; })}<text x={center(i)} y={height - 12} textAnchor="middle">{bucket.label}</text></g>)}
    {linePoints && <><polyline points={linePoints} fill="none" stroke={colors[2]} strokeWidth="2.5" strokeDasharray="5 5" />{buckets.map((bucket, index) => Number.isFinite(bucket[lineKey]) ? <circle key={bucket.key} cx={center(index)} cy={y(bucket[lineKey])} r="4" fill="#fff" stroke={colors[2]} strokeWidth="2" /> : null)}</>}
  </svg>;
}

export function HorizontalBars({ items }) {
  const max = Math.max(1, ...items.map((item) => item.count));
  return <div className={styles.horizontalBars}>{items.slice(0, 5).map((item, index) => <div className={styles.horizontalRow} key={item.appKey ?? item.displayName}><b>{index + 1}</b><span>{item.displayName}</span><div><i style={{ width: `${item.count / max * 100}%` }} /></div><strong>{item.count}회</strong></div>)}</div>;
}
