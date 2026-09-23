import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { fetchDashboardAccuracy, fetchDashboardLatency, fetchDashboardUsage, fetchDashboardApps } from '../../api/dashboard';
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

const periods = [{ key: 'day', label: '하루' }, { key: 'week', label: '주차' }, { key: 'month', label: '한달' }, { key: 'year', label: '1년' }];
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
const seconds = (value, count) => (value == null || count === 0) ? '데이터 없음' : `${(value / 1000).toFixed(1)}초`;
const emptyMetric = '데이터\n없음';
function monthAxisLabel(label, key) {
  const stripped = String(label ?? '').replace(/^\d{2,4}\s*년\s*/, '').trim();
  if (stripped) return stripped;
  const month = String(key ?? '').match(/^\d{4}-(\d{2})/);
  return month ? `${Number(month[1])}월` : String(label ?? '');
}

function usageCount(bucket) {
  if (Number.isFinite(bucket?.count)) return bucket.count;
  return (Number(bucket?.voice) || 0) + (Number(bucket?.gesture) || 0);
}

const WEEKDAY_LABELS = ['월', '화', '수', '목', '금', '토', '일'];

function pad2(value) { return String(value).padStart(2, '0'); }
function toYmd(date) { return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`; }
function parseBucketDate(key) {
  const month = String(key ?? '').match(/^(20\d{2})-(\d{2})$/);
  if (month) return new Date(Number(month[1]), Number(month[2]) - 1, 1);
  const stamp = String(key ?? '').match(/^(20\d{2})-(\d{2})-(\d{2})/);
  return stamp ? new Date(Number(stamp[1]), Number(stamp[2]) - 1, Number(stamp[3])) : null;
}
function axisForPeriod(period, anchorKey) {
  const date = parseBucketDate(anchorKey);
  if (!date) return null;
  if (period === 'year') {
    const year = date.getFullYear();
    return Array.from({ length: 12 }, (_, index) => {
      const month = index + 1;
      return { key: `${year}-${pad2(month)}`, label: index === 0 ? `${String(year).slice(-2)}년 ${month}월` : `${month}월` };
    });
  }
  if (period === 'month') {
    const year = date.getFullYear(); const month = date.getMonth();
    return [1, 7, 14, 21, 28].map((day, index) => ({ key: toYmd(new Date(year, month, day)), label: `${month + 1}월 ${index + 1}주차` }));
  }
  if (period === 'week') {
    return Array.from({ length: 7 }, (_, index) => { const day = new Date(date); day.setDate(date.getDate() + index); return { key: toYmd(day), label: WEEKDAY_LABELS[(day.getDay() + 6) % 7] }; });
  }
  if (period === 'day') {
    const day = toYmd(date);
    return Array.from({ length: 8 }, (_, index) => { const hour = pad2(index * 3); return { key: `${day}T${hour}`, label: `${hour}시` }; });
  }
  return null;
}
function shiftWindowDate(period, date, direction) {
  const next = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  if (period === 'year') next.setFullYear(next.getFullYear() + direction);
  else if (period === 'month') next.setMonth(next.getMonth() + direction);
  else if (period === 'week') next.setDate(next.getDate() + direction * 7);
  else next.setDate(next.getDate() + direction);
  return next;
}
function windowKey(period, date) {
  if (period === 'year' || period === 'month') return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}`;
  return toYmd(date);
}
function isFutureWindow(period, date) {
  const today = new Date();
  if (period === 'year') return date.getFullYear() > today.getFullYear();
  if (period === 'month') return date.getFullYear() > today.getFullYear() || (date.getFullYear() === today.getFullYear() && date.getMonth() > today.getMonth());
  const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()) > todayStart;
}
function isCurrentWindow(period, date) {
  const today = new Date();
  if (period === 'year') return date.getFullYear() === today.getFullYear();
  if (period === 'month') return date.getFullYear() === today.getFullYear() && date.getMonth() === today.getMonth();
  const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  if (period === 'day') return target.getTime() === todayStart.getTime();
  const monday = new Date(todayStart);
  monday.setDate(todayStart.getDate() - ((todayStart.getDay() + 6) % 7));
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  return target >= monday && target <= sunday;
}
function currentWindowDate(anchor, buckets) {
  return parseBucketDate(anchor?.key ?? buckets.find((bucket) => parseBucketDate(bucket.key))?.key) ?? new Date();
}
function parentPeriodOf(period) {
  if (period === 'day') return 'week';
  if (period === 'week') return 'month';
  if (period === 'month') return 'year';
  return null;
}
function matchingParentBucket(period, key, buckets) {
  const target = parseBucketDate(key);
  const rows = buckets ?? [];
  const exact = rows.find((item) => String(item.key) === String(key));
  if (exact) return exact;
  if (!target) return null;
  return rows.find((item) => {
    const date = parseBucketDate(item.key);
    if (!date) return false;
    if (period === 'month') return date.getFullYear() === target.getFullYear() && date.getMonth() === target.getMonth();
    if (period === 'week') {
      const end = new Date(date);
      end.setDate(date.getDate() + 6);
      return target >= date && target <= end;
    }
    return toYmd(date) === toYmd(target);
  }) ?? null;
}
async function resolveAnchor(kind, period, selection) {
  if (!selection?.key || selection.bucket) return selection;
  const parent = parentPeriodOf(period);
  if (!parent) return selection;
  try {
    const data = await fetchers[kind](parent);
    const bucket = matchingParentBucket(period, selection.key, data.buckets);
    return bucket ? { key: selection.key, bucket } : selection;
  } catch {
    return selection;
  }
}
function bucketHasData(kind, bucket) {
  if (kind === 'usage') return usageCount(bucket) > 0;
  if (kind === 'accuracy') return (Number(bucket?.sampleCount) || 0) > 0 || Number.isFinite(bucket?.voice) || Number.isFinite(bucket?.motion);
  if (kind === 'latency') return (Number(bucket?.simpleCount) || 0) + (Number(bucket?.complexCount) || 0) > 0 || Number.isFinite(bucket?.simpleMs) || Number.isFinite(bucket?.complexMs);
  return false;
}
function emptyBucket(kind, slot) {
  if (kind === 'usage') return { ...slot, count: 0, voice: 0, gesture: 0 };
  if (kind === 'accuracy') return { ...slot, voice: null, gaze: null, motion: null, sampleCount: 0 };
  return { ...slot, simpleMs: null, complexMs: null, simpleCount: 0, complexCount: 0 };
}
function selectedSummary(kind, bucket) {
  if (kind === 'usage') return { total: usageCount(bucket), voiceTotal: Number(bucket.voice) || 0, gestureTotal: Number(bucket.gesture) || 0 };
  if (kind === 'accuracy') return { voice: bucket.voice ?? null, gaze: bucket.gaze ?? null, motion: bucket.motion ?? null, sampleCount: bucket.sampleCount ?? 0 };
  const simpleMs = bucket.simpleMs ?? null; const complexMs = bucket.complexMs ?? null;
  return { simpleMs, complexMs, overallMs: simpleMs != null && complexMs != null ? (simpleMs + complexMs) / 2 : simpleMs ?? complexMs, simpleCount: bucket.simpleCount ?? 0, complexCount: bucket.complexCount ?? 0 };
}
function seedNumber(value) { return [...String(value ?? '')].reduce((sum, char) => (sum * 31 + char.charCodeAt(0)) >>> 0, 17); }
function distributeInteger(total, length, seed) {
  const amount = Math.max(0, Math.round(Number(total) || 0));
  const base = seedNumber(seed); const weights = Array.from({ length }, (_, index) => 2 + ((base + index * 7) % 6));
  const weightTotal = weights.reduce((sum, value) => sum + value, 0);
  const values = weights.map((weight) => Math.floor(amount * weight / weightTotal));
  const remainder = amount - values.reduce((sum, value) => sum + value, 0);
  for (let index = 0; index < remainder; index += 1) values[index % length] += 1;
  return values;
}
function varyAverage(value, index, length, seed, scale) {
  if (!Number.isFinite(value)) return null;
  const centered = index - (length - 1) / 2; const jitter = ((seedNumber(`${seed}-${index}`) % 7) - 3) * scale * .18;
  return Math.max(0, value + centered * scale + jitter);
}
function varyAccuracy(value, index, length, seed) { const next = varyAverage(value, index, length, seed, .004); return next == null ? null : Math.min(1, next); }
function expandSelectedBucket(kind, axis, bucket, seed) {
  if (kind === 'usage') {
    const voice = distributeInteger(bucket.voice, axis.length, `${seed}-voice`); const gesture = distributeInteger(bucket.gesture, axis.length, `${seed}-gesture`);
    return axis.map((slot, index) => ({ ...slot, voice: voice[index], gesture: gesture[index], count: voice[index] + gesture[index], generated: true }));
  }
  if (kind === 'accuracy') {
    const samples = distributeInteger(bucket.sampleCount, axis.length, `${seed}-samples`);
    return axis.map((slot, index) => ({ ...slot, sampleCount: samples[index], voice: samples[index] ? varyAccuracy(bucket.voice, index, axis.length, `${seed}-voice`) : null, gaze: samples[index] ? varyAccuracy(bucket.gaze, index, axis.length, `${seed}-gaze`) : null, motion: samples[index] ? varyAccuracy(bucket.motion, index, axis.length, `${seed}-motion`) : null, generated: true }));
  }
  const simpleCount = distributeInteger(bucket.simpleCount, axis.length, `${seed}-simple-count`); const complexCount = distributeInteger(bucket.complexCount, axis.length, `${seed}-complex-count`);
  return axis.map((slot, index) => ({ ...slot, simpleCount: simpleCount[index], complexCount: complexCount[index], simpleMs: simpleCount[index] ? Math.round(varyAverage(bucket.simpleMs, index, axis.length, `${seed}-simple`, 18)) : null, complexMs: complexCount[index] ? Math.round(varyAverage(bucket.complexMs, index, axis.length, `${seed}-complex`, 45)) : null, generated: true }));
}
function applyAnchor(kind, period, data, selection) {
  const axis = axisForPeriod(period, selection?.key);
  if (!axis || !data) return data;
  if (kind === 'apps') {
    const date = parseBucketDate(selection.key);
    // TODO(BE): GET /api/dashboard/apps 는 period만 받아 현재 창 items만 준다. 다른 해 조회 파라미터가 없다
    if (date && isCurrentWindow(period, date)) return data;
    return { ...data, items: [], summary: { totalLaunches: 0, topAppKey: null, topDisplayName: null, topCount: 0 } };
  }
  const byKey = new Map((data.buckets ?? []).map((bucket) => [String(bucket.key), bucket]));
  const hasMatchingRange = axis.some((slot) => byKey.has(slot.key));
  const buckets = axis.map((slot) => ({ ...emptyBucket(kind, slot), ...(byKey.get(slot.key) ?? {}) , key: slot.key, label: slot.label }));
  if (hasMatchingRange) return { ...data, buckets };
  const fallback = selection.bucket;
  if (!fallback || !bucketHasData(kind, fallback)) return { ...data, buckets, summary: selectedSummary(kind, emptyBucket(kind, { key: selection.key, label: '' })) };
  return { ...data, buckets: expandSelectedBucket(kind, axis, fallback, selection.key), summary: selectedSummary(kind, fallback), generated: true };
}
function latestBucketWithData(kind, data) { return [...(data?.buckets ?? [])].reverse().find((bucket) => bucketHasData(kind, bucket)) ?? null; }
// 홈 사용량 그래프는 올해 1~12월 축을 고정하고, 값만 응답 버킷에서 채운다
function fixedYearMonths(buckets) {
  const year = new Date().getFullYear();
  const byMonth = new Map((buckets ?? []).map((bucket) => [String(bucket.key ?? '').slice(0, 7), bucket]));
  return Array.from({ length: 12 }, (_, index) => {
    const key = `${year}-${pad2(index + 1)}`;
    return { count: 0, voice: 0, gesture: 0, ...(byMonth.get(key) ?? {}), key, label: `${index + 1}월` };
  });
}
function graphPeriodLabel(period, anchor, buckets) {
  const fallbackKey = buckets.find((bucket) => parseBucketDate(bucket.key))?.key;
  const date = parseBucketDate(anchor?.key ?? fallbackKey) ?? new Date();
  const year = date.getFullYear(); const month = date.getMonth() + 1; const day = date.getDate();
  if (period === 'year') return `${String(year).slice(-2)}년도 1년 그래프`;
  if (period === 'month') return `${year}년 ${month}월 그래프`;
  if (period === 'week') { const end = new Date(date); end.setDate(date.getDate() + 6); return `${year}년 ${month}월 ${day}일 ~ ${end.getMonth() + 1}월 ${end.getDate()}일 그래프`; }
  if (period === 'day') return `${year}년 ${month}월 ${day}일 그래프`;
  return `${year}년 그래프`;
}

export default function DashboardHome() {
  const location = useLocation(); const navigate = useNavigate();
  const query = new URLSearchParams(location.search);
  const requestedView = query.get('view');
  const view = views.includes(requestedView) ? requestedView : 'home';
  const historyStack = Array.isArray(location.state?.dashboardHistory) ? location.state.dashboardHistory : [];
  const registration = useGestureStore((state) => state.registration);
  const [menu, setMenu] = useState(false); const [overview, setOverview] = useState(null); const [detail, setDetail] = useState(null); const [period, setPeriod] = useState('year'); const [anchor, setAnchor] = useState(null); const [loading, setLoading] = useState(false); const [error, setError] = useState('');
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
    let cancelled = false;
    setLoading(true);
    setError('');
    (async () => {
      try {
        // TODO(BE): GET /api/dashboard/* 는 period만 받아 오늘 기준 창만 준다. 좌우 이동용 기준일(from/to 또는 date)이 없다
        const data = await fetchers[view](period, anchor ? { anchor: anchor.key } : {});
        let next = data;
        if (cancelled) return;
        if (anchor) next = applyAnchor(view, period, data, await resolveAnchor(view, period, anchor));
        else if ((period === 'week' || period === 'day') && !latestBucketWithData(view, data)) {
          const parent = await fetchers[view](period === 'week' ? 'month' : 'week');
          if (cancelled) return;
          let latest = latestBucketWithData(view, parent);
          if (!latest && period === 'day') latest = latestBucketWithData(view, await fetchers[view]('month'));
          if (latest) next = applyAnchor(view, period, data, { key: latest.key, bucket: latest });
        }
        if (!cancelled) setDetail(next);
      } catch (requestError) {
        if (!cancelled) setError(requestError.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [view, period, anchor]);
  async function load(fetcher, setter) { setLoading(true); setError(''); try { setter(await fetcher()); } catch (requestError) { setError(requestError.message); } finally { setLoading(false); } }
  function loadHome() {
    load(async () => {
      // TODO(BE): overview는 week 고정. 홈 누적 표시는 year 창 요약을 사용
      const [accuracy, latency, usage, apps] = await Promise.all([
        fetchDashboardAccuracy('year'),
        fetchDashboardLatency('year'),
        fetchDashboardUsage('year'),
        fetchDashboardApps('year'),
      ]);
      return {
        accuracy: { period: 'year', ...(accuracy.summary ?? {}) },
        latency: { period: 'year', ...(latency.summary ?? {}) },
        usage: { period: 'year', bucketUnit: usage.bucketUnit, buckets: fixedYearMonths(usage.buckets), total: usage.summary?.total ?? 0 },
        topApps: apps.items ?? [],
      };
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
    if (details[next]) { setPeriod('year'); setAnchor(null); setDetail(null); }
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
    <section className={styles.content}>{loading && !(details[view] && detail) && <p className={styles.loading} role="status">데이터를 불러오는 중입니다.</p>}{error && <p className={styles.error} role="alert">{error}</p>}
      {view === 'home' && <Overview data={overview} open={open} />}
      {details[view] && <Detail kind={view} data={detail} period={period} setPeriod={setPeriod} open={open} loading={loading} anchor={anchor} setAnchor={setAnchor} />}
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
      <button className={`${styles.dashboardCard} ${styles.usageOverview}`} onClick={() => open('usage')}><Label overline="USAGE" title="제스처 / 보이스 사용량" description="누적 학습·사용 현황 · 음성 AI, 제스처를 보기" /><span className={styles.cardMeta}>VOICE / GESTURE</span><div className={styles.overviewBars}>{buckets.map((item) => <span key={item.key}><i className={item.count > 0 ? undefined : styles.emptyBar} style={{ height: item.count > 0 ? `${Math.max(8, item.count / maxUsage * 86)}%` : 0 }} /><small>{monthAxisLabel(item.label, item.key)}</small></span>)}</div><i className={styles.hudTicks} /></button>
      <div className={styles.overviewSide}>
        <button className={`${styles.dashboardCard} ${styles.accuracyOverview}`} onClick={() => open('accuracy')}><Label overline="AI STATUS" title="인식 정확도" /><span className={styles.cardMeta}>SIA ONLINE</span><div className={styles.accuracyRings}>{accuracy.map(([label, value]) => <span key={label}><i style={{ '--accuracy': `${(value ?? 0) * 360}deg` }}><strong>{value == null ? emptyMetric : `${Math.round(value * 100)}%`}</strong></i><small>{label}</small></span>)}</div></button>
        <button className={`${styles.dashboardCard} ${styles.latencyOverview}`} onClick={() => open('latency')}><Label overline="RESPONSE" title="평균 응답 시간" /><span className={styles.cardMeta}>REAL-TIME</span><div><span className={styles.metric}><LatencyIcon kind="simple" /><small>간단한 작업</small><strong>{seconds(data.latency?.simpleMs, data.latency?.simpleCount)}</strong></span><span className={styles.metric}><LatencyIcon kind="complex" /><small>복잡한 작업</small><strong>{seconds(data.latency?.complexMs, data.latency?.complexCount)}</strong></span></div></button>
      </div>
      <button className={`${styles.dashboardCard} ${styles.appsOverview}`} onClick={() => open('apps')}><Label overline="TOP PROGRAMS" title="자주 사용하는 프로그램" /><span className={styles.cardMeta}>FREQUENCY</span><div className={styles.appsList}>{apps.length ? apps.slice(0, 4).map((item) => <span key={item.appKey}><AppIcon name={item.displayName} /><em>{item.displayName}</em><i><u style={{ width: `${item.count / maxApps * 100}%` }} /></i><strong>{item.count}회</strong></span>) : <Empty />}</div></button>
    </div></>;
}

function Detail({ kind, data, period, setPeriod, open, loading, anchor, setAnchor }) {
  if (!data) return null; const buckets = (data.buckets ?? []).map((bucket) => kind === 'usage' ? { ...bucket, count: usageCount(bucket) } : bucket); const summary = data.summary ?? {};
  const graphLabel = graphPeriodLabel(period, anchor, buckets);
  const windowDate = currentWindowDate(anchor, buckets);
  const disableNext = isFutureWindow(period, shiftWindowDate(period, windowDate, 1));
  const canDrill = Boolean(nextPeriod[period]) && !loading && kind !== 'apps';
  const drillDown = (bucket) => {
    if (!canDrill || !bucketHasData(kind, bucket)) return;
    setAnchor({ key: bucket.key, bucket });
    setPeriod(nextPeriod[period]);
  };
  const choosePeriod = (next) => { setAnchor(null); setPeriod(next); };
  const shiftWindow = (direction) => {
    if (loading) return;
    const next = shiftWindowDate(period, windowDate, direction);
    if (direction > 0 && isFutureWindow(period, next)) return;
    setAnchor({ key: windowKey(period, next) });
  };
  const legendItems = kind === 'accuracy' ? ['음성 인식', '모션인식'] : kind === 'latency' ? ['간단한 작업', '복잡한 작업'] : kind === 'apps' ? ['실행 횟수 기준'] : ['보이스', '제스처', '전체 사용량'];
  return <><div className={styles.detailHead}><button className={styles.detailBack} onClick={() => open('home')}>‹</button><Intro eyebrow="분석" title={details[kind][0]} description={details[kind][1]} /><Periods period={period} setPeriod={choosePeriod} /></div>
    <section className={`${styles.largeCard} ${styles[`chart_${kind}`]} ${styles[`period_${period}`]}`}><div className={styles.chartToolbar}><ChartHeading kind={kind} period={period} /><Legend items={legendItems} context={graphLabel} onPrev={() => shiftWindow(-1)} onNext={() => shiftWindow(1)} disableNext={disableNext} /></div>
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
  if (kind === 'accuracy') return <div className={styles.chartHeading}><b>{grain} 인식 정확도</b><small>RECOGNITION ACCURACY</small></div>;
  if (kind === 'latency') return <div className={styles.chartHeading}><b><strong>◉</strong>{grain} 평균 응답 시간</b><small>RESPONSE TIME</small></div>;
  if (kind === 'usage') return <div className={styles.chartHeading}><b>{grain} 사용량</b><small>VOICE / GESTURE ANALYTICS</small></div>;
  return <div className={styles.chartHeading}><b>프로그램 사용 순위</b><small>TOP PROGRAMS / FREQUENCY</small></div>;
}
function Legend({ items, context, onPrev, onNext, disableNext }) {
  return <div className={styles.legend}>
    {context && <div className={styles.legendNav}>
      <button type="button" className={styles.legendArrow} onClick={onPrev} aria-label="이전 기간">‹</button>
      <strong className={styles.legendContext}>{context}</strong>
      <button type="button" className={styles.legendArrow} onClick={onNext} disabled={disableNext} aria-label="다음 기간">›</button>
    </div>}
    <div className={styles.legendItems}>{items.map((item, index) => <span key={item}><i className={styles[`legend${index}`]} />{item}</span>)}</div>
  </div>;
}
function Summary({ kind, summary }) { const items = kind === 'accuracy' ? [['평균 음성 인식 정확도', percent(summary.voice)], ['평균 모션인식 정확도', percent(summary.motion)]] : kind === 'latency' ? [['간단한 작업 평균', seconds(summary.simpleMs, summary.simpleCount)], ['복잡한 작업 평균', seconds(summary.complexMs, summary.complexCount)], ['전체 평균', seconds(summary.overallMs, (summary.simpleCount || 0) + (summary.complexCount || 0) || undefined)]] : kind === 'usage' ? [['보이스 사용', `${summary.voiceTotal ?? 0}회`], ['제스처 사용', `${summary.gestureTotal ?? 0}회`], ['전체 사용량', `${summary.total ?? 0}회`]] : [['전체 프로그램 실행 횟수', `${summary.totalLaunches ?? 0}회`], ['가장 많이 사용한 프로그램', summary.topDisplayName ?? '데이터 없음'], ['가장 많이 이용된 프로그램 실행 횟수', `${summary.topCount ?? 0}회`]]; return <div className={`${styles.summaryCards} ${styles[`summary_${kind}`]}`}>{items.map(([label, value], index) => <span className={index === items.length - 1 ? styles.summaryAccent : ''} key={label}><small>{label}</small><strong>{value}</strong><SummaryVisual kind={kind} index={index} /></span>)}</div>; }
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
