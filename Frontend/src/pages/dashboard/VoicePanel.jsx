import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchDevices } from '../../api/devices';
import { fetchSettings } from '../../api/settings';
import { activateProfile, deleteProfile, fetchProfiles, renameVoiceProfile, voiceSampleUrl } from '../../api/profiles';
import { ENROLLMENT_SENTENCES } from '../onboarding/enrollmentConstants';
import VoiceEnrollment from '../../components/onboarding/VoiceEnrollment';
import { useSessionStore } from '../../store/sessionStore';
import { useVoiceStore } from '../../store/voiceStore';
import { initializeVoiceEvents, sendVoice } from '../../ws/voices';
import styles from './VoicePanel.module.css';

initializeVoiceEvents();

const formatDate = (value) => value ? `등록일 ${value.slice(0, 10).replaceAll('-', '.')}` : '등록일 미제공';
const rejectionMessages = {
  TOO_SHORT: '너무 짧게 들렸어요. 문장을 끝까지 읽어주세요.',
  INCONSISTENT: '앞 문장과 목소리가 다르게 들려요. 같은 분이 조용한 곳에서 다시 읽어주세요.',
};

export default function VoicePanel() {
  const voice = useVoiceStore();
  const connected = useSessionStore((state) => state.wsConnected);
  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState('');
  const [modal, setModal] = useState(null);
  const [deleteMode, setDeleteMode] = useState(false);
  const [selected, setSelected] = useState([]);
  const [micLabel, setMicLabel] = useState(null);
  const [busy, setBusy] = useState(false);
  const activeTempId = useRef(null);

  const active = useMemo(() => profiles.find((item) => item.active), [profiles]);
  const stored = useMemo(() => profiles.filter((item) => !item.active), [profiles]);

  useEffect(() => { loadProfiles(); }, []);
  useEffect(() => { activeTempId.current = voice.tempId; }, [voice.tempId]);
  useEffect(() => {
    if (voice.stage !== 'processing') return undefined;
    const timer = setTimeout(() => voice.change({ error: '녹음 확인 응답이 지연되고 있습니다. AI 연결 상태를 확인해주세요.' }), 30000);
    return () => clearTimeout(timer);
  }, [voice.stage, voice.change]);
  useEffect(() => () => {
    if (activeTempId.current) {
      try { sendVoice('voice_reg_cancel', { tempId: activeTempId.current }); } catch { /* 페이지 이탈 시 임시 등록 정리 */ }
    }
    useVoiceStore.getState().resetEnrollment();
  }, []);

  async function loadProfiles() {
    setLoading(true); setPageError('');
    try { setProfiles((await fetchProfiles('mic')).items ?? []); }
    catch (error) { setPageError(error.message); }
    finally { setLoading(false); }
  }
  async function prepareEnrollment() {
    setBusy(true); setPageError('');
    try {
      const [settingsResult, devicesResult] = await Promise.all([fetchSettings(), fetchDevices()]);
      const configuredId = settingsResult.settings.micDeviceId;
      const configuredName = settingsResult.settings.micDevice;
      const configured = devicesResult.mics.find((item) => configuredId ? item.id === configuredId : item.name === configuredName);
      if ((configuredId || configuredName) && !configured) {
        setMicLabel(configuredName);
        setModal(null);
        voice.change({ stage: 'micError', error: '' });
        return;
      }
      const chosen = configured ?? devicesResult.mics.find((item) => item.isDefault);
      setMicLabel(chosen?.name ?? configuredName ?? null);
      setModal(null);
      voice.change({ stage: 'guide', error: '' });
    } catch (error) { setPageError(error.message); setModal(null); }
    finally { setBusy(false); }
  }
  function startRecording() {
    try {
      sendVoice('voice_reg_start');
      voice.change({ stage: 'recording', sentence: null, completed: 0, tempId: null, warning: null, review: null, pending: true, error: '' });
    } catch (error) { voice.change({ pending: false, error: error.message }); }
  }
  function send(type, data, patch = {}) {
    try { sendVoice(type, data); voice.change({ pending: true, error: '', ...patch }); }
    catch (error) { voice.change({ pending: false, error: error.message }); }
  }
  async function rename() {
    const name = modal.name.trim();
    if (!name) return;
    setBusy(true);
    try {
      await renameVoiceProfile(modal.profile.id, name);
      await loadProfiles();
      setModal({ type: 'success', title: '이름이 변경되었습니다', message: `'${modal.profile.name}' → '${name}'` });
    } catch (error) { setPageError(error.message); setModal(null); }
    finally { setBusy(false); }
  }
  async function activate(profile) {
    setBusy(true); setPageError('');
    try {
      const previous = active?.name;
      await activateProfile('mic', profile.id);
      await loadProfiles();
      setModal({ type: 'success', title: '보이스가 교체되었습니다', message: `'${previous}' → '${profile.name}'` });
    } catch (error) { setPageError(error.message); }
    finally { setBusy(false); }
  }
  async function removeSelected() {
    setBusy(true); setPageError('');
    try {
      await Promise.all(selected.map((id) => deleteProfile('mic', id)));
      await loadProfiles();
      setModal(null); setSelected([]); setDeleteMode(false);
    } catch (error) { setPageError(error.message); setModal(null); await loadProfiles(); }
    finally { setBusy(false); }
  }
  function toggle(id) { setSelected((items) => items.includes(id) ? items.filter((item) => item !== id) : [...items, id]); }

  if (voice.stage !== 'list') return <Enrollment voice={voice} micLabel={micLabel} connected={connected} onStart={startRecording} onRetryMic={prepareEnrollment} onSend={send} onSaved={async () => { activeTempId.current = null; await loadProfiles(); voice.resetEnrollment(); }} />;

  return <section className={styles.voicePage}>
    {loading && <p role="status">보이스를 불러오는 중입니다.</p>}
    {(pageError || voice.error) && <p className={styles.error} role="alert">{pageError || voice.error}</p>}
    {active && <><VoiceCard profile={active} active /><h2>등록된 내 목소리</h2></>}
    {!active && !loading && <div className={styles.empty}>등록된 보이스가 없습니다. 보이스를 추가해주세요.</div>}
    <div className={styles.listHeader}>
      {!active && <h2>등록된 내 목소리</h2>}
      {!deleteMode && <button className={styles.primary} onClick={() => setModal({ type: 'add' })} disabled={profiles.length >= 4 || busy}>+ 보이스 추가</button>}
    </div>
    <div className={styles.voiceList}>{stored.map((profile) => <VoiceCard key={profile.id} profile={profile} deleteMode={deleteMode} checked={selected.includes(profile.id)} onToggle={() => toggle(profile.id)} onRename={() => setModal({ type: 'rename', profile, name: profile.name })} onActivate={() => activate(profile)} busy={busy} />)}</div>
    <p className={styles.help}>목소리 인식이 잘 되지 않으면, 보이스를 추가 등록해보세요.</p>
    {deleteMode ? <div className={styles.deleteActions}><button onClick={() => { setDeleteMode(false); setSelected([]); }}>취소</button><button className={styles.primary} disabled={!selected.length || busy} onClick={() => setModal({ type: 'delete' })}>완전 삭제</button><span>{selected.length}개 선택됨</span></div>
      : <button className={styles.secondary} disabled={!stored.length} onClick={() => setDeleteMode(true)}>보이스 삭제</button>}
    {modal && <VoiceModal modal={modal} setModal={setModal} busy={busy} selectedCount={selected.length} onAdd={prepareEnrollment} onRename={rename} onDelete={removeSelected} onCancelDelete={() => { setModal(null); setSelected([]); setDeleteMode(false); }} />}
  </section>;
}

function VoiceCard({ profile, active, deleteMode, checked, onToggle, onRename, onActivate, busy }) {
  function play() {
    const url = voiceSampleUrl(profile.sampleUrl);
    if (url) new Audio(url).play().catch(() => {});
  }
  return <article className={`${styles.voiceCard} ${active ? styles.activeCard : ''}`}>
    {active && <small className={styles.activeCaption}>현재 사용 중인 보이스</small>}
    {deleteMode && <input type="checkbox" checked={checked} onChange={onToggle} aria-label={`${profile.name} 선택`} />}
    <button className={styles.play} onClick={play} disabled={!profile.sampleUrl} aria-label={`${profile.name} 재생`}>▶</button>
    <div className={styles.wave} aria-hidden="true">{Array.from({ length: 28 }, (_, index) => <i key={index} />)}</div>
    <div className={styles.voiceInfo}><strong>{profile.name}{!active && !deleteMode && <button className={styles.edit} onClick={onRename} aria-label={`${profile.name} 이름 변경`}>✎</button>}</strong><small>{formatDate(profile.createdAt)}</small></div>
    {active ? <span className={styles.activeBadge}>사용 중</span> : !deleteMode && <button className={styles.secondary} onClick={onActivate} disabled={busy}>사용으로 설정</button>}
  </article>;
}

function Enrollment({ voice, micLabel, connected, onStart, onRetryMic, onSend, onSaved }) {
  const tempId = voice.tempId;
  if (voice.stage === 'micError') return <div className={`${styles.enrollment} ${styles.enrollmentFullScreen}`}><div className={styles.roundIcon}>!</div><h2>마이크를 사용할 수 없어요</h2><p>{micLabel ? `${micLabel} 연결 상태를 확인해주세요.` : '마이크 연결 또는 권한 설정을 확인해주세요.'}<br />권한을 허용한 뒤 다시 시도할 수 있습니다.</p><div className={styles.actionRow}>{/* TODO(BE): Windows 마이크 설정을 여는 FE용 REST·WS 계약 필요 */}<button className={styles.secondary} disabled title="백엔드 연동이 필요합니다">시스템 설정 열기</button><button className={styles.primary} onClick={onRetryMic}>다시 확인</button></div></div>;
  if (voice.stage === 'guide') return <div className={`${styles.enrollment} ${styles.enrollmentFullScreen}`}><div className={styles.roundIcon}>♩</div><h2>조용한 곳에서 {voice.total}문장을 읽어주세요</h2><p>화면에 나오는 문장을 자연스럽게 읽으면 됩니다.<br />약 30초 정도 걸립니다.</p><div className={styles.device}>마이크 · {micLabel ?? '시스템 기본 마이크'}<span>정상</span></div><button className={styles.primary} onClick={onStart} disabled={!connected}>녹음 시작</button>{!connected && <p className={styles.error}>실시간 연결을 기다리고 있습니다.</p>}</div>;
  if (voice.stage === 'warning') return <div className={`${styles.enrollment} ${styles.enrollmentFullScreen}`}><div className={styles.roundIcon}>!</div><h2>목소리가 잘 들리지 않았어요</h2><p>{voice.warning?.reason ?? '주변 소음이 크거나 마이크와 거리가 멀 수 있습니다.'}<br />조용한 곳에서 다시 읽어주세요.</p><div className={styles.actionRow}><button className={styles.secondary} onClick={() => onSend('voice_accept_anyway', { tempId })} disabled={!tempId || voice.pending}>그대로 진행</button><button className={styles.primary} onClick={() => onSend('voice_reg_retry', { tempId }, { stage: 'recording', completed: 0, sentence: null, warning: null })} disabled={!tempId || voice.pending}>다시 녹음</button></div></div>;
  if (voice.stage === 'processing') return <VoiceEnrollment mode="processing" fullScreen error={voice.error} />;
  if (voice.stage === 'review') {
    const current = Number(voice.review?.n) || Math.max(1, voice.completed);
    const rejected = voice.review?.rejected === true;
    const reason = rejectionMessages[voice.review?.code] ?? voice.review?.reason?.trim() ?? '사유 미판정';
    return <VoiceEnrollment mode="review" fullScreen review={{ ...voice.review, reason }} current={current} total={voice.total} rejected={rejected} ready={connected} pending={voice.pending} canRetry={Boolean(tempId)} canAccept={Boolean(tempId) && (current < voice.total || Boolean(voice.review))} error={voice.error} onRetry={() => onSend(rejected || current < voice.total ? 'voice_sentence_retry' : 'voice_reg_retry', { tempId }, { stage: 'recording', ...(!rejected && current >= voice.total ? { completed: 0 } : {}), sentence: null, review: null })} onAccept={() => current >= voice.total ? onSend('voice_commit', { tempId, ...(micLabel ? { deviceLabel: micLabel } : {}) }) : onSend('voice_sentence_next', { tempId }, { stage: 'recording', sentence: null, review: null })} />;
  }
  if (voice.stage === 'done') return <div className={`${styles.enrollment} ${styles.enrollmentFullScreen}`}><div className={styles.roundIcon}>✓</div><h2>등록 완료!</h2><p>이제 내 목소리를 다른 사람의 말과 구분해<br />명령을 실행합니다!</p><button className={styles.primary} onClick={onSaved}>확인</button></div>;
  const n = voice.sentence?.n ?? Math.min(voice.completed + 1, voice.total);
  return <VoiceEnrollment mode="recording" fullScreen current={n} total={voice.total} sentence={ENROLLMENT_SENTENCES[n - 1] ?? '낭독 문장 원문을 기다리고 있습니다.'} />;
}

function VoiceModal({ modal, setModal, busy, selectedCount, onAdd, onRename, onDelete, onCancelDelete }) {
  const close = () => setModal(null);
  return <div className={styles.backdrop} role="presentation"><section className={styles.modal} role="dialog" aria-modal="true">
    {modal.type === 'add' && <><div className={styles.roundIcon}>♩</div><h2>보이스를 추가 등록하시겠습니까?</h2><div className={styles.actionRow}><button onClick={close}>취소</button><button className={styles.primary} onClick={onAdd} disabled={busy}>새로 시작</button></div></>}
    {modal.type === 'rename' && <><h2>보이스 이름 변경</h2><label>보이스 이름<input value={modal.name} onChange={(event) => setModal({ ...modal, name: event.target.value })} maxLength="50" autoFocus /></label><div className={styles.actionRow}><button onClick={close}>취소</button><button className={styles.primary} onClick={onRename} disabled={busy || !modal.name.trim()}>저장</button></div></>}
    {modal.type === 'delete' && <><div className={styles.roundIcon}>!</div><h2>선택한 보이스 {selectedCount}개를 삭제하시겠습니까?</h2><p>삭제 후에는 되돌릴 수 없습니다.</p><div className={styles.actionRow}><button onClick={onCancelDelete}>취소</button><button className={styles.primary} onClick={onDelete} disabled={busy}>삭제</button></div></>}
    {modal.type === 'success' && <><div className={styles.roundIcon}>✓</div><h2>{modal.title}</h2><p>{modal.message}</p><button className={styles.primary} onClick={close}>확인</button></>}
  </section></div>;
}
