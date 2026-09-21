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

const periods = [{ key: 'day', label: '1일' }, { key: 'week', label: '7일' }, { key: 'month', label: '한달' }, { key: 'year', label: '1년' }];
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

function usageCount(bucket) {
  if (Number.isFinite(bucket?.count)) return bucket.count;
  return (Number(bucket?.voice) || 0) + (Number(bucket?.gesture) || 0);
}

const WEEKDAY_LABELS = ['월', '화', '수', '목', '금', '토', '일'];

function monthAxisLabel(bucket) {
  const date = String(bucket?.key ?? '').match(/(20\d{2})-(\d{2})-(\d{2})/);
  if (date) {
    const parsed = new Date(Number(date[1]), Number(date[2]) - 1, Number(date[3]));
    if (!Number.isNaN(parsed.getTime())) {
      const week = [1, 7, 14, 21, 28].indexOf(parsed.getDate());
      const weekNum = week >= 0 ? week + 1 : Math.ceil(parsed.getDate() / 7);
      return `${parsed.getMonth() + 1}월 ${weekNum}주차`;
    }
  }
  const label = String(bucket?.label ?? '').replace(/\s+/g, ' ').trim();
  return /^\d{1,2}월\s*\d주차$/.test(label) ? label : String(bucket?.label ?? '');
}

function pad2(value) {
  return String(value).padStart(2, '0');
}

function toYmd(date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

function parseBucketDate(key) {
  const text = String(key ?? '');
  const month = text.match(/^(20\d{2})-(\d{2})$/);
  if (month) return new Date(Number(month[1]), Number(month[2]) - 1, 1);
  const stamp = text.match(/^(20\d{2})-(\d{2})-(\d{2})/);
  if (stamp) return new Date(Number(stamp[1]), Number(stamp[2]) - 1, Number(stamp[3]));
  return null;
}

function monthWeekAxis(anchorKey) {
  const date = parseBucketDate(anchorKey);
  if (!date) return null;
  const year = date.getFullYear();
  const month = date.getMonth();
  return [1, 7, 14, 21, 28].map((day, index) => ({
    key: toYmd(new Date(year, month, day)),
    label: `${month + 1}월 ${index + 1}주차`,
  }));
}

function weekDayAxis(anchorKey) {
  const start = parseBucketDate(anchorKey);
  if (!start) return null;
  return Array.from({ length: 7 }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    return { key: toYmd(date), label: WEEKDAY_LABELS[(date.getDay() + 6) % 7] };
  });
}

function dayHourAxis(anchorKey) {
  const date = parseBucketDate(anchorKey);
  if (!date) return null;
  const day = toYmd(date);
  return Array.from({ length: 8 }, (_, index) => {
    const hour = pad2(index * 3);
    return { key: `${day}T${hour}`, label: `${hour}시` };
  });
}

function axisForPeriod(period, anchorKey) {
  if (!anchorKey) return null;
  if (period === 'month') return monthWeekAxis(anchorKey);
  if (period === 'week') return weekDayAxis(anchorKey);
  if (period === 'day') return dayHourAxis(anchorKey);
  return null;
}

function emptyBucket(kind, slot) {
  if (kind === 'usage') return { ...slot, count: 0, voice: 0, gesture: 0 };
  if (kind === 'accuracy') return { ...slot, voice: null, gaze: null, motion: null, sampleCount: 0 };
  if (kind === 'latency') return { ...slot, simpleMs: null, complexMs: null, simpleCount: 0, complexCount: 0 };
  return { ...slot };
}

function alignBuckets(kind, axis, buckets) {
  const byKey = new Map((buckets ?? []).map((bucket) => [String(bucket.key), bucket]));
  return axis.map((slot) => {
    const hit = byKey.get(slot.key);
    return hit ? { ...hit, key: slot.key, label: slot.label } : emptyBucket(kind, slot);
  });
}

function bucketsOverlap(axis, buckets) {
  const keys = new Set((buckets ?? []).map((bucket) => String(bucket.key)));
  return axis.some((slot) => keys.has(slot.key));
}

function bucketHasData(kind, bucket) {
  if (!bucket) return false;
  if (kind === 'usage') return usageCount(bucket) > 0;
  if (kind === 'accuracy') {
    return (Number(bucket.sampleCount) || 0) > 0
      || Number.isFinite(bucket.voice)
      || Number.isFinite(bucket.motion)
      || Number.isFinite(bucket.gaze);
  }
  if (kind === 'latency') {
    return (Number(bucket.simpleCount) || 0) + (Number(bucket.complexCount) || 0) > 0
      || Number.isFinite(bucket.simpleMs)
      || Number.isFinite(bucket.complexMs);
  }
  return false;
}

function summaryFromBuckets(kind, buckets, fallback) {
  if (kind === 'usage') {
    const voiceTotal = buckets.reduce((sum, bucket) => sum + (Number(bucket.voice) || 0), 0);
    const gestureTotal = buckets.reduce((sum, bucket) => sum + (Number(bucket.gesture) || 0), 0);
    return { total: voiceTotal + gestureTotal, voiceTotal, gestureTotal };
  }
  if (kind === 'accuracy') {
    const mean = (key) => {
      const values = buckets.map((bucket) => bucket[key]).filter((value) => Number.isFinite(value));
      if (!values.length) return null;
      return values.reduce((sum, value) => sum + value, 0) / values.length;
    };
    return {
      voice: mean('voice'),
      motion: mean('motion'),
      gaze: mean('gaze'),
      sampleCount: buckets.reduce((sum, bucket) => sum + (Number(bucket.sampleCount) || 0), 0),
    };
  }
  if (kind === 'latency') {
    const simple = buckets.map((bucket) => bucket.simpleMs).filter((value) => Number.isFinite(value));
    const complex = buckets.map((bucket) => bucket.complexMs).filter((value) => Number.isFinite(value));
    const simpleMs = simple.length ? simple.reduce((sum, value) => sum + value, 0) / simple.length : null;
    const complexMs = complex.length ? complex.reduce((sum, value) => sum + value, 0) / complex.length : null;
    return {
      simpleMs,
      complexMs,
      overallMs: simpleMs != null && complexMs != null ? (simpleMs + complexMs) / 2 : simpleMs ?? complexMs,
      simpleCount: buckets.reduce((sum, bucket) => sum + (Number(bucket.simpleCount) || 0), 0),
      complexCount: buckets.reduce((sum, bucket) => sum + (Number(bucket.complexCount) || 0), 0),
    };
  }
  return fallback ?? {};
}

function summaryFromSample(kind, bucket) {
  if (!bucket) return {};
  if (kind === 'usage') {
    const voiceTotal = Number(bucket.voice) || 0;
    const gestureTotal = Number(bucket.gesture) || 0;
    return { total: usageCount(bucket), voiceTotal, gestureTotal };
  }
  if (kind === 'accuracy') {
    return { voice: bucket.voice ?? null, motion: bucket.motion ?? null, gaze: bucket.gaze ?? null, sampleCount: bucket.sampleCount ?? 0 };
  }
  if (kind === 'latency') {
    const simpleMs = bucket.simpleMs ?? null;
    const complexMs = bucket.complexMs ?? null;
    return {
      simpleMs,
      complexMs,
      overallMs: simpleMs != null && complexMs != null ? (simpleMs + complexMs) / 2 : simpleMs ?? complexMs,
      simpleCount: bucket.simpleCount ?? 0,
      complexCount: bucket.complexCount ?? 0,
    };
  }
  return {};
}

function applyAnchor(kind, period, data, selection) {
  const axis = axisForPeriod(period, selection?.key);
  if (!axis || !data) return data;
  const aligned = alignBuckets(kind, axis, data.buckets);
  if (bucketsOverlap(axis, data.buckets)) {
    return { ...data, buckets: aligned, summary: summaryFromBuckets(kind, aligned, data.summary) };
  }
  return { ...data, buckets: aligned, summary: summaryFromSample(kind, selection.bucket) };
}

function bucketAnchor(bucket, period, currentAnchor = '') {
  const key = String(bucket?.key ?? '');
  if (key) return key;
  const label = String(bucket?.label ?? '');
  const week = label.match(/(\d{1,2})월\s*(\d)주차/);
  if (week) {
    const year = String(currentAnchor).match(/(20\d{2})/) ? currentAnchor.slice(0, 4) : String(new Date().getFullYear());
    const day = [1, 7, 14, 21, 28][Number(week[2]) - 1] ?? 1;
    return `${year}-${pad2(Number(week[1]))}-${pad2(day)}`;
  }
  const month = label.match(/(\d{1,2})월/);
  if (period === 'year' && month) {
    const year = String(currentAnchor).match(/(20\d{2})/) ? currentAnchor.slice(0, 4) : String(new Date().getFullYear());
    return `${year}-${pad2(Number(month[1]))}`;
  }
  return label;
}

export default function DashboardHome() {
  const location = useLocation(); const navigate = useNavigate();
  const query = new URLSearchParams(location.search);
  const requestedView = query.get('view');
  const view = views.includes(requestedView) ? requestedView : 'home';
  const historyStack = Array.isArray(location.state?.dashboardHistory) ? location.state.dashboardHistory : [];
  const registration = useGestureStore((state) => state.registration);
  const [menu, setMenu] = useState(false); const [overview, setOverview] = useState(null); const [detail, setDetail] = useState(null); const [period, setPeriod] = useState('week'); const [anchor, setAnchor] = useState(null); const [loading, setLoading] = useState(false); const [error, setError] = useState('');
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
    setDetail(null);
    // TODO(BE): GET /api/dashboard/* 는 period만 받고 선택한 날짜(anchor)를 무시함. 명세에 기간 파라미터가 생기면 그 값을 그대로 전달할 것
    load(() => fetchers[view](period).then((data) => applyAnchor(view, period, data, anchor)), setDetail);
    return undefined;
  }, [view, period, anchor]);
  async function load(fetcher, setter) { setLoading(true); setError(''); try { setter(await fetcher()); } catch (requestError) { setError(requestError.message); } finally { setLoading(false); } }
  function loadHome() {
    load(async () => {
      const overview = await fetchDashboardOverview();
      // TODO(BE): overview.topApps 는 오늘(day)만이라 주간 사용량 카드와 기간이 다름. 명세에 주간 필드가 생기면 /apps?period=week 호출을 제거할 것
      const apps = await fetchDashboardApps('week');
      return { ...overview, topApps: Array.isArray(apps.items) && apps.items.length ? apps.items : (overview.topApps ?? []) };
    }, setOverview);
  }
  const href = (next) => {
    const params = new URLSearchParams();
    if (next && next !== 'home') params.set('view', next);
    const search = params.toString();
    return search ? `/dashboard?${search}` : '/dashboard';
  };
  const open = (next) => {
    if (next !== 'gestures') useGestureStore.getState().closeRegistration();
    setMenu(false); setError('');
    if (details[next]) { setPeriod('week'); setAnchor(null); setDetail(null); }
    const nextHistory = next === 'home' || view === next ? (next === 'home' ? [] : historyStack) : [...historyStack, view];
    navigate(href(next), { state: { dashboardHistory: nextHistory } });
  };
  const registrationTitle = registration?.stage === 'complete' || registration?.stage === 'form' ? '제스처 등록' : registration?.stage === 'review' ? '촬영 결과' : '제스처 촬영';
  const panelTitle = view === 'gestures' ? (registration ? registrationTitle : '제스처') : view === 'voice' ? '보이스' : view === 'gaze' ? '시선' : view === 'settings' ? '설정' : '';
  const back = () => {
    if (view === 'gestures' && registration) { useGestureStore.getState().closeRegistration(); return; }
    const previous = historyStack[historyStack.length - 1];
    const rest = historyStack.slice(0, -1);
    if (previous && previous !== view && views.includes(previous)) {
      if (view !== 'gestures') useGestureStore.getState().closeRegistration();
      navigate(href(previous), { replace: true, state: { dashboardHistory: rest } });
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
      {((view === 'gestures' && !registration) || view === 'settings') && <div className={styles.panelHeading}><button onClick={back} aria-label="이전 화면으로 돌아가기">‹</button><h1>{panelTitle}</h1></div>}
      {view === 'gestures' && <GesturePanel />}{view === 'voice' && <VoicePanel onBack={back} />}{view === 'gaze' && <GazePanel onBack={back} />}{view === 'settings' && <SettingsPanel onBack={back} />}
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
  const buckets = (data.usage?.buckets ?? []).map((bucket) => ({ ...bucket, count: usageCount(bucket) })); const maxUsage = Math.max(1, ...buckets.map((item) => item.count ?? 0)); const apps = data.topApps ?? []; const maxApps = Math.max(1, ...apps.map((item) => item.count));
  return <><div className={styles.homeHead}><Intro title="SIA 대시보드" description="AI가 더 편리한 일상을 만들어갑니다." /><p className={styles.homeMark}>SMART INTERACTION ASSISTANT</p></div>
    <div className={styles.overviewGrid}>
      <button className={`${styles.dashboardCard} ${styles.usageOverview}`} onClick={() => open('usage')}><Label overline="USAGE" title="제스처 / 보이스 사용량" description="최근 7일 사용 현황 · 음성 AI, 제스처를 보기" /><span className={styles.cardMeta}>VOICE / GESTURE</span><div className={styles.overviewBars}>{buckets.map((item) => <span key={item.key}><i className={item.count > 0 ? undefined : styles.emptyBar} style={{ height: item.count > 0 ? `${Math.max(8, item.count / maxUsage * 86)}%` : 0 }} /><small>{item.label}</small></span>)}</div><i className={styles.hudTicks} /></button>
      <div className={styles.overviewSide}>
        <button className={`${styles.dashboardCard} ${styles.accuracyOverview}`} onClick={() => open('accuracy')}><Label overline="AI STATUS" title="인식 정확도" /><span className={styles.cardMeta}>SIA ONLINE</span><div className={styles.accuracyRings}>{accuracy.map(([label, value]) => <span key={label}><i style={{ '--accuracy': `${(value ?? 0) * 360}deg` }}><strong>{value == null ? '–' : `${Math.round(value * 100)}%`}</strong></i><small>{label}</small></span>)}</div></button>
        <button className={`${styles.dashboardCard} ${styles.latencyOverview}`} onClick={() => open('latency')}><Label overline="RESPONSE" title="평균 응답 시간" /><span className={styles.cardMeta}>REAL-TIME</span><div><span className={styles.metric}><LatencyIcon kind="simple" /><small>간단한 작업</small><strong>{seconds(data.latency?.simpleMs)}</strong></span><span className={styles.metric}><LatencyIcon kind="complex" /><small>복잡한 작업</small><strong>{seconds(data.latency?.complexMs)}</strong></span></div></button>
      </div>
      <button className={`${styles.dashboardCard} ${styles.appsOverview}`} onClick={() => open('apps')}><Label overline="TOP PROGRAMS" title="자주 사용하는 프로그램" /><span className={styles.cardMeta}>FREQUENCY</span><div>{apps.length ? apps.slice(0, 4).map((item) => <span key={item.appKey}><AppIcon name={item.displayName} /><em>{item.displayName}</em><i><u style={{ width: `${item.count / maxApps * 100}%` }} /></i><strong>{Math.round(item.count / maxApps * 100)}%</strong></span>) : <Empty />}</div><i className={`${styles.hudTicks} ${styles.hudTicksEnd}`} /></button>
    </div></>;
}

function Detail({ kind, data, period, setPeriod, open, loading, anchor, onBucket }) {
  if (!data) return null; const buckets = (data.buckets ?? []).map((bucket) => {
    const labeled = period === 'month' ? { ...bucket, label: monthAxisLabel(bucket) } : bucket;
    return kind === 'usage' ? { ...labeled, count: usageCount(labeled) } : labeled;
  }); const summary = data.summary ?? {};
  // TODO(BE): 선택한 과거 월·일을 기준으로 조회할 anchor 파라미터가 명세에 추가되면 선택 bucket key를 API에 전달 필요
  const canDrill = Boolean(nextPeriod[period]) && !loading;
  const drillDown = (bucket) => {
    if (!canDrill || !bucketHasData(kind, bucket)) return;
    onBucket({ key: bucketAnchor(bucket, period, anchor?.key ?? ''), bucket });
    setPeriod(nextPeriod[period] ?? period);
  };
  const choosePeriod = (next) => { onBucket(null); setPeriod(next); };
  return <><div className={styles.detailHead}><button className={styles.detailBack} onClick={() => open('home')}>‹</button><Intro eyebrow="분석" title={details[kind][0]} description={details[kind][1]} /><Periods period={period} setPeriod={choosePeriod} /></div>
    <section className={`${styles.largeCard} ${styles[`chart_${kind}`]} ${styles[`period_${period}`]}`}><ChartHeading kind={kind} period={period} />
      {kind !== 'apps' && <Legend items={kind === 'accuracy' ? ['음성 인식', '모션인식'] : kind === 'latency' ? ['간단한 작업', '복잡한 작업'] : ['보이스', '제스처', '전체 사용량']} />}
      <div className={styles.chartStage}>
        {kind === 'accuracy' && <BarChart buckets={buckets} series={[{ key: 'voice' }, { key: 'motion' }]} valueFormatter={(value) => `${Math.round(value * 100)}%`} onBucketClick={canDrill ? drillDown : undefined} />}
        {kind === 'latency' && <BarChart buckets={buckets} series={[{ key: 'simpleMs' }, { key: 'complexMs' }]} valueFormatter={(value) => `${(value / 1000).toFixed(1)}s`} onBucketClick={canDrill ? drillDown : undefined} />}
        {kind === 'usage' && <BarChart buckets={buckets} series={[{ key: 'voice' }, { key: 'gesture' }, { key: 'count' }]} minimumMax={4} valueFormatter={(value) => Math.round(value)} onBucketClick={canDrill ? drillDown : undefined} />}
        {kind === 'apps' && ((data.items ?? []).length ? <HorizontalBars items={data.items} /> : <Empty />)}
      </div>
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
  if (kind === 'accuracy' && index === 1) {
    return <img className={styles.summaryGlyph} src={navGestures} alt="" aria-hidden="true" />;
  }
  if (kind === 'usage' && index < 2) {
    return <svg className={styles.summaryWave} viewBox="0 0 80 40" aria-hidden="true"><path d="M4 22h14l3-12 4 22 4-16 4 10 3-6 3 4h21l4-8 4 10 4-4h8" /></svg>;
  }
  return <svg className={styles.summaryBars} viewBox="0 0 56 44" aria-hidden="true"><rect x="6" y="20" width="12" height="20" rx="3" /><rect className={styles.barMid} x="22" y="6" width="12" height="34" rx="3" /><rect x="38" y="14" width="12" height="26" rx="3" /></svg>;
}
function LatencyIcon({ kind }) {
  if (kind === 'complex') {
    return <svg className={styles.latencyIcon} viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="12" r="2.2" /><circle cx="18" cy="7" r="2.2" /><circle cx="18" cy="17" r="2.2" /><path d="M8 12h8M16.2 8.6 8.8 11.2M16.2 15.4 8.8 12.8" /></svg>;
  }
  return <svg className={styles.latencyIcon} viewBox="0 0 24 24" aria-hidden="true"><path d="M13 2 4 14h7l-1 8 10-12h-7l0-8Z" /></svg>;
}
function AppIcon({ name = '' }) {
  const normalized = name.toLowerCase();
  if (normalized.includes('chrome') || normalized.includes('크롬')) return <svg className={styles.appIcon} viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="4" /><path d="M3.5 7h9M8 21l4-9M21 12h-9" /></svg>;
  if (normalized.includes('slack') || normalized.includes('슬랙')) return <svg className={styles.appIcon} viewBox="0 0 24 24"><path d="M9 3v7M9 14v2a3 3 0 1 1-3-3h2M15 21v-7M15 10V8a3 3 0 1 1 3 3h-2M3 15h7M14 15h2a3 3 0 1 1-3 3v-2M21 9h-7M10 9H8a3 3 0 1 1 3-3v2" /></svg>;
  if (normalized.includes('탐색') || normalized.includes('explorer')) return <svg className={styles.appIcon} viewBox="0 0 24 24"><path d="M2 7h8l2 2h10v11H2Z" /><path d="M2 7V4h8l2 3" /></svg>;
  return <svg className={styles.appIcon} viewBox="0 0 24 24"><rect x="4" y="2" width="16" height="20" rx="2" /><path d="M8 7h8M8 11h8M8 15h6" /></svg>;
}
function Empty() { return <p className={styles.empty}>아직 표시할 활동 데이터가 없습니다.</p>; }
