import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchDevices } from '../../api/devices';
import { fetchSettings } from '../../api/settings';
import { activateProfile, deleteProfile, fetchProfiles, renameVoiceProfile, voiceSampleUrl } from '../../api/profiles';
import { ENROLLMENT_SENTENCES } from '../onboarding/enrollmentConstants';
import { useSessionStore } from '../../store/sessionStore';
import { useVoiceStore } from '../../store/voiceStore';
import { initializeVoiceEvents, sendVoice } from '../../ws/voices';
import styles from './VoicePanel.module.css';

initializeVoiceEvents();

const formatDate = (value) => value ? `등록일 ${value.slice(0, 10).replaceAll('-', '.')}` : '등록일 미제공';

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
  function cancelEnrollment() {
    if (voice.tempId && connected) {
      try { sendVoice('voice_reg_cancel', { tempId: voice.tempId }); } catch { /* 화면 복귀 우선 */ }
    }
    activeTempId.current = null;
    voice.resetEnrollment();
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

  if (voice.stage !== 'list') return <Enrollment voice={voice} micLabel={micLabel} connected={connected} onStart={startRecording} onRetryMic={prepareEnrollment} onSend={send} onCancel={cancelEnrollment} onSaved={async () => { activeTempId.current = null; await loadProfiles(); voice.resetEnrollment(); }} />;

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

function Enrollment({ voice, micLabel, connected, onStart, onRetryMic, onSend, onCancel, onSaved }) {
  const tempId = voice.tempId;
  if (voice.stage === 'micError') return <div className={styles.enrollment}><div className={styles.roundIcon}>!</div><h2>마이크를 사용할 수 없어요</h2><p>{micLabel ? `${micLabel} 연결 상태를 확인해주세요.` : '마이크 연결 또는 권한 설정을 확인해주세요.'}<br />권한을 허용한 뒤 다시 시도할 수 있습니다.</p><div className={styles.actionRow}>{/* TODO(BE): Windows 마이크 설정을 여는 FE용 REST·WS 계약 필요 */}<button className={styles.secondary} disabled title="백엔드 연동이 필요합니다">시스템 설정 열기</button><button className={styles.primary} onClick={onRetryMic}>다시 확인</button></div></div>;
  if (voice.stage === 'guide') return <div className={styles.enrollment}><div className={styles.roundIcon}>♩</div><h2>조용한 곳에서 5문장을 읽어주세요</h2><p>화면에 나오는 문장을 자연스럽게 읽으면 됩니다.<br />약 30초 정도 걸립니다.</p><div className={styles.device}>마이크 · {micLabel ?? '시스템 기본 마이크'}<span>정상</span></div><button className={styles.primary} onClick={onStart} disabled={!connected}>녹음 시작</button>{!connected && <p className={styles.error}>실시간 연결을 기다리고 있습니다.</p>}</div>;
  if (voice.stage === 'warning') return <div className={styles.enrollment}><div className={styles.roundIcon}>!</div><h2>목소리가 잘 들리지 않았어요</h2><p>{voice.warning?.reason ?? '주변 소음이 크거나 마이크와 거리가 멀 수 있습니다.'}<br />조용한 곳에서 다시 읽어주세요.</p><div className={styles.actionRow}><button className={styles.secondary} onClick={() => onSend('voice_accept_anyway', { tempId })} disabled={!tempId || voice.pending}>그대로 진행</button><button className={styles.primary} onClick={() => onSend('voice_reg_retry', { tempId }, { stage: 'recording', completed: 0, sentence: null, warning: null })} disabled={!tempId || voice.pending}>다시 녹음</button></div></div>;
  if (voice.stage === 'review') return <div className={styles.enrollment}><h2>이 목소리로 등록할까요?</h2><p>재생해 들어보고, 마음에 들지 않으면 다시 녹음할 수 있습니다.</p>{voice.review?.sampleUrl ? <audio className={styles.audio} controls src={voiceSampleUrl(voice.review.sampleUrl)} /> : <p>재생 가능한 샘플이 없습니다.</p>}<div className={styles.quality}><span>녹음 품질 · {voice.review?.quality ?? '미제공'}</span><span>주변 소음 {voice.review?.noise ?? '미제공'}</span></div><div className={styles.actionRow}><button className={styles.secondary} onClick={() => onSend('voice_reg_retry', { tempId }, { stage: 'recording', completed: 0, sentence: null, review: null })} disabled={!tempId || voice.pending}>다시 녹음</button><button className={styles.primary} onClick={() => onSend('voice_commit', { tempId, ...(micLabel ? { deviceLabel: micLabel } : {}) })} disabled={!tempId || voice.pending || voice.completed < 5}>등록</button></div>{voice.error && <p className={styles.error}>{voice.error}</p>}</div>;
  if (voice.stage === 'done') return <div className={styles.enrollment}><div className={styles.roundIcon}>✓</div><h2>등록 완료!</h2><p>이제 내 목소리를 다른 사람의 말과 구분해<br />명령을 실행합니다!</p><button className={styles.primary} onClick={onSaved}>확인</button></div>;
  const n = voice.sentence?.n ?? Math.min(voice.completed + 1, 5);
  return <div className={styles.recording}><div className={styles.recordMeta}><span>{n} / 5 문장</span><span>REC</span></div><blockquote>{ENROLLMENT_SENTENCES[n - 1] ?? '녹음 준비를 기다리고 있습니다.'}</blockquote><div className={styles.liveWave}><b />{Array.from({ length: 46 }, (_, index) => <i key={index} />)}</div><progress max="5" value={voice.completed} /><p>문장을 다 읽으면 자동으로 다음 문장으로 넘어갑니다.</p><div className={styles.actionRow}><button className={styles.secondary} onClick={() => onSend('voice_sentence_retry', { tempId })} disabled={!tempId || voice.pending}>이 문장 다시</button><button className={styles.secondary} onClick={onCancel}>중단</button></div>{voice.pending && <p role="status">서버 응답을 기다리고 있습니다.</p>}{voice.error && <p className={styles.error}>{voice.error}</p>}</div>;
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
