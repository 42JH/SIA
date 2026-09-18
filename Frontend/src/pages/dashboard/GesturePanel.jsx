import { useEffect, useRef, useState } from 'react';
import {
  deleteGesture,
  fetchAllGestures,
  fetchGestureTools,
  fetchRegisteredApps,
  mediaUrl,
  setGestureEnabled,
  updateGesture,
} from '../../api/gestures';
import { useGestureStore } from '../../store/gestureStore';
import {
  assignGestureMacro,
  finishGestureRecording,
  startGestureRegistration,
  startGesturePreview,
  stopGesturePreview,
  subscribeGestures,
} from '../../ws/gestures';
import { isTauriRuntime, pickNativeAbsolutePath } from '../../utils/nativePathDialog';
import styles from './GesturePanel.module.css';

const toolLabels = {
  'app.launch': '앱 실행',
  'browser.search': '브라우저 검색',
  'browser.dom_text': '페이지 내용 읽기',
  'window.focus': '창 선택',
  'window.minimize': '창 최소화',
  'window.maximize': '창 최대화',
  'window.restore': '창 복원',
  'window.resize': '창 크기 변경',
  'window.next': '다음 창',
  'window.prev': '이전 창',
  'scroll.step': '화면 스크롤',
  'media.play_pause': '재생 / 일시정지',
  'media.mute_toggle': '음소거 전환',
  'media.next': '다음 미디어',
  'media.prev': '이전 미디어',
  'media.seek': '재생 위치 이동',
  'volume.step': '볼륨 올리기 / 내리기',
  'volume.set': '볼륨 설정',
  'files.open': '파일 열기',
  'files.save': '텍스트 파일 저장',
  'system.lock': '화면 잠금',
  'screen.capture': '화면 캡처',
  'screen.capture_region': '영역 캡처',
  'session.extend': '세션 연장',
  'session.cancel': '세션 종료',
  'context.get': '화면 상황 확인',
  'explorer.items': '탐색기 항목 확인',
};

const defaultGestureCatalog = [
  { name: 'Closed_Fist', label: '주먹 쥐기', description: '주먹을 꽉 쥔 모양입니다.' },
  { name: 'Open_Palm', label: '손바닥 펴기', description: '손바닥을 활짝 편 모양입니다.' },
  { name: 'Pointing_Up', label: '검지 올리기', description: '검지손가락만 위로 치켜세운 모양입니다.' },
  { name: 'Thumb_Down', label: '엄지 내리기', description: '엄지손가락을 아래로 내린 모양입니다.' },
  { name: 'Thumb_Up', label: '엄지 올리기', description: '엄지손가락을 위로 올린 모양입니다.' },
  { name: 'Victory', label: '브이', description: '검지와 중지를 편 브이 모양입니다.' },
  { name: 'ILoveYou', label: '사랑해', description: '엄지, 검지, 새끼손가락을 편 사랑해 수어 제스처입니다.' },
  { name: 'Swipe_Left', label: '왼쪽 스와이프', description: '손을 왼쪽으로 빠르게 쓸어 넘기는 동작입니다.' },
  { name: 'Swipe_Right', label: '오른쪽 스와이프', description: '손을 오른쪽으로 빠르게 쓸어 넘기는 동작입니다.' },
];

function buildDefaultGestures(items) {
  const serverDefaults = items.filter((item) => !item.custom && item.name !== 'None');
  return defaultGestureCatalog.map((definition) => {
    const serverGesture = serverDefaults.find((item) => item.name === definition.name && item.context == null)
      || serverDefaults.find((item) => item.name === definition.name);
    return {
      ...serverGesture,
      ...definition,
      id: serverGesture?.id ?? `default-${definition.name}`,
      kind: 'HAND',
      custom: false,
      enabled: serverGesture?.enabled ?? true,
      // TODO(BE): ILoveYou와 좌우 스와이프가 기본 gesture 시드에 없어 실제 토글 대상 id를 받을 수 없음
      virtual: !serverGesture,
    };
  });
}

const displayName = (gesture) => gesture.custom ? gesture.name : (gesture.label || gesture.name);
const displayTool = (step) => toolLabels[step.tool] || step.tool;
const initialStep = () => ({ tool: '', args: {} });

const isSelectableGestureTool = (tool) => {
  const name = tool?.name || '';
  if (!tool?.available || tool.confirmRequired) return false;
  return name !== 'context.get'
    && name !== 'app.list'
    && !name.startsWith('browser.')
    && name !== 'window.list'
    && name !== 'explorer.items'
    && !name.startsWith('session.')
    && name !== 'screen.capture_region';
};

function CameraIcon({ video = false }) {
  return video ? (
    <svg viewBox="0 0 64 64" aria-hidden="true"><rect x="9" y="17" width="33" height="30" rx="4" /><path d="m42 26 13-7v26l-13-7Z" /></svg>
  ) : (
    <svg viewBox="0 0 64 64" aria-hidden="true"><path d="M20 18h6l3-6h10l3 6h6a7 7 0 0 1 7 7v22a7 7 0 0 1-7 7H16a7 7 0 0 1-7-7V25a7 7 0 0 1 7-7Z" /><circle cx="32" cy="36" r="10" /></svg>
  );
}

const directionLabels = { up: '위', down: '아래', left: '왼쪽', right: '오른쪽' };
const presetLabels = { LEFT_HALF: '화면 왼쪽 절반', RIGHT_HALF: '화면 오른쪽 절반', CENTER: '화면 가운데' };
const argumentLabels = {
  appRef: '앱', winRef: '대상 창', query: '검색어', path: '경로', name: '파일 이름', content: '내용',
  dir: '방향', amount: '이동량', level: '볼륨', preset: '위치', x1: '시작 X', y1: '시작 Y', x2: '끝 X', y2: '끝 Y',
};

function launchAppName(step, apps) {
  if (step?.tool !== 'app.launch') return null;
  const appKey = String(step.args?.appRef ?? '').replace(/^app:/, '');
  if (!appKey) return null;
  return apps.find((app) => app.appKey === appKey)?.displayName || appKey;
}

function displayStepDetail(step, apps) {
  const appName = launchAppName(step, apps);
  if (appName) return `실행 앱 ${appName}`;
  const args = step.args || {};
  const details = Object.entries(args).map(([key, value]) => {
    let displayed = value;
    if (key === 'appRef') {
      const appKey = String(value).replace(/^app:/, '');
      displayed = apps.find((app) => app.appKey === appKey)?.displayName || appKey;
    } else if (key === 'dir') displayed = directionLabels[value] || value;
    else if (key === 'preset') displayed = presetLabels[value] || value;
    else if (key === 'level') displayed = `${value}%`;
    return `${argumentLabels[key] || key}: ${displayed}`;
  });
  return details.join(' · ') || '추가 설정 없이 실행';
}

function shortenPath(path) {
  const name = String(path ?? '').replaceAll('/', '\\').split('\\').filter(Boolean).pop();
  return name ? `...${name}` : String(path ?? '');
}

function displayLinkedAction(step, apps) {
  const appName = launchAppName(step, apps);
  if (appName) return `${displayTool(step)} · ${appName}`;
  if (step.tool === 'files.open' && step.args?.path) return `${displayTool(step)} · ${shortenPath(step.args.path)}`;
  return `${displayTool(step)} · ${displayStepDetail(step, apps)}`;
}

const categoryLabels = {
  app: '앱', browser: '브라우저', context: '화면 정보', explorer: '파일 탐색기', files: '파일 · 폴더',
  media: '미디어', screen: '화면 캡처', scroll: '스크롤', session: '세션', system: '시스템', volume: '볼륨', window: '창',
};

const requiredArgs = {
  'app.launch': ['appRef'],
  'browser.search': ['query'],
  'window.focus': ['winRef'], 'window.minimize': ['winRef'], 'window.maximize': ['winRef'], 'window.restore': ['winRef'], 'window.resize': ['winRef', 'preset'],
  'scroll.step': ['dir'], 'volume.step': ['dir'], 'volume.set': ['level'], 'files.open': ['path'], 'files.save': ['name'],
  'screen.capture_region': ['x1', 'y1', 'x2', 'y2'],
};

function toEditableSteps(steps = []) {
  return steps.map((step) => ({
    tool: step.tool,
    args: step.args || {},
  }));
}

function HoverPreview({ gesture, large = false, comparison = false }) {
  const videoRef = useRef(null);
  const url = mediaUrl(gesture.videoUrl);
  const isImage = gesture.motion === 'STATIC';
  const start = () => videoRef.current?.play().catch(() => {});
  const stop = () => {
    if (!videoRef.current) return;
    videoRef.current.pause();
    videoRef.current.currentTime = 0;
  };

  return (
    <div className={`${styles.preview} ${large ? styles.largePreview : ''} ${comparison ? styles.similarGesturePreview : ''} ${gesture.custom ? styles.customPreview : styles.defaultPreview}`} onMouseEnter={start} onMouseLeave={stop}>
      {url ? (isImage
        ? <img src={url} alt={`${displayName(gesture)} 제스처`} />
        : <video ref={videoRef} src={url} muted loop playsInline preload="metadata" />)
        : <span aria-hidden="true">{gesture.kind === 'FACE' ? '☺' : '✋'}</span>}
      <small>{url ? (isImage ? '등록된 동작 사진' : '커서를 올려 동작 보기') : gesture.custom ? '저장된 미디어 없음' : '기본 제스처'}</small>
    </div>
  );
}

export default function GesturePanel() {
  const { items, loading, error, registration, setItems, setLoading, setError, patchItem, removeItem, beginRegistration } = useGestureStore();
  const [selected, setSelected] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteMode, setDeleteMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);
  const [tools, setTools] = useState([]);
  const [apps, setApps] = useState([]);
  const [appCatalog, setAppCatalog] = useState([]);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const [gestureItems, toolList, appList] = await Promise.all([fetchAllGestures(), fetchGestureTools(), fetchRegisteredApps()]);
      setItems(gestureItems);
      setTools(toolList.filter(isSelectableGestureTool));
      setAppCatalog(appList);
      setApps(appList.filter((app) => app.enabled));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const toggle = async (gesture, enabled) => {
    setError('');
    try {
      await setGestureEnabled(gesture.id, enabled);
      patchItem(gesture.id, { enabled });
      setSelected((current) => current?.id === gesture.id ? { ...current, enabled } : current);
    } catch (requestError) {
      setError(requestError.message);
    }
  };

  const remove = async () => {
    if (!selected) return;
    setDeleting(true);
    try {
      await deleteGesture(selected.id);
      removeItem(selected.id);
      setSelected(null);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setDeleting(false);
    }
  };

  const toggleDeleteSelection = (id) => {
    setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  };

  const removeSelected = async () => {
    if (!selectedIds.length) return;
    setDeleting(true);
    setError('');
    try {
      for (const id of selectedIds) await deleteGesture(id);
      selectedIds.forEach(removeItem);
      setSelectedIds([]);
      setDeleteMode(false);
      setConfirmBulkDelete(false);
    } catch (requestError) {
      setError(requestError.message);
      await load();
    } finally {
      setDeleting(false);
    }
  };

  const basic = buildDefaultGestures(items);
  const custom = items.filter((item) => item.custom);

  if (registration) return <GestureRegistration onClose={() => {}} onSaved={load} />;

  return (
    <>
      <div className={styles.toolbar}>
        <span />
        <div className={styles.toolbarActions}>
          {deleteMode ? <>
            <button onClick={() => { setDeleteMode(false); setSelectedIds([]); }}>취소</button>
            <button className={styles.danger} disabled={!selectedIds.length || deleting} onClick={() => setConfirmBulkDelete(true)}>선택 삭제 ({selectedIds.length})</button>
          </> : <button disabled={!custom.length} onClick={() => { setDeleteMode(true); setSelected(null); }}>제스처 삭제</button>}
          {!deleteMode && <button className={styles.primary} onClick={beginRegistration}>+ 새 제스처 등록</button>}
        </div>
      </div>
      {loading && <p role="status">제스처를 불러오는 중입니다.</p>}
      {error && <p className={styles.error} role="alert">{error}</p>}
      {!loading && <>
        <GestureSection title="기본 제스처" items={basic} onSelect={setSelected} onToggle={toggle} deleteMode={deleteMode} apps={appCatalog} />
        <GestureSection title="내 커스텀 제스처" items={custom} onSelect={setSelected} onToggle={toggle} deleteMode={deleteMode} selectedIds={selectedIds} onSelectForDelete={toggleDeleteSelection} apps={appCatalog} empty="등록한 커스텀 제스처가 없습니다." />
      </>}
      {selected && <GestureDetail
        gesture={selected}
        tools={tools}
        apps={apps}
        appCatalog={appCatalog}
        onClose={() => setSelected(null)}
        onToggle={(enabled) => toggle(selected, enabled)}
        onUpdated={(next) => { patchItem(next.id, next); setSelected(next); }}
        onDelete={remove}
        deleting={deleting}
      />}
      {confirmBulkDelete && <div className={styles.backdrop}><div className={styles.confirm} role="alertdialog" aria-modal="true"><div className={styles.alertIcon}>!</div><h3>제스처 삭제</h3><p>선택한 제스처 {selectedIds.length}개를 삭제하시겠습니까?</p><div className={styles.actions}><button onClick={() => setConfirmBulkDelete(false)}>취소</button><button className={styles.primary} disabled={deleting} onClick={removeSelected}>{deleting ? '삭제 중' : '삭제'}</button></div></div></div>}
    </>
  );
}

function GestureSection({ title, items, onSelect, onToggle, deleteMode = false, selectedIds = [], onSelectForDelete, apps = [], empty }) {
  return (
    <section className={styles.section}>
      <h3>{title}</h3>
      {items.length ? <div className={styles.grid}>{items.map((gesture) => (
        <article key={gesture.id} className={`${styles.card} ${!gesture.enabled ? styles.disabled : ''} ${deleteMode && gesture.custom ? styles.deleteSelectable : ''}`} onClick={() => deleteMode ? gesture.custom && onSelectForDelete?.(gesture.id) : onSelect(gesture)}>
          {deleteMode && gesture.custom ? <label className={styles.deleteCheck} onClick={(event) => event.stopPropagation()}>
            <input type="checkbox" checked={selectedIds.includes(gesture.id)} onChange={() => onSelectForDelete?.(gesture.id)} aria-label={`${displayName(gesture)} 삭제 선택`} />
          </label> : <label className={styles.switch} onClick={(event) => event.stopPropagation()} title={gesture.virtual ? '백엔드 기본 제스처 등록이 필요합니다.' : undefined}>
            <input type="checkbox" checked={gesture.enabled} disabled={gesture.virtual} onChange={(event) => onToggle(gesture, event.target.checked)} aria-label={`${displayName(gesture)} 사용`} />
            <i />
          </label>}
          <HoverPreview gesture={gesture} />
          <div className={styles.cardInfo}><strong>{displayName(gesture)}</strong><span>{gesture.steps?.[0] ? displayLinkedAction(gesture.steps[0], apps) : gesture.custom ? '연결 기능 없음' : '기본 제공'}</span><small className={styles.cardAction}>{deleteMode && gesture.custom ? '선택해서 삭제' : '상세 보기'} <b>›</b></small></div>
          {gesture.custom && !gesture.runnable && <small className={styles.warning}>현재 사용할 수 없는 기능이 포함되어 있습니다.</small>}
        </article>
      ))}</div> : <p className={styles.empty}>{empty}</p>}
    </section>
  );
}

function GestureDetail({ gesture, tools, apps, appCatalog = [], onClose, onToggle, onUpdated, onDelete, deleting }) {
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [name, setName] = useState(gesture.name);
  const [description, setDescription] = useState(gesture.description || '');
  const [repeatable, setRepeatable] = useState(Boolean(gesture.repeatable));
  const [steps, setSteps] = useState(toEditableSteps(gesture.steps));
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setError('');
    let parsedSteps;
    try {
      parsedSteps = parseSteps(steps);
    } catch (parseError) {
      setError(parseError.message);
      return;
    }
    // 기본 제공 제스처는 기능 해제(빈 steps)가 허용되지만 커스텀은 최소 한 단계가 필요하다
    if (gesture.custom && !name.trim()) {
      setError('제스처 이름을 입력해주세요.');
      return;
    }
    if (gesture.custom && !parsedSteps.length) {
      setError('한 개 이상의 기능을 입력해주세요.');
      return;
    }
    // 보낸 필드만 바뀌므로 실제로 바뀐 필드만 담는다 — 기본 제공은 애초에 name · description을 다루지 않는다
    const payload = {};
    if (gesture.custom) {
      if (name.trim() !== gesture.name) payload.name = name.trim();
      const trimmedDescription = description.trim() || null;
      if (trimmedDescription !== (gesture.description || null)) payload.description = trimmedDescription;
    }
    if (repeatable !== Boolean(gesture.repeatable)) payload.repeatable = repeatable;
    if (JSON.stringify(steps) !== JSON.stringify(toEditableSteps(gesture.steps))) payload.steps = parsedSteps;
    if (!Object.keys(payload).length) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      const next = await updateGesture(gesture.id, payload);
      onUpdated(next);
      setEditing(false);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.backdrop} role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className={styles.detailModal} role="dialog" aria-modal="true" aria-labelledby="gesture-detail-title">
        <header><button onClick={onClose} aria-label="닫기">‹</button><h2 id="gesture-detail-title">{editing ? (gesture.custom ? '제스처 수정' : '기본 제스처 기능 수정') : gesture.custom ? '제스처 상세' : '기본 제스처 상세'}</h2><button onClick={onClose} aria-label="닫기">×</button></header>
        <div className={styles.detailLayout}>
          <div className={styles.detailMedia}><h3>{gesture.custom ? '촬영된 동작' : '기본 제스처'}</h3><HoverPreview gesture={gesture} large /><small>{gesture.custom ? 'SIA AI VISION' : 'SIA DEFAULT GESTURE'}</small></div>
          <div className={styles.detailPanel}>
            {editing ? <GestureForm
              custom={gesture.custom}
              name={name} setName={setName} description={description} setDescription={setDescription}
              repeatable={repeatable} setRepeatable={setRepeatable} steps={steps} setSteps={setSteps} tools={tools} apps={apps} error={error}
            /> : <div className={styles.detailBody}>
              <small>GESTURE NAME</small><h3>{displayName(gesture)}</h3>
              <small>GESTURE TYPE</small><strong>{gesture.custom ? '커스텀 제스처' : '기본 제공 제스처'}</strong>
              <small>LINKED ACTION</small>
              {gesture.steps?.length ? <ol className={styles.actionList}>{gesture.steps.map((step, index) => {
                const appName = launchAppName(step, appCatalog.length ? appCatalog : apps);
                return <li key={`${step.tool}-${index}`}><b>{index + 1}. {displayTool(step)}</b>{appName ? <span>실행 앱 · {appName}</span> : <span>{displayStepDetail(step, appCatalog.length ? appCatalog : apps)}</span>}</li>;
              })}</ol> : <strong>연결된 기능 없음</strong>}
              {gesture.createdAt && <><small>REGISTRATION DATE</small><strong>등록일 {gesture.createdAt.slice(0, 10)}</strong></>}
              {!gesture.custom && <p>기본 제스처의 이름과 손 모양은 변경할 수 없습니다. 연결 기능은 수정할 수 있습니다.</p>}
              {!gesture.virtual && <div className={styles.detailToggle}><span><small>USAGE</small>사용 켜기</span><label className={styles.switch}><input type="checkbox" checked={gesture.enabled} onChange={(event) => onToggle(event.target.checked)} /><i /></label></div>}
            </div>}
            <footer className={styles.actions}>
              {editing ? <><button onClick={() => setEditing(false)}>취소</button><button className={styles.primary} disabled={saving} onClick={save}>{saving ? '저장 중' : '저장'}</button></> : gesture.custom ? <><button onClick={() => setEditing(true)}>수정</button><button className={styles.primary} onClick={() => setConfirmDelete(true)}>삭제</button></> : <button className={styles.primary} disabled={gesture.virtual} title={gesture.virtual ? '백엔드 기본 제스처 등록이 필요합니다.' : undefined} onClick={() => setEditing(true)}>기능 수정</button>}
            </footer>
          </div>
        </div>
        {confirmDelete && <div className={styles.innerBackdrop}><div className={styles.confirm} role="alertdialog" aria-modal="true"><div className={styles.alertIcon}>!</div><h3>제스처 삭제</h3><p>‘{displayName(gesture)}’ 제스처를 삭제하시겠습니까?</p><div className={styles.actions}><button onClick={() => setConfirmDelete(false)}>취소</button><button className={styles.primary} disabled={deleting} onClick={onDelete}>{deleting ? '삭제 중' : '삭제'}</button></div></div></div>}
      </section>
    </div>
  );
}

function parseSteps(steps) {
  return steps.map((step, index) => {
    if (!step.tool) throw new Error(`${index + 1}번째 기능을 선택해주세요.`);
    const args = Object.fromEntries(Object.entries(step.args || {}).filter(([, value]) => value !== '' && value != null));
    const missing = (requiredArgs[step.tool] || []).find((key) => args[key] === undefined);
    if (missing) throw new Error(`${index + 1}번째 기능의 설정을 완료해주세요.`);
    if (step.tool === 'files.open' && !/^(?:[a-zA-Z]:[\\/]|\\\\)/.test(args.path)) {
      throw new Error(`${index + 1}번째 기능에 파일 또는 폴더의 절대경로를 입력해주세요.`);
    }
    ['amount', 'level', 'x1', 'y1', 'x2', 'y2'].forEach((key) => {
      if (args[key] !== undefined) args[key] = Number(args[key]);
    });
    if (step.tool === 'scroll.step' && Number.isFinite(args.amount)) args.amount = Math.min(10, Math.max(1, args.amount));
    return { tool: step.tool, args };
  });
}

function GestureForm({ custom = true, name, setName, description, setDescription, repeatable, setRepeatable, steps, setSteps, tools, apps = [], error }) {
  const updateStep = (index, patch) => setSteps(steps.map((step, stepIndex) => stepIndex === index ? { ...step, ...patch } : step));
  const groups = tools.reduce((result, tool) => {
    const category = tool.name.split('.')[0];
    if (!result[category]) result[category] = [];
    result[category].push(tool);
    return result;
  }, {});
  return <div className={styles.form}>
    {custom && <label>제스처 이름<input value={name} onChange={(event) => setName(event.target.value)} placeholder="예: 손가락 하트" /></label>}
    {custom && <label>제스처 설명<input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="어떤 모양과 움직임의 제스처인지 적어주세요." /></label>}
    <div><span>이 제스처로 실행할 기능</span>{steps.map((step, index) => <div className={styles.stepEditor} key={index}>
      <b>{index + 1}</b><select value={step.tool} onChange={(event) => updateStep(index, { tool: event.target.value, args: {} })}><option value="">기능 선택</option>{Object.entries(groups).map(([category, categoryTools]) => <optgroup label={categoryLabels[category] || category} key={category}>{categoryTools.map((tool) => <option value={tool.name} key={tool.name}>{toolLabels[tool.name] || tool.name}</option>)}</optgroup>)}</select>
      <button type="button" className={styles.removeStep} onClick={() => setSteps(steps.filter((_, stepIndex) => stepIndex !== index))} aria-label={`${index + 1}번째 기능 삭제`}>×</button>
      <div className={styles.stepBody}><StepSettings step={step} apps={apps} update={(args) => updateStep(index, { args })} /></div>
    </div>)}<button className={styles.addStep} onClick={() => setSteps((current) => [...current, initialStep()])}>+ 기능 추가하기</button><small>위에서 아래 순서로 실행됩니다.</small></div>
    <label className={styles.repeat}><input type="checkbox" checked={repeatable} onChange={(event) => setRepeatable(event.target.checked)} /> 제스처를 유지하는 동안 반복 실행</label>
    {error && <p className={styles.error} role="alert">{error}</p>}
  </div>;
}

function StepSettings({ step, apps, update }) {
  const set = (key, value) => update({ ...step.args, [key]: value });
  const text = (key, placeholder) => <input value={step.args[key] ?? ''} onChange={(event) => set(key, event.target.value)} placeholder={placeholder} />;

  if (!step.tool) return null;
  if (step.tool === 'app.launch') return <div className={styles.stepSettings}><select value={step.args.appRef ?? ''} onChange={(event) => set('appRef', event.target.value)}><option value="">실행할 앱 선택</option>{apps.map((app) => <option value={`app:${app.appKey}`} key={app.appKey}>{app.displayName}</option>)}</select></div>;
  if (step.tool === 'browser.search') return <div className={styles.stepSettings}>{text('query', '검색어 또는 주소')}</div>;
  if (['window.focus', 'window.minimize', 'window.maximize', 'window.restore'].includes(step.tool)) return <div className={styles.stepSettings}>{text('winRef', '창 참조값 (예: win:1)')}</div>;
  if (step.tool === 'window.resize') return <div className={styles.stepSettings}>{text('winRef', '창 참조값')}<select value={step.args.preset ?? ''} onChange={(event) => set('preset', event.target.value)}><option value="">위치 선택</option><option value="LEFT_HALF">왼쪽 절반</option><option value="RIGHT_HALF">오른쪽 절반</option><option value="CENTER">가운데</option></select></div>;
  if (step.tool === 'explorer.items') return <div className={styles.stepSettings}>{text('winRef', '탐색기 창 참조값 (선택)')}</div>;
  if (step.tool === 'scroll.step') return <div className={styles.stepSettings}><select value={step.args.dir ?? ''} onChange={(event) => set('dir', event.target.value)}><option value="">방향 선택</option><option value="up">위</option><option value="down">아래</option><option value="left">왼쪽</option><option value="right">오른쪽</option></select><input type="number" min="1" max="10" value={step.args.amount ?? ''} onChange={(event) => { const raw = event.target.value; if (raw === '') { set('amount', ''); return; } const next = Number(raw); if (!Number.isFinite(next)) return; set('amount', String(Math.min(10, Math.max(1, Math.round(next))))); }} placeholder="이동량 1~10 (선택)" /></div>;
  if (step.tool === 'volume.step') return <div className={styles.stepSettings}><select value={step.args.dir ?? ''} onChange={(event) => set('dir', event.target.value)}><option value="">방향 선택</option><option value="up">볼륨 올리기</option><option value="down">볼륨 내리기</option></select></div>;
  if (step.tool === 'volume.set') return <div className={styles.stepSettings}><input type="number" min="0" max="100" value={step.args.level ?? ''} onChange={(event) => set('level', event.target.value)} placeholder="볼륨 0~100" /></div>;
  if (step.tool === 'files.open') return <FileTargetPicker path={step.args.path ?? ''} onChange={(path) => set('path', path)} />;
  if (step.tool === 'files.save') return <div className={styles.stepSettings}>{text('name', '저장할 파일 이름')}{text('content', '저장할 내용 (선택)')}</div>;
  if (step.tool === 'screen.capture') return <div className={styles.stepSettings}>{text('winRef', '캡처할 창 참조값 (선택)')}</div>;
  if (step.tool === 'screen.capture_region') return <div className={`${styles.stepSettings} ${styles.coordinates}`}>{['x1', 'y1', 'x2', 'y2'].map((key) => <input type="number" value={step.args[key] ?? ''} onChange={(event) => set(key, event.target.value)} placeholder={key} key={key} />)}</div>;
  return null;
}

function FileTargetPicker({ path, onChange }) {
  const fileInput = useRef(null);
  const folderInput = useRef(null);
  const [targetType, setTargetType] = useState('file');
  const [pickerError, setPickerError] = useState('');
  const [picking, setPicking] = useState(false);
  const [choosingAgain, setChoosingAgain] = useState(!path);

  const chooseFile = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.path) {
      onChange(file.path);
      setChoosingAgain(false);
      setPickerError('');
    } else {
      setPickerError('현재 웹 실행 환경에서는 선택한 파일의 절대경로를 가져올 수 없습니다. 경로를 직접 입력해주세요.');
    }
    event.target.value = '';
  };

  const chooseFolder = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.path && file.webkitRelativePath) {
      const relative = file.webkitRelativePath.replaceAll('/', '\\');
      const rootName = relative.split('\\')[0];
      const base = file.path.slice(0, Math.max(0, file.path.length - relative.length));
      onChange(`${base}${rootName}`);
      setChoosingAgain(false);
      setPickerError('');
    } else {
      setPickerError('현재 웹 실행 환경에서는 선택한 폴더의 절대경로를 가져올 수 없습니다. 경로를 직접 입력해주세요.');
    }
    event.target.value = '';
  };

  const openPicker = async () => {
    if (picking) return;
    setPickerError('');
    const directory = targetType === 'folder';
    setPicking(true);
    try {
      const selectedPath = await pickNativeAbsolutePath({ directory });
      if (typeof selectedPath === 'string' && selectedPath) {
        onChange(selectedPath);
        setChoosingAgain(false);
        return;
      }
      if (selectedPath === null) return;
      if (isTauriRuntime()) {
        setPickerError('Tauri 파일 선택 창을 열 수 없습니다. 경로를 직접 입력해주세요.');
        return;
      }
    } catch {
      if (isTauriRuntime()) {
        setPickerError('네이티브 파일 선택기를 열 수 없습니다. 경로를 직접 입력해주세요.');
        return;
      }
    } finally {
      setPicking(false);
    }
    if (directory) folderInput.current?.click();
    else fileInput.current?.click();
  };

  return <div className={styles.filePicker}>
    {(!path || choosingAgain) && <div className={styles.pickerRow}><select value={targetType} onChange={(event) => setTargetType(event.target.value)} aria-label="열 대상 종류"><option value="file">파일 선택하기</option><option value="folder">폴더 선택하기</option></select><button type="button" onClick={openPicker} disabled={picking}>찾아보기</button></div>}
    <input value={path} onChange={(event) => { onChange(event.target.value); setPickerError(''); setChoosingAgain(!event.target.value); }} placeholder="선택한 파일 또는 폴더의 절대경로" />
    {path && !choosingAgain && <button type="button" className={styles.pickerReset} onClick={() => setChoosingAgain(true)}>다시 선택</button>}
    <input ref={fileInput} className={styles.hiddenPicker} type="file" onChange={chooseFile} />
    <input ref={folderInput} className={styles.hiddenPicker} type="file" webkitdirectory="" directory="" onChange={chooseFolder} />
    {pickerError && <small className={styles.pickerError}>{pickerError}</small>}
  </div>;
}

export function GestureRegistration({ onClose, onSaved }) {
  const { registration, updateRegistration, closeRegistration } = useGestureStore();
  const [tools, setTools] = useState([]);
  const [apps, setApps] = useState([]);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [repeatable, setRepeatable] = useState(false);
  const [steps, setSteps] = useState([initialStep()]);
  const [saving, setSaving] = useState(false);
  const [countdown, setCountdown] = useState(null);
  const [flashTake, setFlashTake] = useState(null);
  const [captureTypeOpen, setCaptureTypeOpen] = useState(false);
  const stopSent = useRef(false);
  const flashedTake = useRef(null);
  const previewStarted = useRef(false);
  const previewSeq = useRef(-1);
  const ignoredTempIds = useRef(new Set());
  const registrationRequested = useRef(false);
  const macroAssignRequested = useRef(false);

  useEffect(() => {
    Promise.all([fetchGestureTools(), fetchRegisteredApps()])
      .then(([list, appList]) => {
        setTools(list.filter(isSelectableGestureTool));
        setApps(appList.filter((app) => app.enabled));
      })
      .catch((error) => updateRegistration({ error: error.message }));
  }, []);

  useEffect(() => subscribeGestures({
    cam_preview_state: (data) => {
      const stage = useGestureStore.getState().registration?.stage;
      if (!['intro', 'waiting', 'capture'].includes(stage)) return;
      if (data.phase === 'READY') {
        previewStarted.current = true;
        updateRegistration({ previewReady: true, error: '' });
        return;
      }
      if (data.phase === 'ERROR' || data.phase === 'STOPPED') {
        previewStarted.current = false;
        previewSeq.current = -1;
        updateRegistration({
          previewReady: false,
          ...(data.phase === 'ERROR' ? { error: data.message || '카메라 인식 화면을 사용할 수 없습니다.' } : {}),
        });
      }
    },
    cam_preview_frame: (data) => {
      const stage = useGestureStore.getState().registration?.stage;
      if (!['intro', 'waiting', 'capture'].includes(stage) || !data.jpegB64) return;
      const seq = Number(data.seq);
      if (!Number.isInteger(seq) || seq < 0 || seq <= previewSeq.current) return;
      previewStarted.current = true;
      previewSeq.current = seq;
      const previewFrame = `data:image/jpeg;base64,${data.jpegB64}`;
      updateRegistration({ previewFrame, previewReady: true, ...(stage === 'capture' && !useGestureStore.getState().registration?.frame ? { frame: previewFrame } : {}) });
    },
    reg_state: (data) => {
      if (!registrationRequested.current) return;
      if (ignoredTempIds.current.has(data.tempId)) return;
      const current = useGestureStore.getState().registration;
      if (current?.tempId && data.tempId !== current.tempId) return;
      const similarTo = data.similarTo ?? data.similar_to ?? data.similarGesture ?? null;
      const rejected = data.phase === 'REJECTED' || Boolean(similarTo);
      if (rejected) updateRegistration({
        tempId: data.tempId,
        stage: 'rejected',
        phase: 'REJECTED',
        similarTo,
        similarity: data.similarity ?? data.score ?? null,
        error: data.reason || (similarTo ? '기존 제스처와 너무 유사하여 등록할 수 없습니다.' : '제스처를 인식하지 못했습니다.'),
      });
      else updateRegistration({ tempId: data.tempId, phase: data.phase, captured: data.phase === 'CAPTURED' ? true : current?.captured, stage: data.phase === 'MODE_STARTED' ? 'capture' : current?.stage });
    },
    reg_take: (data) => {
      if (!registrationRequested.current) return;
      if (ignoredTempIds.current.has(data.tempId)) return;
      const current = useGestureStore.getState().registration;
      if (current?.tempId && data.tempId !== current.tempId) return;
      if (current?.stage === 'rejected') return;
      const completed = data.phase === 'DONE' ? [...new Set([...(current?.completedTakes || []), data.take])] : (current?.completedTakes || []);
      const photoPreviews = current?.motion === 'STATIC' && data.phase === 'DONE' && current.frame
        ? [...(current.previews || []).filter((take) => take.take !== data.take), { take: data.take, previewUrl: current.frame, mediaType: 'IMAGE' }]
        : current?.previews || [];
      updateRegistration({ tempId: data.tempId, stage: 'capture', take: data.take, takePhase: data.phase, completedTakes: completed, previews: photoPreviews });
      if (data.take === 3 && data.phase === 'DONE' && !stopSent.current) {
        stopSent.current = true;
        try { finishGestureRecording(data.tempId); } catch (error) { updateRegistration({ error: error.message }); }
      }
    },
    reg_frame: (data) => {
      // TODO(BE): 카운트다운 중 실시간 프레임 이벤트가 없어 직전 화면만 유지 가능
      if (!registrationRequested.current) return;
      if (ignoredTempIds.current.has(data.tempId)) return;
      const current = useGestureStore.getState().registration;
      if (current?.tempId && data.tempId !== current.tempId) return;
      if (current?.stage === 'rejected') return;
      const frameKey = `${data.tempId}:${data.take}`;
      if (current?.motion === 'STATIC' && flashedTake.current !== frameKey) {
        flashedTake.current = frameKey;
        setFlashTake(frameKey);
      }
      updateRegistration({ tempId: data.tempId, frame: `data:image/jpeg;base64,${data.jpegB64}`, take: data.take, stage: 'capture' });
    },
    reg_recorded: (data) => {
      if (!registrationRequested.current) return;
      if (ignoredTempIds.current.has(data.tempId)) return;
      const current = useGestureStore.getState().registration;
      if (current?.tempId && data.tempId !== current.tempId) return;
      const valid = (data.takes || []).filter((take) => take.previewUrl);
      const previews = valid.length ? valid : current?.previews || [];
      const similarTo = data.similarTo ?? data.similar_to ?? data.similarGesture ?? current?.similarTo ?? null;
      const rejected = current?.stage === 'rejected' || data.phase === 'REJECTED' || data.accepted === false || Boolean(similarTo);
      updateRegistration({
        tempId: data.tempId,
        previews,
        selectedTake: previews[0]?.take || 1,
        stage: rejected ? 'rejected' : 'review',
        similarTo,
        similarity: data.similarity ?? data.score ?? current?.similarity ?? null,
        ...(rejected ? { error: data.reason || current?.error || '기존 제스처와 너무 유사하여 등록할 수 없습니다.' } : data.reason ? { error: data.reason } : {}),
      });
    },
    macro_saved: () => {
      if (!macroAssignRequested.current) return;
      macroAssignRequested.current = false;
      setSaving(false);
      updateRegistration({ stage: 'complete' });
    },
    error: (data) => {
      if (['cam_preview_start', 'cam_preview_stop'].includes(data.of)) {
        previewStarted.current = false;
        previewSeq.current = -1;
        updateRegistration({ previewReady: false, error: data.message || '카메라 미리보기를 시작할 수 없습니다.' });
        return;
      }
      if (!['reg_start', 'reg_stop', 'macro_assign'].includes(data.of)) return;
      if (data.of === 'macro_assign' ? !macroAssignRequested.current : !registrationRequested.current) return;
      if (data.of === 'macro_assign') macroAssignRequested.current = false;
      setSaving(false);
      updateRegistration({
        error: data.message || '제스처 등록 중 오류가 발생했습니다.',
        ...(data.of === 'reg_start' ? { stage: 'intro' } : {}),
      });
    },
  }), [updateRegistration]);

  useEffect(() => {
    if (registration?.stage !== 'intro' || previewStarted.current) return undefined;
    try {
      startGesturePreview();
      previewStarted.current = true;
      previewSeq.current = -1;
      updateRegistration({ previewReady: false, error: '' });
    } catch (error) {
      updateRegistration({ previewReady: false, error: error.message });
    }
    return undefined;
  }, [registration?.stage, updateRegistration]);

  useEffect(() => () => {
    registrationRequested.current = false;
    macroAssignRequested.current = false;
    if (!previewStarted.current) return;
    try { stopGesturePreview(); } catch { /* 연결 종료 시 별도 처리 없음 */ }
    previewStarted.current = false;
    previewSeq.current = -1;
  }, []);

  useEffect(() => {
    if (registration?.takePhase !== 'COUNTDOWN') {
      setCountdown(null);
      return undefined;
    }
    setCountdown(3);
    const timer = setInterval(() => setCountdown((value) => value > 1 ? value - 1 : 1), 1000);
    return () => clearInterval(timer);
  }, [registration?.take, registration?.takePhase]);

  const stopPreview = () => {
    if (!previewStarted.current) return;
    try { stopGesturePreview(); } catch (error) { updateRegistration({ error: error.message }); }
    previewStarted.current = false;
    previewSeq.current = -1;
    updateRegistration({ previewReady: false });
  };

  const start = (motion = registration.motion) => {
    if (!motion) return;
    const initialFrame = registration.previewFrame;
    stopPreview();
    setCaptureTypeOpen(false);
    const currentTempId = useGestureStore.getState().registration?.tempId;
    if (currentTempId) ignoredTempIds.current.add(currentTempId);
    stopSent.current = false;
    flashedTake.current = null;
    setFlashTake(null);
    updateRegistration({
      stage: 'waiting',
      motion,
      tempId: null,
      phase: null,
      take: 0,
      takePhase: null,
      frame: initialFrame,
      completedTakes: [],
      previews: [],
      captured: false,
      selectedTake: 1,
      similarTo: null,
      similarity: null,
      error: '',
    });
    registrationRequested.current = true;
    try { startGestureRegistration(motion); } catch (error) {
      registrationRequested.current = false;
      updateRegistration({ stage: 'intro', error: error.message });
    }
  };

  const next = () => updateRegistration({ stage: 'form', error: '' });
  const save = () => {
    const hasName = Boolean(name.trim());
    const hasSelectedFunction = steps.some((step) => Boolean(step.tool));
    if (!hasName && !hasSelectedFunction) { updateRegistration({ error: '제스처 이름과 한 개 이상의 기능을 입력해주세요.' }); return; }
    if (!hasName) { updateRegistration({ error: '제스처 이름을 입력해주세요.' }); return; }
    if (!hasSelectedFunction) { updateRegistration({ error: '한 개 이상의 기능을 선택해주세요.' }); return; }
    let parsedSteps;
    try { parsedSteps = parseSteps(steps); } catch (error) { updateRegistration({ error: error.message }); return; }
    if (!parsedSteps.length) { updateRegistration({ error: '한 개 이상의 기능을 선택해주세요.' }); return; }
    setSaving(true);
    macroAssignRequested.current = true;
    updateRegistration({ error: '' });
    try {
      assignGestureMacro({ tempId: registration.tempId, take: registration.selectedTake, name: name.trim(), description: description.trim() || undefined, repeatable, steps: parsedSteps });
    } catch (error) {
      macroAssignRequested.current = false;
      setSaving(false);
      updateRegistration({ error: error.message });
    }
  };
  const close = () => { stopPreview(); closeRegistration(); onClose(); };

  if (!registration) return null;
  const stageTitle = registration.stage === 'review' ? '촬영 결과' : ['rejected', 'form', 'complete'].includes(registration.stage) ? '제스처 등록' : '제스처 촬영';
  const selectedPreview = registration.previews.find((take) => take.take === registration.selectedTake) || registration.previews[0];
  const selectedPreviewIsImage = (selectedPreview?.mediaType || (registration.motion === 'STATIC' ? 'IMAGE' : 'VIDEO')) === 'IMAGE';
  return <div className={styles.registration}>
    <div className={styles.registrationHeading}><button onClick={close} aria-label="제스처 목록으로 돌아가기">‹</button><div><h1>{stageTitle}</h1>{registration.stage === 'form' && <p>나만의 제스처로 더 편리한 일상을 만들어보세요.</p>}{registration.stage === 'complete' && <p>새로운 제스처 등록이 완료되었습니다.</p>}</div></div>
    <div className={styles.registrationBody}>
      {/* TODO(BE): 카메라 사용 불가 시 시스템 카메라 설정을 여는 API가 명세에 없음 */}
      {registration.stage === 'intro' && <><div className={styles.cameraBox}>{registration.previewFrame ? <img src={registration.previewFrame} alt="AI 카메라 미리보기" /> : <span>{registration.previewReady ? '카메라 화면을 기다리고 있습니다.' : 'AI 카메라를 준비하고 있습니다.'}</span>}<b className={styles.cameraState}>{registration.previewReady ? '● 카메라 준비 완료' : '카메라 연결 중'}</b></div><p>카메라 화면과 연결 상태를 확인한 뒤 촬영 버튼을 눌러주세요.</p><button className={styles.primary} disabled={!registration.previewReady} onClick={() => setCaptureTypeOpen(true)}>촬영하기</button><small>화면에 손과 동작 범위가 모두 보이는지 확인해주세요.</small>{captureTypeOpen && <CaptureTypeDialog onClose={() => setCaptureTypeOpen(false)} onSelect={start} />}</>}
      {registration.stage === 'waiting' && <><div className={styles.cameraBox}>카메라 연결을 기다리고 있습니다.</div><p>잠시만 기다려주세요.</p></>}
      {registration.stage === 'capture' && <>
        <div className={styles.liveFrame}>
          {(registration.frame || registration.previewFrame) ? <img src={registration.frame || registration.previewFrame} alt="제스처 촬영 화면" /> : <span>카메라 화면을 기다리고 있습니다.</span>}
          <b className={registration.motion === 'DYNAMIC' && registration.takePhase === 'RECORDING' ? styles.recordingIndicator : undefined}>● {registration.motion === 'STATIC' ? 'PHOTO' : 'REC'} {registration.take || 1}/3</b>
          {registration.takePhase === 'COUNTDOWN' && <strong className={styles.countdown} aria-live="assertive">{countdown ?? 3}</strong>}
          {registration.takePhase === 'COUNTDOWN' && registration.frame && <small className={styles.frameNotice}>직전 화면</small>}
          {flashTake && <span className={styles.captureFlash} key={flashTake} aria-hidden="true" />}
        </div>
        <div className={styles.progress}><i style={{ width: `${Math.max(registration.take - (registration.takePhase === 'DONE' ? 0 : 1), 0) / 3 * 100}%` }} /></div>
        <p>{registration.takePhase === 'COUNTDOWN' ? `${registration.take}회차 촬영을 준비하세요.` : registration.takePhase === 'DONE' && registration.take === 3 ? `${registration.motion === 'STATIC' ? '촬영 사진' : '촬영 영상'}을 처리하고 있습니다.` : `${registration.take || 1}/3회 ${registration.motion === 'STATIC' ? '사진 촬영 중' : '인식 중'}`}</p>
        <button className={styles.cancelCapture} onClick={close}>촬영 취소</button>
      </>}
      {registration.stage === 'review' && <Review registration={registration} onSelect={(selectedTake) => updateRegistration({ selectedTake })} onRetry={() => start(registration.motion)} onNext={next} />}
      {registration.stage === 'rejected' && <RegistrationRejected registration={registration} onRetry={() => start(registration.motion)} />}
      {registration.stage === 'form' && <div className={styles.registrationWorkspace}><div className={styles.capturedPanel}><h3>촬영한 동작</h3><div className={styles.capturedMedia}>{selectedPreview && (selectedPreviewIsImage ? <img src={mediaUrl(selectedPreview.previewUrl)} alt="선택한 제스처" /> : <video src={mediaUrl(selectedPreview.previewUrl)} muted loop autoPlay playsInline />)}</div><span>{name || '새 제스처'}</span></div><div className={styles.registrationFormPanel}><GestureForm name={name} setName={setName} description={description} setDescription={setDescription} repeatable={repeatable} setRepeatable={setRepeatable} steps={steps} setSteps={setSteps} tools={tools} apps={apps} error={registration.error} /><div className={styles.actions}><button onClick={close}>취소</button><button className={styles.primary} disabled={saving} onClick={save}>{saving ? '저장 중' : '다음'}</button></div></div></div>}
      {registration.stage === 'complete' && <div className={styles.registrationWorkspace}><div className={styles.capturedPanel}><h3>촬영한 동작</h3><div className={styles.capturedMedia}>{selectedPreview && (selectedPreviewIsImage ? <img src={mediaUrl(selectedPreview.previewUrl)} alt="등록한 제스처" /> : <video src={mediaUrl(selectedPreview.previewUrl)} muted loop autoPlay playsInline />)}</div><span>{name}</span></div><div className={styles.completePanel}><div className={styles.completeIcon}>✓</div><h3>등록 완료!</h3><strong>{name}</strong><p>등록된 기능이 아래 순서대로 실행됩니다.</p><div className={styles.completeSteps}>{steps.map((step, index) => <span key={`${step.tool}-${index}`}>{displayTool(step)}</span>)}</div><button className={styles.primary} onClick={() => { onSaved(); close(); }}>확인</button></div></div>}
      {registration.error && !['rejected', 'form'].includes(registration.stage) && <p className={styles.error} role="alert">{registration.error}</p>}
    </div>
  </div>;
}

function CaptureTypeDialog({ onClose, onSelect }) {
  return <div className={styles.captureTypeBackdrop} role="presentation" onMouseDown={onClose}><div className={styles.captureTypeDialog} role="dialog" aria-modal="true" aria-labelledby="capture-type-title" onMouseDown={(event) => event.stopPropagation()}><h3 id="capture-type-title">촬영 방식 선택</h3><p>등록할 제스처의 촬영 방식을 선택해주세요.</p><div><article><span className={styles.captureTypeIcon}><CameraIcon /></span><strong>정적 제스처 등록</strong><p>사진으로 촬영합니다.<br />3초 카운트다운 후 3회 반복 촬영</p><button className={styles.primary} onClick={() => onSelect('STATIC')}>사진으로 등록</button></article><article><span className={styles.captureTypeIcon}><CameraIcon video /></span><strong>동적 제스처 등록</strong><p>영상으로 촬영합니다.<br />3초 카운트다운 후 2초간 3회 반복</p><button className={styles.primary} onClick={() => onSelect('DYNAMIC')}>영상으로 등록</button></article></div></div></div>;
}

function Review({ registration, onSelect, onRetry, onNext }) {
  const selected = registration.previews.find((take) => take.take === registration.selectedTake);
  const selectedIsImage = (selected?.mediaType || (registration.motion === 'STATIC' ? 'IMAGE' : 'VIDEO')) === 'IMAGE';
  return <>{selected && (selectedIsImage ? <img className={styles.reviewVideo} src={mediaUrl(selected.previewUrl)} alt="선택한 정적 제스처" /> : <video className={styles.reviewVideo} src={mediaUrl(selected.previewUrl)} controls autoPlay muted loop />)}<div className={styles.takeChoices}>{registration.previews.map((take) => <button className={registration.selectedTake === take.take ? styles.selectedTake : ''} onClick={() => onSelect(take.take)} key={take.take}>{take.mediaType === 'IMAGE' ? <img src={mediaUrl(take.previewUrl)} alt={`${take.take}회 촬영`} /> : <video src={mediaUrl(take.previewUrl)} muted preload="metadata" />}<span>{take.take}회</span></button>)}</div><p>이 동작으로 등록할까요?</p><small>세 번의 촬영 데이터는 모두 제스처 학습에 사용됩니다.</small><div className={styles.actions}><button onClick={onRetry}>다시 촬영</button><button className={styles.primary} disabled={!registration.captured || !registration.previews.length} onClick={onNext}>{registration.captured ? '다음' : '학습 처리 중'}</button></div></>;
}

function RegistrationRejected({ registration, onRetry }) {
  const items = useGestureStore((state) => state.items);
  const defaults = buildDefaultGestures(items);
  const hasSimilarGesture = Boolean(registration.similarTo);
  const similar = hasSimilarGesture
    ? [...defaults, ...items.filter((item) => item.custom)].find((item) => item.name === registration.similarTo || displayName(item) === registration.similarTo)
    : null;
  const currentPreview = registration.previews[0];
  return <section className={styles.rejectedResult}>
    <div className={styles.alertIcon}>!</div>
    <h3>{registration.error}</h3>
    {hasSimilarGesture && <p>둘을 구분하지 못해 잘못 실행될 수 있습니다.<br />손 모양이나 방향을 바꿔 다시 촬영해주세요.</p>}
    <div className={`${styles.similarityGrid} ${hasSimilarGesture ? '' : styles.singlePreview}`}>
      <article><div className={styles.compareMedia}>{registration.frame ? <img src={registration.frame} alt="지금 촬영한 제스처" /> : currentPreview?.previewUrl ? (currentPreview.mediaType === 'IMAGE' ? <img src={mediaUrl(currentPreview.previewUrl)} alt="지금 촬영한 제스처" /> : <video src={mediaUrl(currentPreview.previewUrl)} muted loop autoPlay playsInline />) : <span>촬영 화면</span>}</div><strong>지금 만든 제스처</strong></article>
      {hasSimilarGesture && <article>{similar ? <HoverPreview gesture={similar} comparison /> : <div className={styles.compareMedia}><span>비슷한 제스처</span></div>}<strong>{registration.similarTo}</strong>{registration.similarity != null && <small>유사도 {Math.round(registration.similarity * 100)}%</small>}</article>}
    </div>
    <button className={styles.primary} onClick={onRetry}>다시 촬영</button>
    {hasSimilarGesture && <small>혼동 가능한 제스처는 등록할 수 없습니다.</small>}
  </section>;
}
