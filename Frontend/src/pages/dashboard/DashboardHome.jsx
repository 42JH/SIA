import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { fetchDashboardAccuracy, fetchDashboardApps, fetchDashboardLatency, fetchDashboardOverview, fetchDashboardUsage } from '../../api/dashboard';
import { BarChart, HorizontalBars, LineChart } from './DashboardChart';
import GesturePanel from './GesturePanel';
import SettingsPanel from './SettingsPanel';
import VoicePanel from './VoicePanel';
import GazePanel from './GazePanel';
import { useGestureStore } from '../../store/gestureStore';
import siaLogo from '../../assets/sia-logo.png';
import styles from './DashboardHome.module.css';

const periods = [{ key: 'day', label: '1일' }, { key: 'week', label: '7일' }, { key: 'month', label: '한달' }, { key: 'year', label: '1년' }];
const details = {
  accuracy: ['인식 정확도', 'AI가 세상을 이해하는 정확도를 한눈에 확인하세요.', fetchDashboardAccuracy],
  latency: ['평균 응답 시간', '작업 유형별 평균 응답 시간을 확인할 수 있습니다.', fetchDashboardLatency],
  usage: ['제스처 / 보이스 사용량', '시간대별 사용 흐름과 입력 방식의 비중을 확인할 수 있습니다.', fetchDashboardUsage],
  apps: ['자주 사용하는 프로그램', '프로그램별 실행 빈도와 사용 흐름을 한눈에 확인할 수 있습니다.', fetchDashboardApps],
};
const views = ['home', 'settings', 'voice', 'gestures', 'gaze', ...Object.keys(details)];
const percent = (value) => value == null ? '데이터 없음' : `${Math.round(value * 100)}%`;
const seconds = (value) => value == null ? '데이터 없음' : `${(value / 1000).toFixed(1)}초`;
const weekLabels = ['월', '화', '수', '목', '금', '토', '일'];

function parseBucketDate(bucket) {
  const key = String(bucket.key ?? '');
  const match = key.match(/(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})/);
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isNaN(date.getTime()) ? null : date;
}

function calendarBuckets(buckets, period) {
  if (!Array.isArray(buckets) || !['week', 'year'].includes(period)) return buckets ?? [];
  if (period === 'week') {
    const today = new Date(); const monday = new Date(today); const weekday = (today.getDay() + 6) % 7;
    const hasDatedBuckets = buckets.some((bucket) => parseBucketDate(bucket));
    monday.setHours(0, 0, 0, 0); monday.setDate(today.getDate() - weekday);
    return weekLabels.map((label, index) => {
      const target = new Date(monday); target.setDate(monday.getDate() + index);
      const dated = buckets.find((bucket) => parseBucketDate(bucket)?.getTime() === target.getTime());
      const labeled = hasDatedBuckets ? null : buckets.find((bucket) => String(bucket.label ?? '').replace('요일', '').trim().startsWith(label));
      return { ...(dated ?? labeled ?? {}), key: dated?.key ?? labeled?.key ?? `week-${index}`, label };
    });
  }
  const year = new Date().getFullYear(); let inferredYear = null; let previousMonth = null;
  const indexed = buckets.map((bucket) => {
    const date = parseBucketDate(bucket); const text = String(bucket.label ?? '');
    const explicit = text.match(/(\d{2,4})년\s*(\d{1,2})월/); const monthOnly = text.match(/(\d{1,2})월/);
    const month = date ? date.getMonth() + 1 : Number(explicit?.[2] ?? monthOnly?.[1]);
    if (date) inferredYear = date.getFullYear();
    else if (explicit) inferredYear = Number(explicit[1]) < 100 ? 2000 + Number(explicit[1]) : Number(explicit[1]);
    else if (previousMonth && month < previousMonth) inferredYear = (inferredYear ?? year - 1) + 1;
    previousMonth = month || previousMonth;
    return { bucket, month, year: date?.getFullYear() ?? inferredYear };
  });
  return Array.from({ length: 12 }, (_, index) => {
    const month = index + 1; const match = indexed.find((item) => item.year === year && item.month === month)?.bucket;
    return { ...(match ?? {}), key: match?.key ?? `year-${year}-${month}`, label: month === 1 ? `${String(year).slice(2)}년 1월` : `${month}월` };
  });
}

function averageOf(buckets, key) {
  const values = buckets.map((bucket) => bucket[key]).filter((value) => Number.isFinite(value));
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}

function calendarSummary(kind, buckets, fallback, period) {
  if (kind === 'usage') {
    const available = buckets.filter((bucket) => Number.isFinite(bucket.count)); const total = available.reduce((sum, bucket) => sum + bucket.count, 0);
    const voiceTotal = buckets.reduce((sum, bucket) => sum + (Number.isFinite(bucket.voice) ? bucket.voice : 0), 0);
    const gestureTotal = buckets.reduce((sum, bucket) => sum + (Number.isFinite(bucket.gesture) ? bucket.gesture : 0), 0);
    const peakBucket = total > 0 ? available.reduce((peak, bucket) => !peak || bucket.count > peak.count ? bucket : peak, null) : null;
    return { ...fallback, total, voiceTotal, gestureTotal, average: available.length ? Number((total / available.length).toFixed(1)) : 0, peak: peakBucket ? { label: peakBucket.label, count: peakBucket.count } : null };
  }
  if (!['week', 'year'].includes(period)) return fallback;
  if (kind === 'accuracy') return { voice: averageOf(buckets, 'voice'), gaze: averageOf(buckets, 'gaze'), motion: averageOf(buckets, 'motion') };
  if (kind === 'latency') {
    const simpleMs = averageOf(buckets, 'simpleMs'); const complexMs = averageOf(buckets, 'complexMs');
    const all = [simpleMs, complexMs].filter((value) => value != null);
    return { simpleMs, complexMs, overallMs: all.length ? all.reduce((sum, value) => sum + value, 0) / all.length : null };
  }
  return fallback;
}

export default function DashboardHome() {
  const location = useLocation(); const navigate = useNavigate();
  const requestedView = new URLSearchParams(location.search).get('view');
  const view = views.includes(requestedView) ? requestedView : 'home';
  const registration = useGestureStore((state) => state.registration);
  const [menu, setMenu] = useState(false); const [overview, setOverview] = useState(null); const [detail, setDetail] = useState(null); const [period, setPeriod] = useState('day'); const [loading, setLoading] = useState(false); const [error, setError] = useState('');
  useEffect(() => { if (view === 'home') load(fetchDashboardOverview, setOverview); }, [view]);
  useEffect(() => { if (details[view]) load(() => details[view][2](period), setDetail); }, [view, period]);
  async function load(fetcher, setter) { setLoading(true); setError(''); try { setter(await fetcher()); } catch (requestError) { setError(requestError.message); } finally { setLoading(false); } }
  const open = (next) => { if (next !== 'gestures') useGestureStore.getState().closeRegistration(); setMenu(false); setError(''); if (details[next]) { setPeriod('day'); setDetail(null); } navigate(next === 'home' ? '/dashboard' : `/dashboard?view=${next}`); };
  const registrationTitle = registration?.stage === 'complete' || registration?.stage === 'form' ? '제스처 등록' : registration?.stage === 'review' ? '촬영 결과' : '제스처 촬영';
  const panelTitle = view === 'gestures' ? (registration ? registrationTitle : '제스처') : view === 'voice' ? '보이스' : '시선';
  const back = () => { if (view === 'gestures' && registration) { useGestureStore.getState().closeRegistration(); return; } open('home'); };
  return <main className={`${styles.page} ${styles[`view_${view}`] ?? ''}`}>
    <header className={styles.header}><button className={styles.brand} onClick={() => open('home')} aria-label="대시보드 홈"><SiaLogo /></button><span />{!(registration && ['form', 'complete'].includes(registration.stage)) && <button className={styles.menuButton} onClick={() => setMenu((value) => !value)} aria-label="메뉴"><i /><i /><i /></button>}</header>
    {menu && <><button className={styles.scrim} onClick={() => setMenu(false)} aria-label="메뉴 닫기" /><nav className={styles.drawer}>{[['gestures', '제스처'], ['voice', '보이스'], ['gaze', '시선'], ['settings', '설정']].map(([key, label]) => <button key={key} onClick={() => open(key)}><NavIcon kind={key} />{label}<span>›</span></button>)}</nav></>}
    <section className={styles.content}>{loading && <p className={styles.loading} role="status">데이터를 불러오는 중입니다.</p>}{error && <p className={styles.error} role="alert">{error}</p>}
      {view === 'home' && <Overview data={overview} open={open} />}
      {details[view] && <Detail kind={view} data={detail} period={period} setPeriod={setPeriod} open={open} />}
      {['gestures', 'gaze'].includes(view) && <div className={styles.panelHeading}><button onClick={back}>‹</button><h1>{panelTitle}</h1></div>}
      {view === 'gestures' && <GesturePanel />}{view === 'voice' && <VoicePanel onBack={back} />}{view === 'gaze' && <GazePanel />}{view === 'settings' && <SettingsPanel />}
    </section>
  </main>;
}

function Intro({ title, description, eyebrow = '' }) { return <div className={styles.intro}><small>{eyebrow}</small><h1>{title}</h1><p>{description}</p><i /></div>; }
function Label({ overline, title, description }) { return <div className={styles.cardLabel}><small>{overline}</small><strong>{title}</strong>{description && <p>{description}</p>}</div>; }
function SiaLogo() { return <img src={siaLogo} alt="SIA" />; }
function NavIcon({ kind }) {
  if (kind === 'gestures') return <svg className={styles.navIcon} viewBox="0 0 64 64" aria-hidden="true"><path d="M20 30V16a4 4 0 0 1 8 0v11-16a4 4 0 0 1 8 0v16-13a4 4 0 0 1 8 0v15-9a4 4 0 0 1 8 0v19c0 13-8 21-20 21S12 52 12 40v-8a4 4 0 0 1 8 0v5" /></svg>;
  if (kind === 'voice') return <svg className={styles.navIcon} viewBox="0 0 64 64" aria-hidden="true"><rect x="23" y="7" width="18" height="34" rx="9" /><path d="M15 34v2c0 10 7 17 17 17s17-7 17-17v-2M32 53v9M23 62h18" /></svg>;
  if (kind === 'gaze') return <svg className={styles.navIcon} viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="20" /><path d="M32 1v18M32 45v18M1 32h18M45 32h18M32 20v24" /><circle className={styles.gazeDot} cx="43" cy="23" r="3.4" /></svg>;
  return <svg className={styles.navIcon} viewBox="0 0 64 64" aria-hidden="true"><path d="m32 4 5 6 8-2 3 8 8 2-1 9 6 5-6 6 1 8-8 3-3 8-8-2-5 6-6-6-8 2-3-8-8-3 1-8-6-6 6-5-1-9 8-2 3-8 8 2Z" /><circle cx="32" cy="32" r="8" /></svg>;
}

function Overview({ data, open }) {
  if (!data) return null;
  const accuracy = [['음성 인식 정확도', data.accuracy?.voice], ['시선처리 정확도', data.accuracy?.gaze], ['모션인식 정확도', data.accuracy?.motion]];
  const buckets = calendarBuckets(data.usage?.buckets ?? [], 'week'); const maxUsage = Math.max(1, ...buckets.map((item) => item.count ?? 0)); const apps = data.topApps ?? []; const maxApps = Math.max(1, ...apps.map((item) => item.count));
  return <><Intro title="SIA 대시보드" description="AI가 더 편리한 일상을 만들어갑니다." />
    <div className={styles.overviewGrid}>
      <button className={`${styles.dashboardCard} ${styles.usageOverview}`} onClick={() => open('usage')}><Label overline="USAGE" title="제스처 / 보이스 사용량" description="이번 주 사용 현황 · 클릭 시 자세히 보기" /><div className={styles.overviewBars}>{buckets.map((item) => <span key={item.key}><i style={{ height: `${(item.count ?? 0) / maxUsage * 76 + 4}%` }} /><small>{item.label}</small></span>)}</div></button>
      <div className={styles.overviewSide}>
        <button className={`${styles.dashboardCard} ${styles.accuracyOverview}`} onClick={() => open('accuracy')}><Label overline="AI STATUS" title="인식 정확도" /><div className={styles.accuracyRings}>{accuracy.map(([label, value]) => <span key={label}><i style={{ '--accuracy': `${(value ?? 0) * 360}deg` }}><strong>{percent(value)}</strong></i><small>{label}</small></span>)}</div></button>
        <button className={`${styles.dashboardCard} ${styles.latencyOverview}`} onClick={() => open('latency')}><Label overline="RESPONSE" title="평균 응답 시간" /><div><span><small>간단한 작업</small><strong>{seconds(data.latency?.simpleMs)}</strong><i /></span><span><small>복잡한 작업</small><strong>{seconds(data.latency?.complexMs)}</strong><i /></span></div></button>
      </div>
      <button className={`${styles.dashboardCard} ${styles.appsOverview}`} onClick={() => open('apps')}><Label overline="TOP PROGRAMS" title="자주 사용하는 프로그램" /><div>{apps.length ? apps.slice(0, 5).map((item) => <span key={item.appKey}><AppIcon name={item.displayName} /><em>{item.displayName}</em><i><u style={{ width: `${item.count / maxApps * 100}%` }} /></i><strong>{item.count}회</strong></span>) : <Empty />}</div></button>
    </div></>;
}

function Detail({ kind, data, period, setPeriod, open }) {
  if (!data) return null; const buckets = calendarBuckets(data.buckets ?? [], period); const summary = calendarSummary(kind, buckets, data.summary ?? {}, period);
  return <><div className={styles.detailHead}><button className={styles.detailBack} onClick={() => open('home')}>‹</button><Intro eyebrow="분석" title={details[kind][0]} description={details[kind][1]} /><Periods period={period} setPeriod={setPeriod} /></div>
    <section className={`${styles.largeCard} ${styles[`chart_${kind}`]} ${styles[`period_${period}`]}`}><ChartHeading kind={kind} />
      {kind === 'accuracy' && <><Legend items={['음성 인식', '시선처리', '모션인식']} /><LineChart buckets={buckets} series={[{ key: 'voice' }, { key: 'gaze' }, { key: 'motion' }]} /></>}
      {kind === 'latency' && <><Legend items={['간단한 작업', '복잡한 작업']} /><BarChart buckets={buckets} series={[{ key: 'simpleMs' }, { key: 'complexMs' }]} valueFormatter={(value) => `${(value / 1000).toFixed(1)}s`} /></>}
      {kind === 'usage' && <><Legend items={['보이스', '제스처', '전체 추세']} /><BarChart buckets={buckets} series={[{ key: 'voice' }, { key: 'gesture' }]} lineKey="count" minimumMax={4} valueFormatter={(value) => Math.round(value)} /></>}
      {kind === 'apps' && ((data.items ?? []).length ? <HorizontalBars items={data.items} /> : <Empty />)}
    </section><Summary kind={kind} summary={summary} /></>;
}

function Periods({ period, setPeriod }) { return <div className={styles.periods}>{periods.map((item) => <button className={period === item.key ? styles.activePeriod : ''} onClick={() => setPeriod(item.key)} key={item.key}>{item.label}</button>)}</div>; }
function ChartHeading({ kind }) {
  if (kind === 'accuracy') return <div className={styles.chartHeading}><small>RECOGNITION ACCURACY</small></div>;
  if (kind === 'latency') return <div className={styles.chartHeading}><strong>◉</strong><b>시간대별 평균 응답 시간</b></div>;
  if (kind === 'usage') return <div className={styles.chartHeading}><b>시간대별 사용량</b><small>VOICE / GESTURE ANALYTICS</small></div>;
  return <div className={styles.chartHeading}><b>프로그램 사용 순위</b><small>TOP PROGRAMS / FREQUENCY</small><em>실행 횟수 기준</em></div>;
}
function Legend({ items }) { return <div className={styles.legend}>{items.map((item, index) => <span key={item}><i className={styles[`legend${index}`]} />{item}</span>)}</div>; }
function Summary({ kind, summary }) { const items = kind === 'accuracy' ? [['평균 음성 인식 정확도', percent(summary.voice)], ['평균 시선처리 정확도', percent(summary.gaze)], ['평균 모션인식 정확도', percent(summary.motion)]] : kind === 'latency' ? [['간단한 작업 평균', seconds(summary.simpleMs)], ['복잡한 작업 평균', seconds(summary.complexMs)], ['전체 평균', seconds(summary.overallMs)]] : kind === 'usage' ? [['보이스 사용', `${summary.voiceTotal ?? 0}회`], ['제스처 사용', `${summary.gestureTotal ?? 0}회`], ['전체 사용량', `${summary.total ?? 0}회`]] : [['전체 프로그램 실행 횟수', `${summary.totalLaunches ?? 0}회`], ['가장 많이 사용한 프로그램', summary.topDisplayName ?? '데이터 없음'], ['해당 프로그램 사용 횟수', `${summary.topCount ?? 0}회`]]; return <div className={`${styles.summaryCards} ${styles[`summary_${kind}`]}`}>{items.map(([label, value], index) => <span className={index === 2 ? styles.summaryAccent : ''} key={label}><small>{label}</small><strong>{value}</strong><SummaryVisual kind={kind} index={index} /></span>)}</div>; }
function SummaryVisual({ kind, index }) {
  if (kind === 'accuracy' && index === 1) return <svg viewBox="0 0 64 48"><path d="M4 24s10-14 28-14 28 14 28 14-10 14-28 14S4 24 4 24Z" /><circle cx="32" cy="24" r="7" /></svg>;
  if (kind === 'accuracy' && index === 2) return <svg viewBox="0 0 64 48"><circle cx="34" cy="8" r="4" /><path d="m30 15 10 6 8-3M31 16l-6 12-9 7M26 28l12 4 6 12M22 22l-9 3" /></svg>;
  if ((kind === 'latency' || kind === 'apps') && index === 2 || kind === 'usage' && index === 2) return <svg viewBox="0 0 64 48"><circle cx="32" cy="24" r="17" /><path d="M32 7a17 17 0 0 1 17 17H32Z" /></svg>;
  return <svg viewBox="0 0 72 48"><path d="M4 25h5l3-9 4 20 5-29 5 36 5-27 5 19 5-25 5 31 5-20 4 13 4-9h9" /></svg>;
}
function AppIcon({ name = '' }) {
  const normalized = name.toLowerCase();
  if (normalized.includes('chrome') || normalized.includes('크롬')) return <svg className={styles.appIcon} viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="4" /><path d="M3.5 7h9M8 21l4-9M21 12h-9" /></svg>;
  if (normalized.includes('slack') || normalized.includes('슬랙')) return <svg className={styles.appIcon} viewBox="0 0 24 24"><path d="M9 3v7M9 14v2a3 3 0 1 1-3-3h2M15 21v-7M15 10V8a3 3 0 1 1 3 3h-2M3 15h7M14 15h2a3 3 0 1 1-3 3v-2M21 9h-7M10 9H8a3 3 0 1 1 3-3v2" /></svg>;
  if (normalized.includes('탐색') || normalized.includes('explorer')) return <svg className={styles.appIcon} viewBox="0 0 24 24"><path d="M2 7h8l2 2h10v11H2Z" /><path d="M2 7V4h8l2 3" /></svg>;
  return <svg className={styles.appIcon} viewBox="0 0 24 24"><rect x="4" y="2" width="16" height="20" rx="2" /><path d="M8 7h8M8 11h8M8 15h6" /></svg>;
}
function Empty() { return <p className={styles.empty}>아직 표시할 활동 데이터가 없습니다.</p>; }
