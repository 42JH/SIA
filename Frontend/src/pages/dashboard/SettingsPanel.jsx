import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchDevices } from '../../api/devices';
import { fetchSettings, updateSettings } from '../../api/settings';
import { activateProfile, deleteProfile, fetchProfiles, remapDevice } from '../../api/profiles';
import styles from './DashboardHome.module.css';

export default function SettingsPanel() {
  const navigate = useNavigate(); const [config, setConfig] = useState(null); const [devices, setDevices] = useState({ mics: [], cameras: [] }); const [error, setError] = useState(''); const [pending, setPending] = useState(false); const [confirmKind, setConfirmKind] = useState(null); const [changeKind, setChangeKind] = useState(null); const [selected, setSelected] = useState(''); const [dialog, setDialog] = useState(null);
  useEffect(() => { Promise.all([fetchSettings(), fetchDevices()]).then(([nextConfig, nextDevices]) => { setConfig(nextConfig); setDevices(nextDevices); }).catch((e) => setError(e.message)); }, []);
  if (!config) return <p>{error || '설정을 불러오는 중입니다.'}</p>;
  const current = (kind) => config.settings[kind === 'mic' ? 'micDeviceId' : 'cameraDeviceId'];
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
      if (remap.activated) { await persistSelectedDevice(); setDialog({ type: 'success', message: `기존 ${kind === 'mic' ? '음성 학습' : '시선 보정'} 데이터로 자동 전환했습니다.`, profile: remap.activated }); }
      else if ((remap.matches ?? []).length > 1) setDialog({ type: 'choose', matches: remap.matches });
      else { const profiles = await fetchProfiles(kind); setDialog({ type: profiles.items.length >= 4 ? 'limit' : 'missing', profiles: profiles.items }); }
    } catch (e) { setError(e.message); setChangeKind(null); } finally { setPending(false); }
  }
  async function activate(id) { setPending(true); try { await activateProfile(changeKind, id); await persistSelectedDevice(); setDialog({ type: 'success', message: '선택한 학습 데이터로 전환했습니다.' }); } catch (e) { setError(e.message); } finally { setPending(false); } }
  async function removeAndEnroll(id) { setPending(true); try { await deleteProfile(changeKind, id); startEnrollment(); } catch (e) { setError(e.message); setPending(false); } }
  function startEnrollment() {
    const item = list.find((device) => device.id === selected);
    navigate(`/onboarding?step=${changeKind === 'mic' ? 'micStart' : 'gazeStart'}&mode=${changeKind}`, {
      state: { deviceChange: { kind: changeKind, deviceId: item?.id ?? null, deviceName: item?.name ?? null } },
    });
  }
  return <div className={styles.settings}>
    <div className={styles.settingRow}><label>호출명 (Wake Word)<input value="시아야" readOnly aria-readonly="true" /></label><button disabled>저장</button><small>호출명은 시아야로 고정됩니다.</small></div><div className={styles.settingRow}><label>마이크<select value={config.settings.micDeviceId ?? ''} disabled><option value="">시스템 설정 마이크 (기본)</option>{devices.mics.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><button onClick={() => beginChange('mic')}>변경</button></div><div className={styles.settingRow}><label>카메라<select value={config.settings.cameraDeviceId ?? devices.cameras[0]?.id ?? ''} disabled>{devices.cameras.length === 0 && <option value="">사용 가능한 카메라 없음</option>}{devices.cameras.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><button onClick={() => beginChange('camera')}>변경</button></div><Toggle label="시선 커서 표시" description="화면에 현재 보고 있는 지점을 원으로 표시" checked={config.settings.gazeCursor} onChange={async (checked) => { try { setConfig(await updateSettings({ settings: { ...config.settings, gazeCursor: checked }, updatedAt: config.updatedAt })); } catch (e) { setError(e.message); } }} /><Toggle label="컴퓨터 시작 시 자동 실행" description="컴퓨터 전원을 켜면 SIA가 자동으로 함께 실행됩니다." checked={config.settings.autoStart} onChange={async (checked) => { try { setConfig(await updateSettings({ settings: { ...config.settings, autoStart: checked }, updatedAt: config.updatedAt })); } catch (e) { setError(e.message); } }} />
    {error && <p className={styles.error}>{error}</p>}{confirmKind && <Modal><div className={styles.alertIcon}>!</div><h2>{confirmKind === 'mic' ? '마이크' : '카메라'}를 변경하시겠습니까?</h2><label className={styles.deviceChoice}>{confirmKind === 'mic' ? '마이크' : '카메라'}<select value={selected} onChange={(e) => setSelected(e.target.value)}>{confirmKind === 'mic' && <option value="">시스템 기본 마이크</option>}{list.map((item) => <option value={item.id} key={item.id}>{item.name}{item.isDefault ? ' (기본)' : ''}</option>)}</select></label><p>장치를 변경하면 해당 장치의 기존 학습 데이터를 자동 전환합니다.</p><div className={styles.dialogActions}><button onClick={finishChange}>취소</button><button className={styles.primary} onClick={() => { setConfirmKind(null); saveDevice(); }} disabled={pending || (confirmKind === 'camera' && !selected)}>변경</button></div></Modal>}{dialog && <ProfileDialog dialog={dialog} kind={changeKind} pending={pending} close={finishChange} activate={activate} enroll={startEnrollment} removeAndEnroll={removeAndEnroll} />}
  </div>;
}

function Toggle({ label, description, checked, onChange }) { return <label className={styles.toggleRow}><span><strong>{label}</strong><small>{description}</small></span><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} /></label>; }
function Modal({ children }) { return <div className={styles.modalBackdrop}><section className={styles.modal} role="dialog" aria-modal="true">{children}</section></div>; }
function ProfileDialog({ dialog, kind, pending, close, activate, enroll, removeAndEnroll }) {
  const noun = kind === 'mic' ? '음성 학습' : '시선 보정'; const [choice, setChoice] = useState(dialog.matches?.[0]?.id ?? dialog.profiles?.find((item) => !item.active)?.id ?? null);
  if (dialog.type === 'success') return <Modal><div className={styles.alertIcon}>✓</div><h2>{dialog.message}</h2>{dialog.profile && <p>‘{dialog.profile.name}’ 데이터 사용</p>}<button className={styles.primary} onClick={close}>확인</button></Modal>;
  if (dialog.type === 'missing') return <Modal><div className={styles.alertIcon}>!</div><h2>이 장치의 {noun} 데이터가 없습니다</h2><p>지금 새로 등록하거나 나중에 진행할 수 있습니다.</p><div className={styles.dialogActions}><button onClick={close}>나중에</button><button className={styles.primary} onClick={enroll}>지금 시작</button></div></Modal>;
  const options = dialog.matches ?? dialog.profiles.filter((item) => !item.active);
  return <Modal><h2>{dialog.type === 'limit' ? '저장 한도(4개)를 초과합니다' : `이 장치의 ${noun} 데이터가 ${options.length}개 있습니다`}</h2><p>{dialog.type === 'limit' ? `삭제할 ${noun} 데이터 1개를 선택한 뒤 새 등록을 진행합니다.` : '사용할 데이터를 선택해주세요.'}</p><div className={styles.profileList}>{options.map((item) => <label key={item.id}><input type="radio" checked={choice === item.id} onChange={() => setChoice(item.id)} /><span><strong>{item.name}</strong><small>등록 {item.createdAt ?? '-'} · 마지막 사용 {item.lastUsedAt ?? '-'}</small></span></label>)}</div><div className={styles.dialogActions}><button onClick={close}>취소</button><button className={styles.primary} disabled={!choice || pending} onClick={() => dialog.type === 'limit' ? removeAndEnroll(choice) : activate(choice)}>{dialog.type === 'limit' ? '삭제 후 계속' : '선택한 데이터 사용'}</button></div></Modal>;
}
