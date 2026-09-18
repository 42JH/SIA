import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { fetchDashboardOverview, fetchDashboardAccuracy, fetchDashboardLatency, fetchDashboardUsage, fetchDashboardApps } from '../../api/dashboard';
import { BarChart, HorizontalBars } from './DashboardChart';
import GesturePanel from './GesturePanel';
import SettingsPanel from './SettingsPanel';
import VoicePanel from './VoicePanel';
import GazePanel from './GazePanel';
import { useGestureStore } from '../../store/gestureStore';
import siaLogo from '../../assets/sia-logo.png';
import navSettings from '../../assets/nav-settings.png';
import navDashboard from '../../assets/nav-dashboard.png';
import navVoice from '../../assets/nav-voice.png';
import navGaze from '../../assets/nav-gaze.png';
import navGestures from '../../assets/nav-gestures.png';
import styles from './DashboardHome.module.css';

const periods = [{ key: 'day', label: '1일' }, { key: 'week', label: '7일' }, { key: 'month', label: '1개월' }, { key: 'year', label: '1년' }];
const nextPeriod = { year: 'month', month: 'week', week: 'day' };
const periodGrain = { year: '월별', month: '주차별', week: '요일별', day: '시간대별' };
const details = {
  accuracy: ['인식 정확도', 'AI가 세상을 이해하는 정확도를 한눈에 확인하세요.'],
  latency: ['평균 응답 시간', '작업 유형별 평균 응답 시간을 확인할 수 있습니다.'],
  usage: ['제스처 / 보이스 사용량', '시간대별 사용 흐름과 입력 방식의 비중을 확인할 수 있습니다.'],
  apps: ['자주 사용하는 프로그램', '프로그램별 실행 빈도와 사용 흐름을 한눈에 확인할 수 있습니다.'],
};
const views = ['home', 'settings', 'voice', 'gestures', 'gaze', ...Object.keys(details)];
const fetchers = { accuracy: fetchDashboardAccuracy, latency: fetchDashboardLatency, usage: fetchDashboardUsage, apps: fetchDashboardApps };
const percent = (value) => value == null ? '데이터 없음' : `${Math.round(value * 100)}%`;
const seconds = (value) => value == null ? '데이터 없음' : `${(value / 1000).toFixed(1)}초`;
const weekLabels = ['월', '화', '수', '목', '금', '토', '일'];

function dayKey(value) {
  const text = value instanceof Date
    ? `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
    : String(value ?? '');
  const match = text.match(/(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})/);
  return match ? `${match[1]}-${match[2].padStart(2, '0')}-${match[3].padStart(2, '0')}` : '';
}

function parseBucketDate(bucket) {
  const key = dayKey(bucket?.key);
  if (!key) return null;
  const [year, month, day] = key.split('-').map(Number);
  const date = new Date(year, month - 1, day);
  return Number.isNaN(date.getTime()) ? null : date;
}

function usageCount(bucket) {
  if (Number.isFinite(bucket?.count)) return bucket.count;
  return (Number(bucket?.voice) || 0) + (Number(bucket?.gesture) || 0);
}

function weekUsageBuckets(buckets, anchor = '') {
  const source = Array.isArray(buckets) ? buckets : [];
  const base = String(anchor).match(/(20\d{2})-(\d{2})-(\d{2})/) ? new Date(Number(anchor.slice(0, 4)), Number(anchor.slice(5, 7)) - 1, Number(anchor.slice(8, 10))) : new Date();
  return weekLabels.map((label, index) => {
    const byLabel = source.find((bucket) => String(bucket.label ?? '').replace('요일', '').trim().startsWith(label));
    const byKey = source.find((bucket) => {
      const monday = new Date(base.getFullYear(), base.getMonth(), base.getDate() - ((base.getDay() + 6) % 7));
      monday.setDate(monday.getDate() + index);
      return dayKey(bucket.key) === dayKey(monday);
    });
    const match = byLabel ?? byKey ?? {};
    return { ...match, key: match.key ?? `week-${index}`, label, count: usageCount(match) };
  });
}

function calendarBuckets(buckets, period, anchor = '') {
  if (!Array.isArray(buckets) || !['week', 'year'].includes(period)) return buckets ?? [];
  if (period === 'week') return weekUsageBuckets(buckets, anchor);
  const year = String(anchor).match(/(20\d{2})/) ? Number(anchor.slice(0, 4)) : new Date().getFullYear(); let inferredYear = null; let previousMonth = null;
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
    const normalized = buckets.map((bucket) => ({ ...bucket, count: Number.isFinite(bucket.count) ? bucket.count : (bucket.voice ?? 0) + (bucket.gesture ?? 0) }));
    const available = normalized.filter((bucket) => Number.isFinite(bucket.count)); const total = available.reduce((sum, bucket) => sum + bucket.count, 0);
    const voiceTotal = buckets.reduce((sum, bucket) => sum + (Number.isFinite(bucket.voice) ? bucket.voice : 0), 0);
    const gestureTotal = buckets.reduce((sum, bucket) => sum + (Number.isFinite(bucket.gesture) ? bucket.gesture : 0), 0);
    const peakBucket = total > 0 ? available.reduce((peak, bucket) => !peak || bucket.count > peak.count ? bucket : peak, null) : null;
    return { ...fallback, total, voiceTotal, gestureTotal, average: available.length ? Number((total / available.length).toFixed(1)) : 0, peak: peakBucket ? { label: peakBucket.label, count: peakBucket.count } : null };
  }
  if (!['week', 'year'].includes(period)) return fallback;
  if (kind === 'accuracy') return { voice: averageOf(buckets, 'voice'), motion: averageOf(buckets, 'motion') };
  if (kind === 'latency') {
    const simpleMs = averageOf(buckets, 'simpleMs'); const complexMs = averageOf(buckets, 'complexMs');
    const all = [simpleMs, complexMs].filter((value) => value != null);
    return { simpleMs, complexMs, overallMs: all.length ? all.reduce((sum, value) => sum + value, 0) / all.length : null };
  }
  return fallback;
}

function bucketAnchor(bucket, period, currentAnchor = '') {
  const key = String(bucket?.key ?? '');
  if (key && !key.startsWith('week-') && !key.startsWith('year-')) return key;
  const label = String(bucket?.label ?? '');
  const week = label.match(/(\d{1,2})월\s*(\d)주차/);
  if (week) {
    const year = String(currentAnchor).match(/(20\d{2})/) ? currentAnchor.slice(0, 4) : String(new Date().getFullYear());
    return `${year}-${String(Number(week[1])).padStart(2, '0')}-W${week[2]}`;
  }
  const month = label.match(/(\d{1,2})월/);
  if (period === 'year' && month) {
    const year = String(currentAnchor).match(/(20\d{2})/) ? currentAnchor.slice(0, 4) : String(new Date().getFullYear());
    return `${year}-${String(Number(month[1])).padStart(2, '0')}`;
  }
  if (period === 'week') {
    const index = weekLabels.findIndex((item) => label.replace('요일', '').trim().startsWith(item));
    if (index >= 0) {
      const base = String(currentAnchor).match(/(20\d{2})-(\d{2})-(\d{2})/) ? new Date(Number(currentAnchor.slice(0, 4)), Number(currentAnchor.slice(5, 7)) - 1, Number(currentAnchor.slice(8, 10))) : new Date();
      const monday = new Date(base.getFullYear(), base.getMonth(), base.getDate() - ((base.getDay() + 6) % 7));
      monday.setDate(monday.getDate() + index);
      return dayKey(monday);
    }
  }
  return key || label;
}

export default function DashboardHome() {
  const location = useLocation(); const navigate = useNavigate();
  const requestedView = new URLSearchParams(location.search).get('view');
  const view = views.includes(requestedView) ? requestedView : 'home';
  const historyStack = Array.isArray(location.state?.dashboardHistory) ? location.state.dashboardHistory : [];
  const registration = useGestureStore((state) => state.registration);
  const [menu, setMenu] = useState(false); const [overview, setOverview] = useState(null); const [detail, setDetail] = useState(null); const [period, setPeriod] = useState('week'); const [anchor, setAnchor] = useState(''); const [loading, setLoading] = useState(false); const [error, setError] = useState('');
  useEffect(() => { if (view === 'home') loadHome(); }, [view]);
  useEffect(() => {
    if (!menu) return undefined;
    const html = document.documentElement;
    const previous = { html: html.style.overflow, body: document.body.style.overflow, position: document.body.style.position, top: document.body.style.top, width: document.body.style.width };
    const scrollY = window.scrollY;
    html.style.overflow = 'hidden';
    document.body.style.overflow = 'hidden';
    document.body.style.position = 'fixed';
    document.body.style.top = `-${scrollY}px`;
    document.body.style.width = '100%';
    const blockScroll = (event) => event.preventDefault();
    window.addEventListener('wheel', blockScroll, { passive: false });
    window.addEventListener('touchmove', blockScroll, { passive: false });
    return () => {
      html.style.overflow = previous.html;
      document.body.style.overflow = previous.body;
      document.body.style.position = previous.position;
      document.body.style.top = previous.top;
      document.body.style.width = previous.width;
      window.removeEventListener('wheel', blockScroll);
      window.removeEventListener('touchmove', blockScroll);
      window.scrollTo(0, scrollY);
    };
  }, [menu]);
  useEffect(() => {
    if (!details[view]) return undefined;
    // TODO(BE): 선택한 과거 월·일을 기준으로 조회할 anchor 파라미터가 명세에 추가되면 period와 함께 전달할 것
    load(() => fetchers[view](period), setDetail);
    return undefined;
  }, [view, period, anchor]);
  async function load(fetcher, setter) { setLoading(true); setError(''); try { setter(await fetcher()); } catch (requestError) { setError(requestError.message); } finally { setLoading(false); } }
  function loadHome() { load(fetchDashboardOverview, setOverview); }
  const open = (next) => {
    if (next !== 'gestures') useGestureStore.getState().closeRegistration();
    setMenu(false); setError('');
    if (details[next]) { setPeriod('week'); setAnchor(''); setDetail(null); }
    const nextHistory = next === 'home' || view === next ? (next === 'home' ? [] : historyStack) : [...historyStack, view];
    navigate(next === 'home' ? '/dashboard' : `/dashboard?view=${next}`, { state: { dashboardHistory: nextHistory } });
  };
  const registrationTitle = registration?.stage === 'complete' || registration?.stage === 'form' ? '제스처 등록' : registration?.stage === 'review' ? '촬영 결과' : '제스처 촬영';
  const panelTitle = view === 'gestures' ? (registration ? registrationTitle : '제스처') : view === 'voice' ? '보이스' : view === 'gaze' ? '시선' : view === 'settings' ? '설정' : '';
  const back = () => {
    if (view === 'gestures' && registration) { useGestureStore.getState().closeRegistration(); return; }
    const previous = historyStack[historyStack.length - 1];
    const rest = historyStack.slice(0, -1);
    if (previous && previous !== view && views.includes(previous)) {
      if (view !== 'gestures') useGestureStore.getState().closeRegistration();
      navigate(previous === 'home' ? '/dashboard' : `/dashboard?view=${previous}`, { replace: true, state: { dashboardHistory: rest } });
      return;
    }
    open('home');
  };
  return <main className={`${styles.page} ${styles[`view_${view}`] ?? ''}`}>
    <header className={styles.header}><button className={styles.brand} onClick={() => open('home')} aria-label="대시보드 홈"><SiaLogo /></button><span />{!(registration && ['form', 'complete'].includes(registration.stage)) && <button className={styles.menuButton} onClick={() => setMenu((value) => !value)} aria-label="메뉴"><i /><i /><i /></button>}</header>
    {menu && <><button className={styles.scrim} onClick={() => setMenu(false)} aria-label="메뉴 닫기" /><nav className={styles.drawer}>{[['home', '대시보드'], ['gestures', '제스처'], ['voice', '보이스'], ['gaze', '시선'], ['settings', '설정']].map(([key, label]) => <button key={key} onClick={() => open(key)}><NavIcon kind={key} />{label}<span>›</span></button>)}</nav></>}
    <section className={styles.content}>{loading && <p className={styles.loading} role="status">데이터를 불러오는 중입니다.</p>}{error && <p className={styles.error} role="alert">{error}</p>}
      {view === 'home' && <Overview data={overview} open={open} />}
      {details[view] && <Detail kind={view} data={detail} period={period} setPeriod={setPeriod} open={open} loading={loading} anchor={anchor} onBucket={setAnchor} />}
      {(view === 'gestures' || view === 'settings') && <div className={styles.panelHeading}><button onClick={back} aria-label="이전 화면으로 돌아가기">‹</button><h1>{panelTitle}</h1></div>}
      {view === 'gestures' && <GesturePanel />}{view === 'voice' && <VoicePanel onBack={back} />}{view === 'gaze' && <GazePanel onBack={back} />}{view === 'settings' && <SettingsPanel />}
    </section>
  </main>;
}

function Intro({ title, description, eyebrow = '' }) { return <div className={styles.intro}><small>{eyebrow}</small><h1>{title}</h1><p>{description}</p><i /></div>; }
function Label({ overline, title, description }) { return <div className={styles.cardLabel}><small>{overline}</small><strong>{title}</strong>{description && <p>{description}</p>}</div>; }
function SiaLogo() { return <img src={siaLogo} alt="SIA" />; }
function NavIcon({ kind }) {
  const icons = { settings: navSettings, home: navDashboard, voice: navVoice, gaze: navGaze, gestures: navGestures };
  return <img className={styles.navIcon} src={icons[kind]} alt="" aria-hidden="true" />;
}

function Overview({ data, open }) {
  if (!data) return null;
  const accuracy = [['음성 인식 정확도', data.accuracy?.voice], ['모션인식 정확도', data.accuracy?.motion]];
  const buckets = weekUsageBuckets(data.usage?.buckets ?? []); const maxUsage = Math.max(1, ...buckets.map((item) => item.count ?? 0)); const apps = data.topApps ?? []; const maxApps = Math.max(1, ...apps.map((item) => item.count));
  return <><Intro title="SIA 대시보드" description="AI가 더 편리한 일상을 만들어갑니다." />
    <div className={styles.overviewGrid}>
      <button className={`${styles.dashboardCard} ${styles.usageOverview}`} onClick={() => open('usage')}><Label overline="USAGE" title="제스처 / 보이스 사용량" description="이번 주 사용 현황 · 클릭 시 자세히 보기" /><div className={styles.overviewBars}>{buckets.map((item) => <span key={item.key}><i className={item.count > 0 ? undefined : styles.emptyBar} style={{ height: item.count > 0 ? `${Math.max(8, item.count / maxUsage * 86)}%` : 0 }} /><small>{item.label}</small></span>)}</div></button>
      <div className={styles.overviewSide}>
        <button className={`${styles.dashboardCard} ${styles.accuracyOverview}`} onClick={() => open('accuracy')}><Label overline="AI STATUS" title="인식 정확도" /><div className={styles.accuracyRings}>{accuracy.map(([label, value]) => <span key={label}><i style={{ '--accuracy': `${(value ?? 0) * 360}deg` }}><strong>{percent(value)}</strong></i><small>{label}</small></span>)}</div></button>
        <button className={`${styles.dashboardCard} ${styles.latencyOverview}`} onClick={() => open('latency')}><Label overline="RESPONSE" title="평균 응답 시간" /><div><span><small>간단한 작업</small><strong>{seconds(data.latency?.simpleMs)}</strong><i /></span><span><small>복잡한 작업</small><strong>{seconds(data.latency?.complexMs)}</strong><i /></span></div></button>
      </div>
      <button className={`${styles.dashboardCard} ${styles.appsOverview}`} onClick={() => open('apps')}><Label overline="TOP PROGRAMS" title="자주 사용하는 프로그램" /><div>{apps.length ? apps.slice(0, 5).map((item) => <span key={item.appKey}><AppIcon name={item.displayName} /><em>{item.displayName}</em><i><u style={{ width: `${item.count / maxApps * 100}%` }} /></i><strong>{item.count}회</strong></span>) : <Empty />}</div></button>
    </div></>;
}

function Detail({ kind, data, period, setPeriod, open, loading, anchor, onBucket }) {
  if (!data) return null; const buckets = calendarBuckets(data.buckets ?? [], period, anchor).map((bucket) => kind === 'usage' ? { ...bucket, count: Number.isFinite(bucket.count) ? bucket.count : (bucket.voice ?? 0) + (bucket.gesture ?? 0) } : bucket); const summary = calendarSummary(kind, buckets, data.summary ?? {}, period);
  // TODO(BE): 선택한 과거 월·일을 기준으로 조회할 anchor 파라미터가 명세에 추가되면 선택 bucket key를 API에 전달 필요
  const canDrill = Boolean(nextPeriod[period]) && !loading;
  const drillDown = (bucket) => {
    if (!canDrill) return;
    onBucket(bucketAnchor(bucket, period, anchor));
    setPeriod(nextPeriod[period] ?? period);
  };
  const choosePeriod = (next) => { onBucket(''); setPeriod(next); };
  return <><div className={styles.detailHead}><button className={styles.detailBack} onClick={() => open('home')}>‹</button><Intro eyebrow="분석" title={details[kind][0]} description={details[kind][1]} /><Periods period={period} setPeriod={choosePeriod} /></div>
    <section className={`${styles.largeCard} ${styles[`chart_${kind}`]} ${styles[`period_${period}`]}`}><ChartHeading kind={kind} period={period} />
      {kind === 'accuracy' && <><Legend items={['음성 인식', '모션인식']} /><BarChart buckets={buckets} series={[{ key: 'voice' }, { key: 'motion' }]} valueFormatter={(value) => `${Math.round(value * 100)}%`} onBucketClick={canDrill ? drillDown : undefined} /></>}
      {kind === 'latency' && <><Legend items={['간단한 작업', '복잡한 작업']} /><BarChart buckets={buckets} series={[{ key: 'simpleMs' }, { key: 'complexMs' }]} valueFormatter={(value) => `${(value / 1000).toFixed(1)}s`} onBucketClick={canDrill ? drillDown : undefined} /></>}
      {kind === 'usage' && <><Legend items={['보이스', '제스처', '전체 사용량']} /><BarChart buckets={buckets} series={[{ key: 'voice' }, { key: 'gesture' }, { key: 'count' }]} minimumMax={4} valueFormatter={(value) => Math.round(value)} onBucketClick={canDrill ? drillDown : undefined} /></>}
      {kind === 'apps' && ((data.items ?? []).length ? <HorizontalBars items={data.items} /> : <Empty />)}
    </section><Summary kind={kind} summary={summary} /></>;
}

function Periods({ period, setPeriod }) { return <div className={styles.periods}>{periods.map((item) => <button className={period === item.key ? styles.activePeriod : ''} onClick={() => setPeriod(item.key)} key={item.key}>{item.label}</button>)}</div>; }
function ChartHeading({ kind, period }) {
  const grain = periodGrain[period] ?? '기간별';
  if (kind === 'accuracy') return <div className={styles.chartHeading}><small>RECOGNITION ACCURACY</small><b>{grain} 인식 정확도</b></div>;
  if (kind === 'latency') return <div className={styles.chartHeading}><strong>◉</strong><b>{grain} 평균 응답 시간</b></div>;
  if (kind === 'usage') return <div className={styles.chartHeading}><b>{grain} 사용량</b><small>VOICE / GESTURE ANALYTICS</small></div>;
  return <div className={styles.chartHeading}><b>프로그램 사용 순위</b><small>TOP PROGRAMS / FREQUENCY</small><em>실행 횟수 기준</em></div>;
}
function Legend({ items }) { return <div className={styles.legend}>{items.map((item, index) => <span key={item}><i className={styles[`legend${index}`]} />{item}</span>)}</div>; }
function Summary({ kind, summary }) { const items = kind === 'accuracy' ? [['평균 음성 인식 정확도', percent(summary.voice)], ['평균 모션인식 정확도', percent(summary.motion)]] : kind === 'latency' ? [['간단한 작업 평균', seconds(summary.simpleMs)], ['복잡한 작업 평균', seconds(summary.complexMs)], ['전체 평균', seconds(summary.overallMs)]] : kind === 'usage' ? [['보이스 사용', `${summary.voiceTotal ?? 0}회`], ['제스처 사용', `${summary.gestureTotal ?? 0}회`], ['전체 사용량', `${summary.total ?? 0}회`]] : [['전체 프로그램 실행 횟수', `${summary.totalLaunches ?? 0}회`], ['가장 많이 사용한 프로그램', summary.topDisplayName ?? '데이터 없음'], ['가장 많이 이용된 프로그램 실행 횟수', `${summary.topCount ?? 0}회`]]; return <div className={`${styles.summaryCards} ${styles[`summary_${kind}`]}`}>{items.map(([label, value], index) => <span className={index === items.length - 1 ? styles.summaryAccent : ''} key={label}><small>{label}</small><strong>{value}</strong><SummaryVisual kind={kind} index={index} /></span>)}</div>; }
function SummaryVisual({ kind, index }) {
  if (kind === 'accuracy' && index === 1) return <svg viewBox="0 0 64 48"><circle cx="34" cy="8" r="4" /><path d="m30 15 10 6 8-3M31 16l-6 12-9 7M26 28l12 4 6 12M22 22l-9 3" /></svg>;
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
