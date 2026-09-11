import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { activateProfile, deleteProfile, fetchProfiles } from '../../api/profiles';
import styles from './GazePanel.module.css';

const grades = { excellent: '우수', good: '양호', poor: '나쁨' };
const formatDate = (value) => value ? value.slice(0, 10).replaceAll('-', '.') : '미제공';

export default function GazePanel() {
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

  function startEnrollment() {
    navigate('/dashboard/gaze/setup');
  }

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
      await Promise.all(selected.map((id) => deleteProfile('camera', id)));
      const count = selected.length;
      await loadProfiles();
      setSelected([]);
      setDeleteMode(false);
      setModal({ type: 'success', title: '보정이 삭제되었습니다', message: `선택한 보정 ${count}개를 삭제했습니다.` });
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
    {loading && <p role="status">시선 보정을 불러오는 중입니다.</p>}
    {error && <p className={styles.error} role="alert">{error}</p>}
    {active && <section><p className={styles.caption}>현재 사용 중인 보정</p><GazeCard profile={active} active /></section>}
    {!active && !loading && <div className={styles.empty}>등록된 시선 보정이 없습니다. 새 보정을 추가해주세요.</div>}
    <div className={styles.listHeader}>
      <h2>등록된 보정</h2>
      {!deleteMode && <button className={styles.primary} onClick={() => setModal({ type: 'add' })} disabled={profiles.length >= 4 || busy}>+ 새 보정</button>}
    </div>
    <div className={styles.profileList}>
      {stored.map((profile) => <GazeCard key={profile.id} profile={profile} deleteMode={deleteMode} checked={selected.includes(profile.id)} onToggle={() => toggle(profile.id)} onActivate={() => setModal({ type: 'activate', profile })} busy={busy} />)}
    </div>
    <p className={styles.help}>시선 인식이 잘 되지 않으면, 새로 보정한 뒤 그 보정을 사용으로 설정해보세요.</p>
    {deleteMode
      ? <div className={styles.deleteActions}><button onClick={() => { setDeleteMode(false); setSelected([]); }}>취소</button><button className={styles.primary} disabled={!selected.length || busy} onClick={() => setModal({ type: 'delete' })}>완전 삭제</button><span>{selected.length}개 선택됨</span></div>
      : <button className={styles.secondary} disabled={!stored.length || busy} onClick={() => setDeleteMode(true)}>보정 삭제</button>}
    {modal && <GazeModal modal={modal} active={active} busy={busy} selectedCount={selected.length} close={() => setModal(null)} startEnrollment={startEnrollment} activate={activate} removeSelected={removeSelected} />}
  </section>;
}

function GazeCard({ profile, active, deleteMode, checked, onToggle, onActivate, busy }) {
  return <article className={`${styles.profileCard} ${active ? styles.activeCard : ''}`}>
    {deleteMode && <input type="checkbox" checked={checked} onChange={onToggle} aria-label={`${profile.name} 선택`} />}
    <span className={styles.gazeMark} aria-hidden="true"><i /></span>
    <div className={styles.profileInfo}>
      <strong>{profile.name}</strong>
      <small>등록일 {formatDate(profile.createdAt)} · 평균 오차 {profile.avgErrorPx == null ? '미제공' : `${Math.round(profile.avgErrorPx)}px`} · 상태: {grades[profile.grade] ?? '미제공'}</small>
    </div>
    {active ? <span className={styles.activeBadge}>사용 중</span> : !deleteMode && <button className={styles.secondary} onClick={onActivate} disabled={busy}>사용으로 설정</button>}
  </article>;
}

function GazeModal({ modal, active, busy, selectedCount, close, startEnrollment, activate, removeSelected }) {
  if (modal.type === 'add') return <Modal><GazeMark /><h2>새 보정을 추가하시겠습니까?</h2><p>기존 보정은 그대로 두고 새 보정 데이터를 만듭니다.<br />약 1분 정도 걸립니다.</p><div className={styles.modalActions}><button onClick={close}>취소</button><button className={styles.primary} onClick={startEnrollment}>새로 시작</button></div></Modal>;
  if (modal.type === 'activate') return <Modal><h2>현재 보정을 교체하시겠습니까?</h2><p>{active ? `'${active.name}' → '${modal.profile.name}'` : `'${modal.profile.name}' 보정을 사용합니다.`}</p><div className={styles.modalActions}><button onClick={close}>취소</button><button className={styles.primary} onClick={() => activate(modal.profile)} disabled={busy}>교체</button></div></Modal>;
  if (modal.type === 'delete') return <Modal><div className={styles.roundIcon}>!</div><h2>선택한 보정 {selectedCount}개를 삭제하시겠습니까?</h2><p>삭제 후에는 되돌릴 수 없습니다.</p><div className={styles.modalActions}><button onClick={close}>취소</button><button className={styles.primary} onClick={removeSelected} disabled={busy}>삭제</button></div></Modal>;
  if (modal.type === 'added') return <Modal><div className={styles.roundIcon}>✓</div><h2>새 보정이 추가되었습니다</h2><p>{modal.profile.name ? `'${modal.profile.name}' 보정이 저장되었습니다.` : '새 시선 보정이 저장되었습니다.'}</p><div className={styles.modalActions}><button onClick={close}>나중에</button>{!modal.profile.active && <button className={styles.primary} onClick={() => activate(modal.profile, 'added')} disabled={busy}>사용으로 설정</button>}</div></Modal>;
  return <Modal><div className={styles.roundIcon}>✓</div><h2>{modal.title}</h2><p>{modal.message}</p><button className={styles.primary} onClick={close}>확인</button></Modal>;
}

function Modal({ children }) {
  return <div className={styles.backdrop} role="presentation"><section className={styles.modal} role="dialog" aria-modal="true">{children}</section></div>;
}

function GazeMark() {
  return <span className={`${styles.gazeMark} ${styles.gazePreview}`} aria-hidden="true"><i /></span>;
}
