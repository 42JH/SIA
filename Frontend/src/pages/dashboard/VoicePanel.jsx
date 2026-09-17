import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchDevices } from '../../api/devices';
import { fetchSettings, updateSettings } from '../../api/settings';
import { activateProfile, deleteProfile, fetchProfiles, renameVoiceProfile, voiceSampleUrl } from '../../api/profiles';
import { ENROLLMENT_SENTENCES } from '../onboarding/enrollmentConstants';
import { useSessionStore } from '../../store/sessionStore';
import { useVoiceStore } from '../../store/voiceStore';
import { initializeVoiceEvents, sendVoice } from '../../ws/voices';
import { useMicPreview } from '../../hooks/useMicPreview';
import styles from './VoicePanel.module.css';

initializeVoiceEvents();

const formatDate = (value) => value ? `등록일 ${value.slice(0, 10).replaceAll('-', '.')}` : '등록일 미제공';
const rejectionMessages = {
  TOO_SHORT: '너무 짧게 들렸어요. 문장을 끝까지 읽어주세요.',
  TOO_LONG: '너무 길게 들렸어요. 화면의 문장 하나만 읽어주세요.',
  NOISY: '주변이 시끄러워요. 조용한 곳에서 다시 읽어주세요.',
  INCONSISTENT: '앞 문장과 목소리가 다르게 들려요. 같은 분이 조용한 곳에서 다시 읽어주세요.',
};
// 추정값 - 원본 이미지에서 명확히 확인 불가
const WAVE_HEIGHTS = [34, 56, 43, 27, 39, 51, 76, 48, 31, 62, 84, 57, 36, 46, 69, 91, 53, 33, 61, 78, 45, 29, 49, 73, 55, 37, 65, 82, 58, 42, 69, 50];

export default function VoicePanel({ onBack }) {
  const voice = useVoiceStore();
  const connected = useSessionStore((state) => state.wsConnected);
  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState('');
  const [modal, setModal] = useState(null);
  const [deleteMode, setDeleteMode] = useState(false);
  const [selected, setSelected] = useState([]);
  const [micLabel, setMicLabel] = useState(null);
  const [micDevices, setMicDevices] = useState([]);
  const [selectedMicId, setSelectedMicId] = useState('');
  const [settingsConfig, setSettingsConfig] = useState(null);
  const [busy, setBusy] = useState(false);
  const [playingProfileId, setPlayingProfileId] = useState(null);
  const audioRef = useRef(null);
  const active = useMemo(() => profiles.find((item) => item.active), [profiles]);
  const stored = useMemo(() => profiles.filter((item) => !item.active), [profiles]);
  const micPreview = useMicPreview(connected && voice.stage !== 'list' && voice.stage !== 'done');

  useEffect(() => {
    const stale = useVoiceStore.getState();
    if (stale.tempId) { try { sendVoice('voice_reg_cancel', { tempId: stale.tempId }); } catch { /* 재진입 시 초기화 우선 */ } }
    stale.resetEnrollment();
    loadProfiles();
    return () => {
      audioRef.current?.pause(); audioRef.current = null;
      const current = useVoiceStore.getState();
      if (current.tempId) { try { sendVoice('voice_reg_cancel', { tempId: current.tempId }); } catch { /* 이탈 시 초기화 우선 */ } }
      current.resetEnrollment();
    };
  }, []);
  useEffect(() => {
    if (voice.stage !== 'processing') return undefined;
    const timer = setTimeout(() => voice.change({ error: '녹음 확인 응답이 지연되고 있습니다. AI 연결 상태를 확인해주세요.' }), 30000);
    return () => clearTimeout(timer);
  }, [voice.stage, voice.change]);

  async function loadProfiles() { setLoading(true); setPageError(''); try { setProfiles((await fetchProfiles('mic')).items ?? []); } catch (error) { setPageError(error.message); } finally { setLoading(false); } }
  async function prepareEnrollment() {
    voice.resetEnrollment(); setBusy(true); setPageError('');
    try {
      const [settingsResult, devicesResult] = await Promise.all([fetchSettings(), fetchDevices()]);
      setSettingsConfig(settingsResult); setMicDevices(devicesResult.mics);
      const configuredId = settingsResult.settings.micDeviceId; const configuredName = settingsResult.settings.micDevice;
      const configured = devicesResult.mics.find((item) => configuredId ? item.id === configuredId : item.name === configuredName);
      if ((configuredId || configuredName) && !configured) { setMicLabel(configuredName); setModal(null); voice.change({ stage: 'micError', error: '' }); return; }
      const chosen = configured ?? devicesResult.mics.find((item) => item.isDefault) ?? devicesResult.mics[0];
      if (!chosen) { setMicLabel(null); setModal(null); voice.change({ stage: 'micError', error: '' }); return; }
      setSelectedMicId(chosen.id); setMicLabel(chosen.name); setModal(null); voice.change({ stage: 'guide', error: '' });
    } catch (error) { setPageError(error.message); setModal(null); } finally { setBusy(false); }
  }
  async function startRecording() {
    const selectedMic = micDevices.find((item) => item.id === selectedMicId);
    if (!selectedMic) { voice.change({ error: '사용할 마이크를 선택해주세요.' }); return; }
    setBusy(true);
    try {
      const latest = settingsConfig ?? await fetchSettings();
      if (latest.settings.micDeviceId !== selectedMic.id || latest.settings.micDevice !== selectedMic.name) setSettingsConfig(await updateSettings({ settings: { ...latest.settings, micDeviceId: selectedMic.id, micDevice: selectedMic.name }, updatedAt: latest.updatedAt }));
      setMicLabel(selectedMic.name); sendVoice('voice_reg_start'); voice.change({ stage: 'recording', sentence: null, completed: 0, tempId: null, warning: null, review: null, pending: true, error: '' });
    } catch (error) { voice.change({ pending: false, error: error.message }); } finally { setBusy(false); }
  }
  function cancelEnrollment() { const current = useVoiceStore.getState(); if (current.tempId) { try { sendVoice('voice_reg_cancel', { tempId: current.tempId }); } catch { /* 목록 복귀 우선 */ } } current.resetEnrollment(); }
  async function finishEnrollment() { await loadProfiles(); voice.resetEnrollment(); }
  function send(type, data, patch = {}) { try { sendVoice(type, data); voice.change({ pending: true, error: '', ...patch }); } catch (error) { voice.change({ pending: false, error: error.message }); } }
  async function rename() { const name = modal.name.trim(); if (!name) return; setBusy(true); try { await renameVoiceProfile(modal.profile.id, name); await loadProfiles(); setModal({ type: 'success', title: '이름이 변경되었습니다', message: `${modal.profile.name} → ${name}` }); } catch (error) { setPageError(error.message); setModal(null); } finally { setBusy(false); } }
  async function activate(profile) { setBusy(true); setPageError(''); try { const previous = active?.name; await activateProfile('mic', profile.id); await loadProfiles(); setModal({ type: 'success', title: '보이스가 교체되었습니다', message: `${previous} → ${profile.name}` }); } catch (error) { setPageError(error.message); } finally { setBusy(false); } }
  async function removeSelected() { setBusy(true); setPageError(''); try { await Promise.all(selected.map((id) => deleteProfile('mic', id))); await loadProfiles(); setModal(null); setSelected([]); setDeleteMode(false); } catch (error) { setPageError(error.message); setModal(null); await loadProfiles(); } finally { setBusy(false); } }
  function toggle(id) { setSelected((items) => items.includes(id) ? items.filter((item) => item !== id) : [...items, id]); }
  function playProfile(profile) { if (audioRef.current) return; const url = voiceSampleUrl(profile.sampleUrl); if (!url) return; const audio = new Audio(url); const finish = () => { if (audioRef.current !== audio) return; audioRef.current = null; setPlayingProfileId(null); }; audio.addEventListener('ended', finish, { once: true }); audio.addEventListener('error', finish, { once: true }); audioRef.current = audio; setPlayingProfileId(profile.id); audio.play().catch(finish); }

  if (voice.stage !== 'list') return <Enrollment voice={voice} micLabel={micLabel} micDevices={micDevices} selectedMicId={selectedMicId} setSelectedMicId={setSelectedMicId} connected={connected} busy={busy} micLevels={micPreview.levels} micPreviewError={micPreview.error} onStart={startRecording} onRetryMic={prepareEnrollment} onSend={send} onCancel={cancelEnrollment} onSaved={finishEnrollment} />;

  return <section className={styles.voicePage}>
    <VoiceHero title="보이스" subtitle="나만의 목소리로 더 편리한 경험을 시작하세요." onBack={onBack} />
    {(loading || pageError || voice.error) && <p className={pageError || voice.error ? styles.pageError : styles.loading} role="status">{pageError || voice.error || '보이스를 불러오는 중입니다.'}</p>}
    <div className={styles.voiceGrid}><ActiveVoicePanel profile={active} onPlay={() => active && playProfile(active)} playing={active && playingProfileId === active.id} /><section className={`${styles.frame} ${styles.storedPanel}`}><FrameMarks /><div className={styles.listTitle}><span><small>MYVOICES</small><h2>등록된 내 목소리</h2></span>{!deleteMode && <button className={styles.primary} onClick={() => setModal({ type: 'add' })} disabled={profiles.length >= 4 || busy}>＋ 보이스 추가</button>}</div><div className={styles.voiceList}>{stored.map((profile) => <VoiceCard key={profile.id} profile={profile} deleteMode={deleteMode} checked={selected.includes(profile.id)} onToggle={() => toggle(profile.id)} onRename={() => setModal({ type: 'rename', profile, name: profile.name })} onActivate={() => activate(profile)} onPlay={() => playProfile(profile)} playing={playingProfileId === profile.id} playLocked={playingProfileId !== null} busy={busy} />)}</div></section></div>
    <footer className={`${styles.frame} ${styles.bottomBar}`}><span className={styles.noticeIcon}>!</span><strong>목소리 인식이 잘 되지 않으면, 보이스를 추가등록해보세요.</strong>{deleteMode ? <div className={styles.deleteActions}><button onClick={() => { setDeleteMode(false); setSelected([]); }}>취소</button><button className={styles.primary} disabled={!selected.length || busy} onClick={() => setModal({ type: 'delete' })}>완전 삭제</button><span>{selected.length}개 선택됨</span></div> : <button className={styles.secondary} disabled={!stored.length} onClick={() => setDeleteMode(true)}>보이스 삭제</button>}</footer>
    {modal && <VoiceModal modal={modal} setModal={setModal} busy={busy} selectedCount={selected.length} onAdd={prepareEnrollment} onRename={rename} onDelete={removeSelected} onCancelDelete={() => { setModal(null); setSelected([]); setDeleteMode(false); }} />}
  </section>;
}

function VoiceHero({ title, subtitle, onBack }) { // 추정값 - 원본 이미지에서 명확히 확인 불가
  return <header className={styles.voiceHero}><div><div className={styles.heroTitle}>{onBack && <button onClick={onBack} aria-label="이전 화면으로 돌아가기">‹</button>}<h1>{title}</h1></div><p>{subtitle}</p></div><svg className={styles.circuit} viewBox="0 0 760 116" aria-hidden="true"><circle cx="22" cy="62" r="5" /><path d="M27 62h160l36 24h226l56-38h154" /><path className={styles.circuitLight} d="M455 31h128l38-17h95" /><g><circle cx="361" cy="52" r="4" /><circle cx="376" cy="52" r="4" /><circle cx="391" cy="52" r="4" /><circle cx="406" cy="52" r="4" /></g></svg><div className={styles.signalSeal}><MiniWave /></div></header>;
}
function FrameMarks() { return <><i className={styles.frameLine} /><i className={styles.frameDots}>••••</i></>; }
function Wave({ large = false, levels }) { const heights = levels?.length ? levels.map((level) => Math.max(10, level * 100)) : WAVE_HEIGHTS; return <div className={`${styles.wave} ${large ? styles.largeWave : ''}`} aria-hidden="true">{heights.map((height, index) => <i style={{ height: `${height}%` }} key={index} />)}</div>; }
function MiniWave() { return <div className={styles.miniWave}>{[42, 66, 92, 70, 100, 76, 60].map((height, index) => <i style={{ height: `${height}%` }} key={index} />)}</div>; }
function MicIcon({ compact = false }) { return <svg className={`${styles.micIcon} ${compact ? styles.compactMic : ''}`} viewBox="0 0 120 120" aria-hidden="true"><rect x="44" y="19" width="32" height="56" rx="16" /><path d="M30 64v4c0 19 12 31 30 31s30-12 30-31v-4M60 99v15M43 114h34" /></svg>; }
function ActiveVoicePanel({ profile, onPlay, playing }) { return <section className={`${styles.frame} ${styles.activePanel}`}><FrameMarks /><small>ACTIVEVOICE</small><h2>현재 사용 중인 보이스</h2><button className={styles.activeVisual} onClick={onPlay} disabled={!profile?.sampleUrl} aria-label={profile ? `${profile.name} 재생` : '활성 보이스 없음'}><Wave large /><div className={`${styles.micRings} ${playing ? styles.playing : ''}`}><MicIcon /></div></button><div className={styles.activeFooter}><span><strong>{profile?.name ?? '등록된 보이스 없음'}</strong><small>{profile ? formatDate(profile.createdAt) : '보이스를 추가등록해주세요.'}</small></span>{profile && <em><i />사용 중</em>}</div></section>; }
function VoiceCard({ profile, deleteMode, checked, onToggle, onRename, onActivate, onPlay, playing, playLocked, busy }) { return <article className={styles.voiceCard}>{deleteMode && <input type="checkbox" checked={checked} onChange={onToggle} aria-label={`${profile.name} 선택`} />}<button className={styles.cardAudio} onClick={onPlay} disabled={!profile.sampleUrl || playLocked} aria-label={`${profile.name}${playing ? ' 재생 중' : ' 재생'}`}><span><MicIcon compact /></span><Wave /></button><div className={styles.voiceInfo}><span className={styles.nameRow}><strong>{profile.name}</strong>{!deleteMode && <button className={styles.editButton} onClick={onRename} aria-label={`${profile.name} 이름 변경`}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 20 4.2-1 10.6-10.6-3.2-3.2L5 15.8 4 20ZM14.5 6.3l3.2 3.2M13 20h7" /></svg></button>}</span><small>{formatDate(profile.createdAt)}</small></div><button className={styles.pillButton} onClick={onActivate} disabled={busy}>사용으로 설정</button></article>; }

function Enrollment({ voice, micLabel, micDevices, selectedMicId, setSelectedMicId, connected, busy, micLevels, micPreviewError, onStart, onRetryMic, onSend, onCancel, onSaved }) {
  const tempId = voice.tempId; const n = voice.sentence?.n ?? Math.min(voice.completed + 1, voice.total);
  const recording = <RecordingContent voice={voice} n={n} levels={micLevels} previewError={micPreviewError} onRetry={() => onSend('voice_sentence_retry', { tempId })} onCancel={onCancel} />;
  if (voice.stage === 'guide' || voice.stage === 'micError') return <RegistrationPage title="보이스 녹음" onBack={onCancel}><GuideContent total={voice.total} micDevices={micDevices} selectedMicId={selectedMicId} setSelectedMicId={setSelectedMicId} connected={connected} busy={busy} onStart={onStart} />{voice.stage === 'micError' && <StageModal icon="mic" title="마이크를 사용할 수 없어요" description={<>마이크 연결 또는 권한 설정을 확인해주세요.<br />권한을 허용한 뒤 다시 시도할 수 있습니다.</>} secondary="시스템 설정 열기" primary="다시 확인" secondaryDisabled onPrimary={onRetryMic} />}</RegistrationPage>;
  if (voice.stage === 'warning') return <RegistrationPage title="보이스 녹음" onBack={onCancel}>{recording}<StageModal icon="warning" title="목소리가 잘 들리지 않았어요" description={<>{voice.warning?.reason || '제대로 녹음되지 않았습니다. 다시 읽어주세요.'}<br />조용한 곳에서 다시 읽어주세요.</>} secondary="그대로 진행" primary="다시 녹음" onSecondary={() => onSend('voice_accept_anyway', { tempId })} onPrimary={() => onSend('voice_reg_retry', { tempId }, { stage: 'recording', completed: 0, sentence: null, warning: null })} /></RegistrationPage>;
  if (voice.stage === 'processing') return <RegistrationPage title="보이스 녹음" onBack={onCancel}><div className={styles.centerState}><div className={styles.spinner} /><h2>녹음을 확인하고 있습니다</h2><p>녹음 파일과 목소리 데이터를 준비하고 있습니다.</p>{voice.error && <p className={styles.pageError}>{voice.error}</p>}</div></RegistrationPage>;
  if (voice.stage === 'review') { const current = Number(voice.review?.n) || Math.max(1, voice.completed); const rejected = voice.review?.rejected === true; const reason = (rejectionMessages[voice.review?.code] ?? voice.review?.reason?.trim()) || '제대로 녹음되지 않았습니다. 같은 문장을 다시 읽어주세요.'; return <RegistrationPage title="녹음 확인" subtitle="이 목소리로 등록할지 확인해보세요." onBack={onCancel}><ReviewContent review={{ ...voice.review, reason }} current={current} total={voice.total} rejected={rejected} connected={connected} pending={voice.pending} tempId={tempId} error={voice.error} onRetry={() => onSend(rejected || current < voice.total ? 'voice_sentence_retry' : 'voice_reg_retry', { tempId }, { stage: 'recording', ...(!rejected && current >= voice.total ? { completed: 0 } : {}), sentence: null, review: null })} onAccept={() => current >= voice.total ? onSend('voice_commit', { tempId, ...(micLabel ? { deviceLabel: micLabel } : {}) }) : onSend('voice_sentence_next', { tempId }, { stage: 'recording', sentence: null, review: null })} /></RegistrationPage>; }
  if (voice.stage === 'done') return <RegistrationPage title="보이스 녹음" onBack={onSaved}><div className={styles.completeState}><span>✓</span><h2>등록 완료!</h2><p>이제 내 목소리를 다른 사람의 말과 구분해<br />명령을 실행합니다.</p><button className={styles.primary} onClick={onSaved}>확인</button></div></RegistrationPage>;
  return <RegistrationPage title="보이스 녹음" onBack={onCancel}>{recording}</RegistrationPage>;
}
function RegistrationPage({ title, subtitle = '나만의 목소리로 더 편리한 경험을 시작하세요.', onBack, children }) { return <section className={styles.registrationPage}><VoiceHero title={title} subtitle={subtitle} onBack={onBack} /><div className={styles.registrationGrid}><section className={`${styles.frame} ${styles.registrationVisual}`}><FrameMarks /><div className={styles.micRings}><MicIcon /></div></section><section className={`${styles.frame} ${styles.registrationContent}`}><FrameMarks />{children}</section></div></section>; }
function GuideContent({ total, micDevices, selectedMicId, setSelectedMicId, connected, busy, onStart }) { return <div className={styles.guideContent}><h2>조용한 곳에서 {total}문장을 읽어주세요</h2><p>화면에 나오는 문장을 자연스럽게 읽으면 됩니다.<br />약 30초 정도 걸립니다.</p><label className={styles.deviceSelect}><span>마이크 ·</span><select value={selectedMicId} onChange={(event) => setSelectedMicId(event.target.value)} disabled={busy}>{micDevices.map((device) => <option value={device.id} key={device.id}>{device.name}</option>)}</select><strong>{selectedMicId ? '정상' : '확인 필요'}</strong></label><button className={styles.primary} onClick={onStart} disabled={!connected || busy || !selectedMicId}>녹음 시작</button>{!connected && <p className={styles.pageError}>실시간 연결을 기다리고 있습니다.</p>}</div>; }
function RecordingTimer() { const [seconds, setSeconds] = useState(0); useEffect(() => { const timer = setInterval(() => setSeconds((value) => value + 1), 1000); return () => clearInterval(timer); }, []); return <span>REC {String(Math.floor(seconds / 60)).padStart(2, '0')}:{String(seconds % 60).padStart(2, '0')}</span>; }
function RecordingContent({ voice, n, levels, previewError, onRetry, onCancel }) { return <div className={styles.recordingContent}><div className={styles.recordMeta}><strong>{n} / {voice.total} 문장</strong><RecordingTimer /></div><blockquote>{ENROLLMENT_SENTENCES[n - 1] ?? '낭독 문장을 기다리고 있습니다.'}</blockquote><div className={styles.liveAudio}><span><MicIcon compact /></span><Wave levels={levels} /><strong>음성 감지 중</strong></div>{previewError && <p className={styles.previewError} role="status">{previewError}</p>}<div className={styles.progressRow}><progress max={voice.total} value={voice.completed} /><span>문장을 다 읽으면 자동으로 다음</span></div><div className={styles.actionRow}><button onClick={onRetry} disabled={!voice.tempId || voice.pending}>이 문장 다시</button><button onClick={onCancel}>중단</button></div>{voice.error && <p className={styles.pageError}>{voice.error}</p>}</div>; }
function ReviewContent({ review, current, total, rejected, connected, pending, tempId, error, onRetry, onAccept }) { const finalReview = current >= total && !rejected; return <div className={styles.reviewContent}><h2>{finalReview ? '이 목소리로 등록할까요?' : `${current} / ${total} 문장 판독 결과`}</h2><p>{rejected ? review.reason : finalReview ? '재생해 들어보고, 마음에 들지 않으면 다시 녹음할 수 있습니다.' : '판독 결과를 확인한 뒤 다음 문장으로 진행해주세요.'}</p><ReviewAudio sampleUrl={review.sampleUrl} duration={review.durationSec} /><div className={styles.qualityRow}><strong>녹음 품질 · {review.quality?.trim() || '미판정'}</strong><span>주변 소음 {review.noise?.trim() || '없음'}</span></div><div className={styles.actionRow}><button onClick={onRetry} disabled={!connected || pending || !tempId}>다시 녹음</button>{!rejected && <button className={styles.primary} onClick={onAccept} disabled={!connected || pending || !tempId}>{finalReview ? '등록' : '다음 문장'}</button>}</div>{error && <p className={styles.pageError}>{error}</p>}</div>; }
function ReviewAudio({ sampleUrl, duration }) { const audio = useRef(null); const [playing, setPlaying] = useState(false); useEffect(() => () => audio.current?.pause(), []); function play() { const src = voiceSampleUrl(sampleUrl); if (!src || playing) return; const instance = new Audio(src); audio.current = instance; setPlaying(true); const finish = () => setPlaying(false); instance.addEventListener('ended', finish, { once: true }); instance.addEventListener('error', finish, { once: true }); instance.play().catch(finish); } const seconds = Number(duration) || 0; return <button className={styles.reviewAudio} onClick={play} disabled={!sampleUrl}><span><MicIcon compact /></span><Wave /><time>{seconds ? `00:${String(Math.round(seconds)).padStart(2, '0')}` : '00:04'}</time></button>; }
// TODO(BE): Windows 마이크 설정을 여는 FE용 REST·WS 계약 필요
function StageModal({ icon, title, description, secondary, primary, secondaryDisabled = false, onSecondary, onPrimary }) { return <div className={styles.backdrop}><section className={`${styles.modal} ${styles.stageModal}`} role="dialog" aria-modal="true"><FrameMarks /><div className={`${styles.modalIcon} ${icon === 'mic' ? styles.modalMic : ''}`}>{icon === 'mic' ? <MicIcon compact /> : '!'}</div><h2>{title}</h2><p>{description}</p><div className={styles.actionRow}><button onClick={onSecondary} disabled={secondaryDisabled} title={secondaryDisabled ? '백엔드 연동이 필요합니다' : undefined}>{secondary}</button><button className={styles.primary} onClick={onPrimary}>{primary}</button></div></section></div>; }
function VoiceModal({ modal, setModal, busy, selectedCount, onAdd, onRename, onDelete, onCancelDelete }) { const close = () => setModal(null); return <div className={styles.backdrop}><section className={`${styles.modal} ${modal.type === 'rename' ? styles.renameModal : ''}`} role="dialog" aria-modal="true"><FrameMarks />{modal.type === 'add' && <><div className={`${styles.modalIcon} ${styles.modalMic}`}><MicIcon compact /></div><h2>보이스를 추가 등록하시겠습니까?</h2><div className={styles.actionRow}><button onClick={close}>취소</button><button className={styles.primary} onClick={onAdd} disabled={busy}>새로 시작</button></div></>}{modal.type === 'rename' && <><h2>보이스 이름 변경</h2><i className={styles.titleUnderline} /><label>보이스 이름<input value={modal.name} onChange={(event) => setModal({ ...modal, name: event.target.value })} maxLength="50" autoFocus /></label><div className={styles.actionRow}><button onClick={close}>취소</button><button className={styles.primary} onClick={onRename} disabled={busy || !modal.name.trim()}>저장</button></div></>}{modal.type === 'delete' && <><div className={styles.modalIcon}>!</div><h2>선택한 보이스 {selectedCount}개를 삭제하시겠습니까?</h2><p>삭제 후에는 되돌릴 수 없습니다.</p><div className={styles.actionRow}><button onClick={onCancelDelete}>취소</button><button className={styles.primary} onClick={onDelete} disabled={busy}>삭제</button></div></>}{modal.type === 'success' && <><div className={styles.modalIcon}>✓</div><h2>{modal.title}</h2><p className={styles.successMessage}>{modal.message}</p><button className={styles.primary} onClick={close}>확인</button></>}</section></div>; }
