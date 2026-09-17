import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchDevices } from '../../api/devices';
import { fetchSettings, updateSettings } from '../../api/settings';
import { activateProfile, deleteProfile, fetchProfiles, remapDevice } from '../../api/profiles';
import { useOnboardingStore } from '../../store/onboardingStore';
import styles from './DashboardHome.module.css';

export default function SettingsPanel() {
  const navigate = useNavigate(); const [config, setConfig] = useState(null); const [devices, setDevices] = useState({ mics: [], cameras: [] }); const [error, setError] = useState(''); const [pending, setPending] = useState(false); const [confirmKind, setConfirmKind] = useState(null); const [changeKind, setChangeKind] = useState(null); const [selected, setSelected] = useState(''); const [dialog, setDialog] = useState(null);
  useEffect(() => { Promise.all([fetchSettings(), fetchDevices()]).then(([nextConfig, nextDevices]) => { setConfig(nextConfig); setDevices(nextDevices); }).catch((e) => setError(e.message)); }, []);
  if (!config) return <p>{error || '설정을 불러오는 중입니다.'}</p>;
  const current = (kind) => config.settings[kind === 'mic' ? 'micDeviceId' : 'cameraDeviceId'];
  const deviceLabel = (kind) => {
    const values = kind === 'mic' ? devices.mics : devices.cameras;
    const key = kind === 'mic' ? 'micDevice' : 'cameraDevice';
    const matched = values.find((device) => device.id === current(kind));
    return matched?.name ?? config.settings[key] ?? (kind === 'mic' ? '시스템 설정 마이크 (기본)' : '사용 가능한 카메라 없음');
  };
  const list = changeKind === 'mic' ? devices.mics : devices.cameras;
  function beginChange(kind) { const values = kind === 'mic' ? devices.mics : devices.cameras; setChangeKind(kind); setSelected(current(kind) ?? (kind === 'camera' ? values[0]?.id ?? '' : '')); setConfirmKind(kind); }
  function finishChange() { setDialog(null); setConfirmKind(null); setChangeKind(null); setSelected(''); }
  async function persistSelectedDevice() {
    const key = changeKind === 'mic' ? 'mic' : 'camera';
    const item = list.find((device) => device.id === selected);
    const settings = { ...config.settings, [`${key}Device`]: item?.name ?? null, [`${key}DeviceId`]: item?.id ?? null };
    const saved = await updateSettings({ settings, updatedAt: config.updatedAt });
    setConfig(saved);
    return item;
  }
  async function saveDevice() {
    const kind = changeKind; const item = list.find((device) => device.id === selected); if (kind === 'camera' && !item) { setError('사용할 카메라를 선택해주세요.'); return; }
    setPending(true); setError('');
    try {
      if (!item) { await persistSelectedDevice(); setDialog({ type: 'success', message: '시스템 기본 마이크 설정으로 변경했습니다.' }); return; }
      const remap = await remapDevice(kind, item.name);
      const profiles = (await fetchProfiles(kind)).items ?? [];
      const activeId = profiles.find((profile) => profile.active)?.id;
      const unused = (items) => (items ?? []).filter((profile) => !profile.active && profile.id !== activeId);
      if (remap.activated) { await persistSelectedDevice(); setDialog({ type: 'success', message: `기존 ${kind === 'mic' ? '음성 학습' : '시선 보정'} 데이터로 자동 전환했습니다.`, profile: remap.activated }); }
      else if (unused(remap.matches).length > 0) setDialog({ type: 'choose', matches: unused(remap.matches) });
      else setDialog({ type: profiles.length >= 4 ? 'limit' : 'missing', profiles: unused(profiles) });
    } catch (e) { setError(e.message); setChangeKind(null); } finally { setPending(false); }
  }
  async function activate(id) { setPending(true); try { await activateProfile(changeKind, id); await persistSelectedDevice(); setDialog({ type: 'success', message: '선택한 학습 데이터로 전환했습니다.' }); } catch (e) { setError(e.message); } finally { setPending(false); } }
  async function removeAndEnroll(id) { setPending(true); try { await deleteProfile(changeKind, id); startEnrollment(); } catch (e) { setError(e.message); setPending(false); } }
  function startEnrollment() {
    const item = list.find((device) => device.id === selected);
    if (changeKind === 'mic') useOnboardingStore.getState().resetVoiceEnrollment();
    navigate(`/onboarding?step=${changeKind === 'mic' ? 'micStart' : 'gazeStart'}&mode=${changeKind}`, {
      state: { deviceChange: { kind: changeKind, deviceId: item?.id ?? null, deviceName: item?.name ?? null } },
    });
  }
  // 추정값 - 원본 이미지에서 명확히 확인 불가: 좌측 광원 투명도와 회전·파형 애니메이션 속도
  return <div className={styles.settings}><svg className={styles.settingsCorner} viewBox="0 0 280 92" preserveAspectRatio="none" aria-hidden="true"><path className={styles.cornerUpper} d="M0 10h84l34 35h126" /><path className={styles.cornerLower} d="M0 29h72l45 45h105l31 18" /><path className={styles.cornerTail} d="M117 58h106" /><g className={styles.cornerHatch}><path d="M15 7h11M32 7h11M49 7h11" /><path d="M142 70h10M159 70h10M176 70h10" /></g><g className={styles.cornerMarks}><rect x="97" y="42" width="10" height="4" rx="1" /><rect x="112" y="42" width="10" height="4" rx="1" /><rect x="127" y="42" width="10" height="4" rx="1" /></g><path className={styles.cornerWedge} d="M232 68h28l20 19v5h-18Z" /></svg><div className={styles.settingsVisual} aria-hidden="true"><ScannerVisual /></div>
    <div className={`${styles.settingRow} ${styles.wakeRow}`}><label>호출명 (Wake Word)<input value="시아야" readOnly aria-readonly="true" /></label><button disabled>저장</button><small>한국어 이름으로 입력해주세요.</small></div><div className={`${styles.settingRow} ${styles.deviceRow}`}><label>마이크<div className={styles.deviceValue} title={deviceLabel('mic')}>{deviceLabel('mic')}</div></label><button onClick={() => beginChange('mic')}>변경</button></div><div className={`${styles.settingRow} ${styles.deviceRow}`}><label>카메라<div className={styles.deviceValue} title={deviceLabel('camera')}>{deviceLabel('camera')}</div></label><button onClick={() => beginChange('camera')}>변경</button></div><Toggle label="컴퓨터 시작 시 자동 실행" description="컴퓨터 전원을 켜면 SIA가 자동으로 함께 실행됩니다." checked={config.settings.autoStart} onChange={async (checked) => { try { setConfig(await updateSettings({ settings: { ...config.settings, autoStart: checked }, updatedAt: config.updatedAt })); } catch (e) { setError(e.message); } }} />
    {error && <p className={styles.error}>{error}</p>}{confirmKind && <Modal><DeviceIcon kind={confirmKind} /><h2>{confirmKind === 'mic' ? '마이크' : '카메라'} 변경</h2><label className={styles.deviceChoice}>{confirmKind === 'mic' ? '마이크' : '카메라'}<select value={selected} onChange={(e) => setSelected(e.target.value)}>{confirmKind === 'mic' && <option value="">시스템 기본 마이크</option>}{list.map((item) => <option value={item.id} key={item.id}>{item.name}{item.isDefault ? ' (기본)' : ''}</option>)}</select></label><p>장치를 변경하면 해당 장치의 기존 학습 데이터를 자동 전환합니다.</p><div className={styles.dialogActions}><button onClick={finishChange}>취소</button><button className={styles.primary} onClick={() => { setConfirmKind(null); saveDevice(); }} disabled={pending || (confirmKind === 'camera' && !selected)}>변경</button></div></Modal>}{dialog && <ProfileDialog dialog={dialog} kind={changeKind} pending={pending} close={finishChange} activate={activate} enroll={startEnrollment} removeAndEnroll={removeAndEnroll} />}
  </div>;
}

function ScannerVisual() {
  // 추정값 - 원본 이미지에서 명확히 확인 불가: arc 각도, 파티클 개수, 파형 진폭
  const particles = Array.from({ length: 360 }, (_, index) => {
    const distance = 51 * Math.sqrt((index + 0.5) / 360);
    const angle = index * 2.3999632297;
    const x = 160 + Math.cos(angle) * distance;
    const y = 150 + Math.sin(angle) * distance;
    const edgeFade = Math.max(0.08, 1 - (distance / 51) ** 3.8);
    const lightBias = Math.max(0.22, Math.min(1, 0.76 - (x - 160) / 150 - (y - 150) / 190));
    return <circle cx={x} cy={y} r={index % 9 === 0 ? 1.25 : 0.82} opacity={edgeFade * lightBias} key={index} />;
  });
  const bars = Array.from({ length: 57 }, (_, index) => {
    const center = 28;
    const height = 2 + 55 * Math.exp(-(((index - center) / 3.1) ** 2)) + 27 * Math.exp(-(((index - 17) / 6) ** 2)) + 34 * Math.exp(-(((index - 40) / 6.5) ** 2)) + (index % 4) * 1.8;
    const x = 48 + index * 4;
    return <line x1={x} x2={x} y1={338 - height / 2} y2={338 + height / 2} style={{ '--delay': `${index * -31}ms` }} key={index} />;
  });
  return <svg className={styles.visualScanner} viewBox="0 0 320 420" aria-hidden="true">
    <defs>
      <filter id="scanner-glow" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="2.4" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      <radialGradient id="sphere-base" cx="35%" cy="30%" r="75%"><stop offset="0" stopColor="#29456d" /><stop offset=".48" stopColor="#102544" /><stop offset="1" stopColor="#061225" /></radialGradient>
      <clipPath id="sphere-clip"><circle cx="160" cy="150" r="53" /></clipPath>
    </defs>
    <g className={styles.scannerRings}>
      <circle className={styles.scannerOuter} cx="160" cy="150" r="116" />
      <g className={styles.scannerMiddle}><circle cx="160" cy="150" r="94" /></g>
      <g className={styles.scannerInner}><circle cx="160" cy="150" r="74" /></g>
      <g className={styles.scannerTicks}><path d="M160 20v18M151 29h18M160 262v18M151 271h18" /></g>
      <circle className={styles.scannerMarker} cx="61" cy="91" r="4" />
      <circle className={styles.scannerMarker} cx="245" cy="229" r="4" />
    </g>
    <g className={styles.scannerSphere} clipPath="url(#sphere-clip)"><circle cx="160" cy="150" r="53" fill="url(#sphere-base)" />{particles}</g>
    <circle className={styles.scannerSphereEdge} cx="160" cy="150" r="53" />
    <g className={styles.scannerWave} filter="url(#scanner-glow)">{bars}</g>
  </svg>;
}

function Toggle({ label, description, checked, onChange }) { return <label className={styles.toggleRow}><span><strong>{label}</strong><small>{description}</small></span><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} /></label>; }
function Modal({ children }) { return <div className={styles.modalBackdrop}><section className={styles.modal} role="dialog" aria-modal="true">{children}</section></div>; }
function DeviceIcon({ kind }) {
  return <div className={styles.deviceIcon} aria-hidden="true">{kind === 'mic' ? <svg viewBox="0 0 64 64"><rect x="25" y="13" width="14" height="27" rx="7" /><path d="M18 31v2a14 14 0 0 0 28 0v-2M32 47v8M24 55h16" /><path className={styles.signal} d="M13 25v14M8 28v8M51 25v14M56 28v8" /></svg> : <svg viewBox="0 0 64 64"><rect x="15" y="20" width="34" height="25" rx="3" /><circle cx="32" cy="32.5" r="8" /><path d="m23 20 3-6h12l3 6M32 49v6M25 55h14" /><path className={styles.signal} d="M10 24v17M54 24v17" /></svg>}</div>;
}
function ProfileDialog({ dialog, kind, pending, close, activate, enroll, removeAndEnroll }) {
  const noun = kind === 'mic' ? '음성 학습' : '시선 보정';
  const options = (dialog.matches ?? dialog.profiles ?? []).filter((item) => !item.active);
  const [choice, setChoice] = useState(options[0]?.id ?? null);
  if (dialog.type === 'success') return <Modal><DeviceIcon kind={kind} /><h2>{dialog.message}</h2>{dialog.profile && <p>‘{dialog.profile.name}’ 데이터 사용</p>}<button className={styles.primary} onClick={close}>확인</button></Modal>;
  if (dialog.type === 'missing') return <Modal><DeviceIcon kind={kind} /><h2>이 장치의 {noun} 데이터가 없습니다</h2><p>지금 새로 등록하거나 나중에 진행할 수 있습니다.</p><div className={styles.dialogActions}><button onClick={close}>나중에</button><button className={styles.primary} onClick={enroll}>지금 시작</button></div></Modal>;
  return <Modal><DeviceIcon kind={kind} /><h2>{dialog.type === 'limit' ? '저장 한도를 초과합니다' : `이 장치의 ${noun} 데이터가 ${options.length}개 있습니다`}</h2><p>{dialog.type === 'limit' ? `삭제할 ${noun} 데이터 1개를 선택한 뒤 새 등록을 진행합니다.` : '사용할 데이터를 선택해주세요.'}</p><div className={styles.profileList}>{options.map((item) => <label key={item.id}><input type="radio" checked={choice === item.id} onChange={() => setChoice(item.id)} /><span><strong>{item.name}</strong><small>등록 {item.createdAt ?? '-'} · 마지막 사용 {item.lastUsedAt ?? '-'}</small></span></label>)}</div><div className={styles.dialogActions}><button onClick={close}>취소</button><button className={styles.primary} disabled={!choice || pending} onClick={() => dialog.type === 'limit' ? removeAndEnroll(choice) : activate(choice)}>{dialog.type === 'limit' ? '삭제 후 계속' : '선택한 데이터 사용'}</button></div></Modal>;
}
