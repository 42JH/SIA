import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { activateProfile, deleteProfile, fetchProfiles } from '../../api/profiles';
import styles from './GazePanel.module.css';

const grades = { excellent: '우수', good: '양호', poor: '나쁨' };
const formatDate = (value) => value ? value.slice(0, 10).replaceAll('-', '.') : '미제공';

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
    try { setProfiles((await fetchProfiles('camera')).items ?? []); }
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
      await Promise.all(selected.map((id) => deleteProfile('camera', id)));
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
          <div className={styles.activeFooter}><span><strong>{active.name}</strong><small>등록일 {formatDate(active.createdAt)}</small></span><em><i />사용 중</em></div>
        </> : <div className={styles.emptyActive}><GazeRadar /><strong>현재 사용 중인 보정이 없습니다</strong></div>}
      </section>
      <section className={`${styles.frame} ${styles.storedPanel}`}>
        <FrameMarks />
        <div className={styles.listTitle}><span><small>{deleteMode ? 'DELETE CALIBRATIONS' : 'MY CALIBRATIONS'}</small><h2>{deleteMode ? '삭제할 보정을 선택하세요' : '등록된 보정'}</h2></span>{!deleteMode && (profiles.length >= 4 ? <b>최대 4개 등록됨</b> : <button className={styles.primary} onClick={() => setModal({ type: 'add' })} disabled={busy}>+ 새 보정</button>)}</div>
        <div className={styles.profileList}>
          {stored.map((profile) => <GazeCard key={profile.id} profile={profile} deleteMode={deleteMode} checked={selected.includes(profile.id)} onToggle={() => toggle(profile.id)} onActivate={() => setModal({ type: 'activate', profile })} busy={busy} />)}
          {!stored.length && !loading && <p className={styles.emptyList}>등록된 보정이 없습니다.</p>}
        </div>
        {deleteMode && <div className={styles.deleteNotice}><span>!</span><p>선택한 보정은 삭제 후 복구할 수 없습니다.</p></div>}
      </section>
    </div>
    <section className={`${styles.frame} ${styles.bottomBar}`}><FrameMarks /><span className={styles.noticeIcon}>!</span><strong>시선 인식이 잘 되지 않으면, 새로 보정한 뒤 사용할 보정을 설정해보세요.</strong>{deleteMode
      ? <div className={styles.deleteActions}><button onClick={() => { setDeleteMode(false); setSelected([]); }}>취소</button><button className={styles.primary} disabled={!selected.length || busy} onClick={() => setModal({ type: 'delete' })}>완전 삭제</button><span>{selected.length}개 선택됨</span></div>
      : <button className={styles.secondary} disabled={!stored.length || busy} onClick={() => setDeleteMode(true)}>보정 삭제</button>}</section>
    {modal && <GazeModal modal={modal} active={active} busy={busy} selectedCount={selected.length} close={() => setModal(null)} startEnrollment={startEnrollment} activate={activate} removeSelected={removeSelected} />}
  </section>;
}

function GazeHero({ onBack }) {
  return <header className={styles.gazeHero}><div><div className={styles.heroTitle}><button onClick={onBack} aria-label="대시보드로 돌아가기">‹</button><h1>시선</h1></div><p>나에게 맞는 시선을 설정하여 더 편리한 환경을 만들어보세요.</p></div><Circuit /><GazeSeal /></header>;
}

function Circuit() {
  return <svg className={styles.circuit} viewBox="0 0 760 120" preserveAspectRatio="none" aria-hidden="true"><path d="M0 54h120l25 21h170l30 23h255l30-22h130" /><path d="M356 98h218l28-18h108" /><path d="M180 43h155l28 21h152" /><circle cx="342" cy="98" r="7" /><circle cx="742" cy="76" r="5" /></svg>;
}

function GazeSeal() {
  return <div className={styles.gazeSeal} aria-hidden="true"><i /><i /><span /></div>;
}

function FrameMarks() { return <><i className={styles.frameLine} /><i className={styles.frameDots}>••••</i></>; }

function GazeRadar({ compact = false }) {
  return <svg className={compact ? styles.compactRadar : styles.radar} viewBox="0 0 280 280" aria-hidden="true"><circle cx="140" cy="140" r="111" className={styles.radarOuter} /><circle cx="140" cy="140" r="84" /><circle cx="140" cy="140" r="54" /><path d="M140 15v250M15 140h250" /><path d="M140 33v24M140 223v24M33 140h24M223 140h24" /><circle cx="170" cy="111" r="12" className={styles.radarTarget} /><circle cx="140" cy="140" r="4" className={styles.radarCenter} /></svg>;
}

function GazeCard({ profile, deleteMode, checked, onToggle, onActivate, busy }) {
  return <article className={styles.profileCard}>{deleteMode && <input type="checkbox" checked={checked} onChange={onToggle} aria-label={`${profile.name} 선택`} />}<GazeRadar compact /><div className={styles.profileInfo}><strong>{profile.name}</strong><small>등록일 {formatDate(profile.createdAt)} · 상태: {grades[profile.grade] ?? '미제공'}</small></div>{!deleteMode && <button className={styles.pillButton} onClick={onActivate} disabled={busy}>사용으로 설정</button>}</article>;
}

function GazeModal({ modal, active, busy, selectedCount, close, startEnrollment, activate, removeSelected }) {
  let content;
  if (modal.type === 'add') content = <><GazeModalIcon type="target" /><h2>새 보정을 추가하시겠습니까?</h2><p>기존 보정은 그대로 유지되며, 새로운 보정이 1개 추가됩니다.<br />사용 중 1개와 저장 3개까지, 최대 4개의 보정을 등록할 수 있습니다.</p><div className={styles.modalActions}><button onClick={close}>취소</button><button className={styles.primary} onClick={startEnrollment}>새로 시작</button></div></>;
  else if (modal.type === 'activate') content = <><h2>현재 보정을 교체하시겠습니까?</h2><p>{active ? `'${active.name}' → '${modal.profile.name}' (으)로 교체됩니다.` : `'${modal.profile.name}' 보정을 사용합니다.`}</p><div className={styles.modalActions}><button onClick={close}>취소</button><button className={styles.primary} onClick={() => activate(modal.profile)} disabled={busy}>교체</button></div></>;
  else if (modal.type === 'delete') content = <><GazeModalIcon type="warning" /><h2>선택한 보정 {selectedCount}개를 삭제하시겠습니까?</h2><p>삭제된 보정은 복구할 수 없습니다.</p><div className={styles.modalActions}><button onClick={close}>취소</button><button className={styles.primary} onClick={removeSelected} disabled={busy}>삭제</button></div></>;
  else if (modal.type === 'added') content = <><GazeModalIcon type="check" /><h2>새 보정이 추가되었습니다</h2><strong className={styles.addedName}>{modal.profile.name}</strong><p>평균 오차 {modal.profile.avgErrorPx == null ? '미제공' : `${Math.round(modal.profile.avgErrorPx)}px`} · 기준 {grades[modal.profile.grade] ?? '통과'}</p><p>이 보정을 지금 사용으로 설정할까요?</p><div className={styles.modalActions}><button onClick={close}>나중에</button>{!modal.profile.active && <button className={styles.primary} onClick={() => activate(modal.profile, 'added')} disabled={busy}>사용으로 설정</button>}</div></>;
  else content = <><GazeModalIcon type="check" /><h2>{modal.title}</h2><p>{modal.message}</p><button className={styles.primary} onClick={close}>확인</button></>;
  return <div className={styles.backdrop} role="presentation"><section className={`${styles.modal} ${styles.frame}`} role="dialog" aria-modal="true"><FrameMarks />{content}</section></div>;
}

function GazeModalIcon({ type }) {
  if (type === 'target') return <span className={styles.modalIcon}><i /></span>;
  return <span className={styles.modalIcon}>{type === 'check' ? '✓' : '!'}</span>;
}
