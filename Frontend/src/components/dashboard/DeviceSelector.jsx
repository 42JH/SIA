import styles from './DeviceSelector.module.css';

export default function DeviceSelector({ label, devices, value, onChange, disabled }) {
  return <div className={styles.device}>
    <label>{label}<select value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled}>
      {disabled && devices.length === 0 && <option value="">장치 목록을 불러오는 중입니다</option>}
      {!disabled && devices.length === 0 && <option value="">사용 가능한 {label} 없음</option>}
      {devices.map((item) => <option value={item.id} key={item.id}>{item.name}{item.isDefault ? ' (기본)' : ''}</option>)}
    </select></label>
    <span>{devices.length > 0 ? '정상' : '확인 필요'}</span>
  </div>;
}
