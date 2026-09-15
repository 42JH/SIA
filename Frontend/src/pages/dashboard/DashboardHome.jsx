import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { fetchDashboardAccuracy, fetchDashboardApps, fetchDashboardLatency, fetchDashboardOverview, fetchDashboardUsage } from '../../api/dashboard';
import { BarChart, HorizontalBars, LineChart } from './DashboardChart';
import GesturePanel from './GesturePanel';
import SettingsPanel from './SettingsPanel';
import VoicePanel from './VoicePanel';
import GazePanel from './GazePanel';
import { useGestureStore } from '../../store/gestureStore';
import styles from './DashboardHome.module.css';

const periods = [{ key: 'day', label: '1일' }, { key: 'week', label: '7일' }, { key: 'month', label: '한달' }, { key: 'year', label: '1년' }];
const details = { accuracy: ['인식 정확도', fetchDashboardAccuracy], latency: ['평균 응답 시간', fetchDashboardLatency], usage: ['제스처 / 보이스 사용량', fetchDashboardUsage], apps: ['자주 사용하는 프로그램', fetchDashboardApps] };
const views = ['home', 'settings', 'voice', 'gestures', 'gaze', ...Object.keys(details)];
const percent = (value) => value == null ? '데이터 없음' : `${Math.round(value * 100)}%`;
const seconds = (value) => value == null ? '데이터 없음' : `${(value / 1000).toFixed(1)}초`;

export default function DashboardHome() {
  const location = useLocation(); const navigate = useNavigate();
  const requestedView = new URLSearchParams(location.search).get('view');
  const view = views.includes(requestedView) ? requestedView : 'home';
  const gestureRegistration = useGestureStore((state) => state.registration);
  const [menu, setMenu] = useState(false); const [overview, setOverview] = useState(null); const [detail, setDetail] = useState(null); const [period, setPeriod] = useState('day'); const [loading, setLoading] = useState(false); const [error, setError] = useState('');
  useEffect(() => { if (view === 'home') load(fetchDashboardOverview, setOverview); }, [view]);
  useEffect(() => { if (details[view]) load(() => details[view][1](period), setDetail); }, [view, period]);
  async function load(fetcher, setter) { setLoading(true); setError(''); try { setter(await fetcher()); } catch (e) { setError(e.message); } finally { setLoading(false); } }
  const open = (next) => {
    if (next !== 'gestures') useGestureStore.getState().closeRegistration();
    setMenu(false);
    setError('');
    if (details[next]) {
      setPeriod('day');
      setDetail(null);
    }
    navigate(next === 'home' ? '/dashboard' : `/dashboard?view=${next}`);
  };
  const registrationTitle = gestureRegistration?.stage === 'complete' || gestureRegistration?.stage === 'form' ? '제스처 등록' : gestureRegistration?.stage === 'review' ? '촬영 결과' : '제스처 촬영';
  const title = view === 'home' ? 'SIA 대시보드' : view === 'settings' ? '설정' : view === 'gestures' ? (gestureRegistration ? registrationTitle : '제스처') : view === 'voice' ? '보이스' : view === 'gaze' ? '시선' : details[view]?.[0];
  const back = () => {
    if (view === 'gestures' && gestureRegistration) {
      useGestureStore.getState().closeRegistration();
      return;
    }
    if (view !== 'home') open('home');
  };
  return <main className={styles.page}><header className={styles.header}><button className={styles.back} onClick={back} aria-label="뒤로">{view === 'home' ? '' : '‹'}</button><h1>{title}</h1><button className={styles.menuButton} onClick={() => setMenu((value) => !value)} aria-label="메뉴">☰</button></header>
    {menu && <><button className={styles.scrim} onClick={() => setMenu(false)} aria-label="메뉴 닫기" /><nav className={styles.drawer}><button onClick={() => open('gestures')}>제스처<span>›</span></button><button onClick={() => open('voice')}>보이스<span>›</span></button><button onClick={() => open('gaze')}>시선<span>›</span></button><button onClick={() => open('settings')}>설정<span>›</span></button></nav></>}
    <section className={styles.content}>{loading && <p role="status">데이터를 불러오는 중입니다.</p>}{error && <p className={styles.error} role="alert">{error}</p>}{view === 'home' && <Overview data={overview} open={open} />}{details[view] && <Detail kind={view} data={detail} period={period} setPeriod={setPeriod} />}{view === 'gestures' && <GesturePanel />}{view === 'voice' && <VoicePanel />}{view === 'gaze' && <GazePanel />}{view === 'settings' && <SettingsPanel />}</section></main>;
}

function Overview({ data, open }) {
  if (!data) return null; const accuracy = [['음성 인식 정확도', data.accuracy?.voice], ['시선처리 정확도', data.accuracy?.gaze], ['모션인식 정확도', data.accuracy?.motion]]; const maxUsage = Math.max(1, ...(data.usage?.buckets ?? []).map((item) => item.count)); const maxApps = Math.max(1, ...(data.topApps ?? []).map((item) => item.count));
  return <><h2 className={styles.sectionTitle}>인식 정확도</h2><button className={`${styles.card} ${styles.accuracyCards}`} onClick={() => open('accuracy')}>{accuracy.map(([label, value]) => <span key={label}><small>{label}</small><strong>{percent(value)}</strong><i><b style={{ width: `${(value ?? 0) * 100}%` }} /></i></span>)}</button>
    <h2 className={styles.sectionTitle}>평균 응답 시간</h2><button className={`${styles.card} ${styles.latencyCard}`} onClick={() => open('latency')}><span><small>간단한 작업</small><strong>{seconds(data.latency?.simpleMs)}</strong></span><span><small>복잡한 작업</small><strong>{seconds(data.latency?.complexMs)}</strong></span></button>
    <h2 className={styles.sectionTitle}>제스처 / 보이스 사용량</h2><button className={`${styles.card} ${styles.miniBars}`} onClick={() => open('usage')}><small>최근 7일 사용 횟수 · 클릭 시 자세히 보기</small><span>{(data.usage?.buckets ?? []).map((item) => <i key={item.key} title={`${item.label} ${item.count}회`} style={{ height: `${item.count / maxUsage * 80 + 4}%` }} />)}</span></button>
    <h2 className={styles.sectionTitle}>자주 사용하는 프로그램</h2><button className={`${styles.card} ${styles.appPreview}`} onClick={() => open('apps')}>{(data.topApps ?? []).length ? data.topApps.map((item) => <span key={item.appKey}><em>{item.displayName}</em><i><b style={{ width: `${item.count / maxApps * 100}%` }} /></i></span>) : <Empty />}</button></>;
}

function Detail({ kind, data, period, setPeriod }) {
  if (!data) return null; const buckets = data.buckets ?? []; const summary = data.summary ?? {};
  return <><div className={styles.periods}>{periods.map((item) => <button className={period === item.key ? styles.activePeriod : ''} onClick={() => setPeriod(item.key)} key={item.key}>{item.label}</button>)}</div><section className={styles.largeCard}>{kind === 'accuracy' && <><Legend items={['음성 인식', '시선처리', '모션인식']} /><LineChart buckets={buckets} series={[{ key: 'voice' }, { key: 'gaze' }, { key: 'motion' }]} /></>}{kind === 'latency' && <><Legend items={['간단한 작업', '복잡한 작업']} /><BarChart buckets={buckets} series={[{ key: 'simpleMs' }, { key: 'complexMs' }]} valueFormatter={(v) => `${(v / 1000).toFixed(1)}s`} /></>}{kind === 'usage' && <><Legend items={['제스처 + 보이스 명령 합산 횟수']} /><BarChart buckets={buckets} series={[{ key: 'count' }]} valueFormatter={(v) => Math.round(v)} /></>}{kind === 'apps' && ((data.items ?? []).length ? <HorizontalBars items={data.items} /> : <Empty />)}</section><Summary kind={kind} summary={summary} /></>;
}

function Legend({ items }) { return <div className={styles.legend}>{items.map((item, index) => <span key={item}><i style={{ background: ['#333', '#777', '#aaa'][index] }} />{item}</span>)}</div>; }
function Summary({ kind, summary }) { const items = kind === 'accuracy' ? [['평균 음성 인식 정확도', percent(summary.voice)], ['평균 시선처리 정확도', percent(summary.gaze)], ['평균 모션인식 정확도', percent(summary.motion)]] : kind === 'latency' ? [['간단한 작업 평균', seconds(summary.simpleMs)], ['복잡한 작업 평균', seconds(summary.complexMs)], ['전체 평균', seconds(summary.overallMs)]] : kind === 'usage' ? [['총 사용 횟수', `${summary.total ?? 0}회`], ['기간당 평균', `${summary.average ?? 0}회`], ['최다 사용 구간', summary.peak ? `${summary.peak.label} (${summary.peak.count}회)` : '데이터 없음']] : [['전체 프로그램 실행 횟수', `${summary.totalLaunches ?? 0}회`], ['가장 많이 사용한 프로그램', summary.topDisplayName ?? '데이터 없음'], ['해당 프로그램 사용 횟수', `${summary.topCount ?? 0}회`]]; return <div className={styles.summaryCards}>{items.map(([label, value]) => <span className={styles.card} key={label}><small>{label}</small><strong>{value}</strong></span>)}</div>; }
function Empty() { return <p className={styles.empty}>아직 표시할 활동 데이터가 없습니다.</p>; }
