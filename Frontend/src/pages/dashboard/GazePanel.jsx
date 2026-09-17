import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { activateProfile, deleteProfile, fetchProfile, fetchProfiles, renameGazeProfile } from '../../api/profiles';
import styles from './GazePanel.module.css';

const grades = { excellent: '우수', good: '양호', poor: '나쁨' };
const formatDate = (value) => value ? value.slice(0, 10).replaceAll('-', '.') : '미제공';
const px = (value) => Number.isFinite(value) ? `${Math.round(value)}px` : '미제공';
function gazeStats(profile) {
  let points = profile.points ?? [];
  if (!points.length && profile.pointsJson) {
    try { points = JSON.parse(profile.pointsJson); } catch { points = []; }
  }
  const values = points.map((point) => Math.hypot(Number(point.dx), Number(point.dy))).filter(Number.isFinite);
  return {
    min: profile.minErrorPx ?? (values.length ? Math.min(...values) : null),
    avg: profile.avgErrorPx ?? (values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null),
    max: profile.maxErrorPx ?? (values.length ? Math.max(...values) : null),
  };
}

export default function GazePanel({ onBack }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [modal, setModal] = useState(() => location.state?.gazeAdded ? { type: 'added', profile: location.state.gazeAdded } : null);
  const [deleteMode, setDeleteMode] = useState(false);
  const [selected, setSelected] = useState([]);

  const active = useMemo(() => profiles.find((profile) => profile.active), [profiles]);
  const stored = useMemo(() => profiles.filter((profile) => !profile.active), [profiles]);

  useEffect(() => { loadProfiles(); }, []);
  useEffect(() => {
    if (location.state?.gazeAdded) navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
  }, [location.pathname, location.search, location.state, navigate]);

  async function loadProfiles() {
    setLoading(true);
    setError('');
    try {
      const items = (await fetchProfiles('camera')).items ?? [];
      const profilesWithStats = await Promise.all(items.map(async (profile) => {
        try { return { ...profile, ...(await fetchProfile('camera', profile.id)) }; }
        catch { return profile; }
      }));
      setProfiles(profilesWithStats);
    }
    catch (requestError) { setError(requestError.message); }
    finally { setLoading(false); }
  }

  function startEnrollment() { navigate('/dashboard/gaze/setup'); }

  async function activate(profile, successType = 'activated') {
    setBusy(true);
    setError('');
    try {
      const previous = active?.name;
      await activateProfile('camera', profile.id);
      await loadProfiles();
      setModal(successType === 'added'
        ? { type: 'success', title: '새 보정이 추가되었습니다', message: `'${profile.name}' 보정을 사용하도록 설정했습니다.` }
        : { type: 'success', title: '보정이 교체되었습니다', message: previous ? `'${previous}' → '${profile.name}'` : `'${profile.name}' 보정을 사용합니다.` });
    } catch (requestError) {
      setError(requestError.message);
      setModal(null);
    } finally { setBusy(false); }
  }

  async function removeSelected() {
    setBusy(true);
    setError('');
    try {
      const removedNames = stored.filter((profile) => selected.includes(profile.id)).map((profile) => profile.name);
      for (const id of selected) await deleteProfile('camera', id);
      await loadProfiles();
      setSelected([]);
      setDeleteMode(false);
      setModal({ type: 'success', title: '보정이 삭제되었습니다', message: `${removedNames.join(', ')}이(가) 삭제되었습니다.` });
    } catch (requestError) {
      setError(requestError.message);
      setModal(null);
      await loadProfiles();
    } finally { setBusy(false); }
  }

  function toggle(id) {
    setSelected((items) => items.includes(id) ? items.filter((item) => item !== id) : [...items, id]);
  }

  async function rename() {
    const name = modal.name.trim();
    if (!name) return;
    setBusy(true);
    setError('');
    try {
      await renameGazeProfile(modal.profile.id, name);
      await loadProfiles();
      setModal({ type: 'success', title: '이름이 변경되었습니다', message: `${modal.profile.name} → ${name}` });
    } catch (requestError) {
      setError(requestError.message);
      setModal(null);
    } finally { setBusy(false); }
  }

  return <section className={styles.gazePage}>
    <GazeHero onBack={onBack} />
    {loading && <p className={styles.loading} role="status">시선 보정을 불러오는 중입니다.</p>}
    {error && <p className={styles.error} role="alert">{error}</p>}
    <div className={styles.calibrationGrid}>
      <section className={`${styles.frame} ${styles.activePanel}`}>
        <FrameMarks />
        <small>ACTIVE GAZE</small>
        <h2>현재 사용 중인 보정</h2>
        {active ? <>
          <div className={styles.activeRadar}><GazeRadar /></div>
          <div className={styles.activeFooter}><span><span className={styles.nameRow}><strong>{active.name}</strong><button className={styles.activeEditButton} onClick={() => setModal({ type: 'rename', profile: active, name: active.name })} aria-label={`${active.name} 이름 변경`}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 20 4.2-1 10.6-10.6-3.2-3.2L5 15.8 4 20ZM14.5 6.3l3.2 3.2M13 20h7" /></svg></button></span><small>등록일 {formatDate(active.createdAt)}</small><GazeStats profile={active} /></span><em><i />사용 중</em></div>
        </> : <div className={styles.emptyActive}><GazeRadar /><strong>현재 사용 중인 보정이 없습니다</strong></div>}
      </section>
      <section className={`${styles.frame} ${styles.storedPanel}`}>
        <FrameMarks />
        <div className={styles.listTitle}><span><small>{deleteMode ? 'DELETE CALIBRATIONS' : 'MY CALIBRATIONS'}</small><h2>{deleteMode ? '삭제할 보정을 선택하세요' : '등록된 보정'}</h2></span>{!deleteMode && (profiles.length >= 4 ? <b>최대 4개 등록됨</b> : <button className={styles.primary} onClick={() => setModal({ type: 'add' })} disabled={busy}>+ 새 보정</button>)}</div>
        <div className={styles.profileList}>
          {stored.map((profile) => <GazeCard key={profile.id} profile={profile} deleteMode={deleteMode} checked={selected.includes(profile.id)} onToggle={() => toggle(profile.id)} onRename={() => setModal({ type: 'rename', profile, name: profile.name })} onActivate={() => setModal({ type: 'activate', profile })} busy={busy} />)}
          {!stored.length && !loading && <p className={styles.emptyList}>등록된 보정이 없습니다.</p>}
        </div>
        {deleteMode && <div className={styles.deleteNotice}><span>!</span><p>선택한 보정은 삭제 후 복구할 수 없습니다.</p></div>}
      </section>
    </div>
    <section className={`${styles.frame} ${styles.bottomBar}`}><FrameMarks /><span className={styles.noticeIcon}>!</span><strong>시선 인식이 잘 되지 않으면, 새로 보정한 뒤 사용할 보정을 설정해보세요.</strong>{deleteMode
      ? <div className={styles.deleteActions}><button onClick={() => { setDeleteMode(false); setSelected([]); }}>취소</button><button className={styles.primary} disabled={!selected.length || busy} onClick={() => setModal({ type: 'delete' })}>완전 삭제</button><span>{selected.length}개 선택됨</span></div>
      : <button className={styles.secondary} disabled={!stored.length || busy} onClick={() => setDeleteMode(true)}>보정 삭제</button>}</section>
    {modal && <GazeModal modal={modal} setModal={setModal} active={active} busy={busy} selectedCount={selected.length} close={() => setModal(null)} startEnrollment={startEnrollment} activate={activate} rename={rename} removeSelected={removeSelected} />}
  </section>;
}

function GazeHero({ onBack }) {
  return <header className={styles.gazeHero}><div className={styles.heroTitle}><button onClick={onBack} aria-label="대시보드로 돌아가기">‹</button><h1>시선</h1></div><Circuit /><GazeRadar hero /></header>;
}

function Circuit() {
  return <svg className={styles.circuit} viewBox="0 0 760 120" preserveAspectRatio="none" aria-hidden="true"><circle cx="14" cy="66" r="5" /><path d="M19 66h190l44 30h249l54-42h174" /><path className={styles.circuitLight} d="M350 35h170l42-19h150" /></svg>;
}

function FrameMarks() { return <i className={styles.frameLine} />; }

function GazeRadar({ compact = false, hero = false }) {
  const className = hero ? styles.heroRadar : compact ? styles.compactRadar : styles.radar;
  return <svg className={className} viewBox="0 0 280 280" aria-hidden="true"><circle cx="140" cy="140" r="111" className={styles.radarOuter} /><circle cx="140" cy="140" r="84" /><circle cx="140" cy="140" r="54" /><path d="M140 15v250M15 140h250" /><path d="M140 33v24M140 223v24M33 140h24M223 140h24" /><circle cx="170" cy="111" r="12" className={styles.radarTarget} /><circle cx="140" cy="140" r="4" className={styles.radarCenter} /></svg>;
}

function GazeCard({ profile, deleteMode, checked, onToggle, onRename, onActivate, busy }) {
  return <article className={styles.profileCard}>{deleteMode && <input type="checkbox" checked={checked} onChange={onToggle} aria-label={`${profile.name} 선택`} />}<GazeRadar compact /><div className={styles.profileInfo}><span className={styles.nameRow}><strong>{profile.name}</strong>{!deleteMode && <button className={styles.editButton} onClick={onRename} aria-label={`${profile.name} 이름 변경`}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 20 4.2-1 10.6-10.6-3.2-3.2L5 15.8 4 20ZM14.5 6.3l3.2 3.2M13 20h7" /></svg></button>}</span><small>등록일 {formatDate(profile.createdAt)} · 상태: {grades[profile.grade] ?? '미제공'}</small><GazeStats profile={profile} /></div>{!deleteMode && <button className={styles.pillButton} onClick={onActivate} disabled={busy}>사용으로 설정</button>}</article>;
}

function GazeStats({ profile }) {
  const stats = gazeStats(profile);
  return <small>좌표 오차 최소 {px(stats.min)} · 평균 {px(stats.avg)} · 최대 {px(stats.max)}</small>;
}

function GazeModal({ modal, setModal, active, busy, selectedCount, close, startEnrollment, activate, rename, removeSelected }) {
  let content;
  if (modal.type === 'add') content = <><GazeModalIcon type="target" /><h2>새 보정을 추가하시겠습니까?</h2><p>기존 보정은 그대로 유지되며, 새로운 보정이 1개 추가됩니다.<br />사용 중 1개와 저장 3개까지, 최대 4개의 보정을 등록할 수 있습니다.</p><div className={styles.modalActions}><button onClick={close}>취소</button><button className={styles.primary} onClick={startEnrollment}>새로 시작</button></div></>;
  else if (modal.type === 'activate') content = <><h2>현재 보정을 교체하시겠습니까?</h2><p>{active ? `'${active.name}' → '${modal.profile.name}' (으)로 교체됩니다.` : `'${modal.profile.name}' 보정을 사용합니다.`}</p><div className={styles.modalActions}><button onClick={close}>취소</button><button className={styles.primary} onClick={() => activate(modal.profile)} disabled={busy}>교체</button></div></>;
  else if (modal.type === 'delete') content = <><GazeModalIcon type="warning" /><h2>선택한 보정 {selectedCount}개를 삭제하시겠습니까?</h2><p>삭제된 보정은 복구할 수 없습니다.</p><div className={styles.modalActions}><button onClick={close}>취소</button><button className={styles.primary} onClick={removeSelected} disabled={busy}>삭제</button></div></>;
  else if (modal.type === 'rename') content = <div className={styles.renameContent}><h2>시선 보정 이름 변경</h2><i className={styles.titleUnderline} /><label>보정 이름<input value={modal.name} onChange={(event) => setModal({ ...modal, name: event.target.value })} maxLength="50" autoFocus /></label><div className={styles.modalActions}><button onClick={close}>취소</button><button className={styles.primary} onClick={rename} disabled={busy || !modal.name.trim()}>저장</button></div></div>;
  else if (modal.type === 'added') { const stats = gazeStats(modal.profile); content = <><GazeModalIcon type="check" /><h2>새 보정이 추가되었습니다</h2><strong className={styles.addedName}>{modal.profile.name}</strong><p>최소 {px(stats.min)} · 평균 {px(stats.avg)} · 최대 {px(stats.max)} · 기준 {grades[modal.profile.grade] ?? '통과'}</p><p>이 보정을 지금 사용으로 설정할까요?</p><div className={styles.modalActions}><button onClick={close}>나중에</button>{!modal.profile.active && <button className={styles.primary} onClick={() => activate(modal.profile, 'added')} disabled={busy}>사용으로 설정</button>}</div></>; }
  else content = <><GazeModalIcon type="check" /><h2>{modal.title}</h2><p>{modal.message}</p><button className={styles.primary} onClick={close}>확인</button></>;
  return <div className={styles.backdrop} role="presentation"><section className={`${styles.modal} ${styles.frame}`} role="dialog" aria-modal="true"><FrameMarks />{content}</section></div>;
}

function GazeModalIcon({ type }) {
  if (type === 'target') return <span className={styles.modalIcon}><i /></span>;
  return <span className={styles.modalIcon}>{type === 'check' ? '✓' : '!'}</span>;
}
