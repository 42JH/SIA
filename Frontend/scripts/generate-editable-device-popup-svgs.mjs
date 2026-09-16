import fs from 'node:fs';
import path from 'node:path';

const OUT = path.resolve('design/device-change-popups-svg-editable');
fs.mkdirSync(OUT, { recursive: true });

const C = {
  bg: '#f6f9fc',
  white: '#ffffff',
  navy: '#082b4b',
  deep: '#041d35',
  blue: '#2e6191',
  cyan: '#43c8ef',
  line: '#b7cada',
  line2: '#d8e4ee',
  muted: '#6f88a1',
  dim: '#081a2d',
  selected: '#e7f1fa',
};

const esc = (value) => String(value)
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;');

function text(x, y, value, size = 18, weight = 500, fill = C.deep, anchor = 'start', extra = '') {
  return `<text x="${x}" y="${y}" font-family="Pretendard, Noto Sans KR, Malgun Gothic, sans-serif" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}" ${extra}>${esc(value)}</text>`;
}

function button(x, y, w, h, label, filled = true, id = 'button') {
  const fill = filled ? C.navy : C.white;
  const stroke = C.navy;
  const labelFill = filled ? C.white : C.navy;
  return `<g id="${id}">
    <path d="M${x} ${y}H${x + w - 10}L${x + w} ${y + 10}V${y + h}H${x + 10}L${x} ${y + h - 10}Z" fill="${fill}" stroke="${stroke}" stroke-width="1.5"/>
    ${text(x + w / 2, y + h / 2 + 7, label, 17, 700, labelFill, 'middle')}
  </g>`;
}

function micIcon(cx, cy, scale = 1) {
  return `<g id="microphone-icon" fill="none" stroke="${C.navy}" stroke-width="${4 * scale}" stroke-linecap="round" stroke-linejoin="round">
    <rect x="${cx - 12 * scale}" y="${cy - 28 * scale}" width="${24 * scale}" height="${45 * scale}" rx="${12 * scale}"/>
    <path d="M${cx - 25 * scale} ${cy + 2 * scale}C${cx - 25 * scale} ${cy + 27 * scale} ${cx + 25 * scale} ${cy + 27 * scale} ${cx + 25 * scale} ${cy + 2 * scale}"/>
    <path d="M${cx} ${cy + 27 * scale}V${cy + 43 * scale}M${cx - 15 * scale} ${cy + 43 * scale}H${cx + 15 * scale}"/>
    <path d="M${cx - 38 * scale} ${cy - 3 * scale}V${cy + 9 * scale}M${cx - 46 * scale} ${cy + 1 * scale}V${cy + 5 * scale}M${cx + 38 * scale} ${cy - 3 * scale}V${cy + 9 * scale}M${cx + 46 * scale} ${cy + 1 * scale}V${cy + 5 * scale}" stroke-width="${2.4 * scale}"/>
  </g>`;
}

function cameraIcon(cx, cy, scale = 1) {
  return `<g id="camera-icon" fill="none" stroke="${C.navy}" stroke-width="${4 * scale}" stroke-linejoin="round">
    <path d="M${cx - 31 * scale} ${cy - 18 * scale}H${cx - 14 * scale}L${cx - 7 * scale} ${cy - 28 * scale}H${cx + 8 * scale}L${cx + 15 * scale} ${cy - 18 * scale}H${cx + 31 * scale}V${cy + 24 * scale}H${cx - 31 * scale}Z"/>
    <circle cx="${cx}" cy="${cy + 2 * scale}" r="${14 * scale}"/>
  </g>`;
}

function iconRing(type, cx = 800, cy = 408) {
  const icon = type === 'camera' ? cameraIcon(cx, cy, 0.68) : micIcon(cx, cy, 0.68);
  return `<g id="status-icon-ring">
    <circle cx="${cx}" cy="${cy}" r="57" fill="none" stroke="${C.line2}" stroke-width="2"/>
    <circle cx="${cx}" cy="${cy}" r="47" fill="none" stroke="${C.line}" stroke-width="2" stroke-dasharray="92 22"/>
    <circle cx="${cx}" cy="${cy}" r="38" fill="none" stroke="${C.navy}" stroke-width="5" stroke-dasharray="70 170" transform="rotate(-88 ${cx} ${cy})"/>
    ${icon}
  </g>`;
}

function settingsBackground() {
  return `<g id="settings-page-background">
    <rect width="1600" height="1000" fill="${C.bg}"/>
    <g id="top-bar">
      <path d="M36 22H1545L1570 47V82H36Z" fill="${C.white}" stroke="${C.line2}" stroke-width="1.5"/>
      ${text(78, 63, 'SIA', 40, 900, C.navy, 'start', 'font-style="italic" letter-spacing="-4"')}
      <g id="hamburger" stroke="${C.navy}" stroke-width="3" stroke-linecap="round"><path d="M1514 43H1536M1514 51H1536M1514 59H1536"/></g>
      <path d="M1364 83H1510L1522 95H1568" fill="none" stroke="${C.blue}" stroke-width="1.3"/>
      <circle cx="1442" cy="83" r="3" fill="${C.blue}"/><circle cx="1454" cy="83" r="3" fill="${C.blue}"/><circle cx="1466" cy="83" r="3" fill="${C.blue}"/>
    </g>
    <g id="left-ai-panel">
      <path d="M34 91H397L421 115V581L410 592V937L388 960H34Z" fill="url(#navyGradient)" stroke="${C.blue}" stroke-width="1"/>
      <circle cx="226" cy="524" r="128" fill="none" stroke="#5ea4d0" stroke-width="1" opacity=".55"/>
      <circle cx="226" cy="524" r="102" fill="none" stroke="#83c5eb" stroke-width="4" stroke-dasharray="142 34 78 26"/>
      <circle cx="226" cy="524" r="76" fill="none" stroke="#4aa9da" stroke-width="1.4"/>
      <circle cx="226" cy="524" r="54" fill="url(#dotGrid)" stroke="#a3d9f3" stroke-width="1"/>
      <g id="ai-wave" fill="${C.cyan}" opacity=".92">
        ${Array.from({length: 45}, (_, i) => {
          const h = 8 + Math.abs(Math.sin(i * .63)) * 42 + (i > 16 && i < 29 ? 22 : 0);
          return `<rect x="${69 + i * 7}" y="${738 - h / 2}" width="2.5" height="${h}" rx="1.2"/>`;
        }).join('')}
      </g>
    </g>
    <g id="settings-content">
      <path d="M421 91H1536L1566 121V939L1544 961H421Z" fill="${C.white}" fill-opacity=".88" stroke="${C.line2}" stroke-width="1.5"/>
      ${text(489, 180, '설정', 48, 800)}
      <line x1="489" y1="241" x2="1518" y2="241" stroke="${C.line}"/>
      <rect x="489" y="276" width="5" height="25" fill="${C.navy}"/>
      ${text(508, 298, '호출명 (Wake Word)', 21, 700)}
      <rect x="489" y="324" width="499" height="55" fill="${C.white}" stroke="${C.line}"/>
      ${text(516, 359, '시아', 18, 500)}
      ${button(1006, 324, 169, 55, '저장', true, 'save-wake-word')}
      ${text(508, 403, '한국어 이름으로 입력해주세요.', 14, 400, C.muted)}
      <line x1="489" y1="440" x2="975" y2="440" stroke="${C.line2}"/>
      <line x1="1030" y1="440" x2="1518" y2="440" stroke="${C.line2}"/>
      <rect x="489" y="455" width="5" height="25" fill="${C.navy}"/><rect x="1030" y="455" width="5" height="25" fill="${C.navy}"/>
      ${text(508, 477, '마이크', 21, 700)}${text(1049, 477, '카메라', 21, 700)}
      <path d="M489 491H958L974 507V566H489Z" fill="${C.white}" stroke="${C.line}"/>
      <path d="M1030 491H1502L1518 507V566H1030Z" fill="${C.white}" stroke="${C.line}"/>
      ${text(516, 535, '시스템 설정 마이크 (기본)', 17, 600)}
      ${text(1057, 535, '내장 카메라 (기본)', 17, 600)}
      <path d="M793 518l7 7 7-7M1335 518l7 7 7-7" fill="none" stroke="${C.navy}" stroke-width="2"/>
      ${button(832, 497, 122, 51, '변경', false, 'change-mic')}
      ${button(1376, 497, 122, 51, '변경', false, 'change-camera')}
      <path d="M489 603H1493L1518 628V721L1494 745H489Z" fill="${C.white}" stroke="${C.line}"/>
      <rect x="489" y="632" width="5" height="25" fill="${C.navy}"/>
      ${text(508, 654, '동작', 21, 700)}${text(508, 685, '시선 커서 표시', 18, 700)}${text(508, 711, '화면에 현재 보고 있는 지점을 원으로 표시', 14, 400, C.muted)}
      <g id="gaze-cursor-toggle"><rect x="1424" y="666" width="64" height="34" rx="17" fill="${C.navy}"/><circle cx="1471" cy="683" r="14" fill="white"/></g>
      <path d="M489 749H1493L1518 774V866L1494 891H489Z" fill="${C.white}" stroke="${C.line}"/>
      <rect x="489" y="779" width="5" height="25" fill="${C.navy}"/>
      ${text(508, 801, '실행', 21, 700)}${text(508, 832, '컴퓨터 시작 시 자동 실행', 18, 700)}${text(508, 858, '컴퓨터 전원을 켜면 SIA가 자동으로 함께 실행됩니다.', 14, 400, C.muted)}
      <g id="autostart-toggle"><rect x="1424" y="814" width="64" height="34" rx="17" fill="${C.navy}"/><circle cx="1471" cy="831" r="14" fill="white"/></g>
    </g>
  </g>`;
}

function modalFrame(height = 388) {
  const x = 488;
  const w = 624;
  const y = Math.round((1000 - height) / 2);
  return { x, y, w, h: height, cx: 800, bottom: y + height,
    open: `<g id="popup-frame">
      <path d="M${x} ${y + 30}L${x + 30} ${y}H${x + w / 2 - 52}L${x + w / 2 - 38} ${y + 14}H${x + w / 2 + 38}L${x + w / 2 + 52} ${y}H${x + w - 24}L${x + w} ${y + 24}V${y + height - 25}L${x + w - 25} ${y + height}H${x + 25}L${x} ${y + height - 25}Z" fill="${C.white}" stroke="${C.navy}" stroke-width="2.2"/>
      <path d="M${x + 4} ${y + 30}L${x + 30} ${y + 4}M${x + 36} ${y + 8}l14 0M${x + 55} ${y + 8}l14 0M${x + 74} ${y + 8}l14 0" stroke="${C.navy}" stroke-width="5"/>
      <circle cx="${x + w - 53}" cy="${y + 20}" r="4" fill="${C.navy}"/><circle cx="${x + w - 39}" cy="${y + 20}" r="4" fill="${C.navy}"/><circle cx="${x + w - 25}" cy="${y + 20}" r="4" fill="${C.navy}"/>
      <path d="M${x + 22} ${y + height - 10}h14M${x + 42} ${y + height - 10}h14M${x + 62} ${y + height - 10}h14" stroke="${C.navy}" stroke-width="5"/>
      <path d="M${x + w - 86} ${y + height - 7}H${x + w - 24}L${x + w - 7} ${y + height - 24}" fill="none" stroke="${C.navy}" stroke-width="1.6"/><circle cx="${x + w - 88}" cy="${y + height - 7}" r="3.5" fill="${C.navy}"/>
    </g>` };
}

function dimOverlay() {
  return `<rect id="modal-dim-overlay" width="1600" height="1000" fill="${C.dim}" fill-opacity=".64"/>`;
}

function dropdownContent(type, f) {
  const isMic = type === 'mic';
  const title = isMic ? '마이크 변경' : '카메라 변경';
  const options = isMic
    ? ['시스템 설정 마이크 (기본)', 'USB 콘덴서 마이크', '웹캠 내장 마이크']
    : ['내장 카메라 (기본)', 'USB 웹캠', '외장 카메라'];
  const selected = options[1];
  const fieldX = f.cx - 170;
  const fieldY = f.y + 178;
  return `${iconRing(type === 'mic' ? 'mic' : 'camera', f.cx, f.y + 95)}
    ${text(f.cx, f.y + 158, title, 25, 800, C.deep, 'middle')}
    <g id="device-dropdown-open">
      <rect x="${fieldX}" y="${fieldY}" width="340" height="45" fill="white" stroke="${C.navy}" stroke-width="1.5"/>
      ${text(fieldX + 18, fieldY + 29, selected, 16, 700)}
      <path d="M${fieldX + 306} ${fieldY + 27}l8-8 8 8" fill="none" stroke="${C.navy}" stroke-width="2"/>
      <rect x="${fieldX}" y="${fieldY + 45}" width="340" height="112" fill="white" stroke="${C.line}" filter="url(#softShadow)"/>
      ${options.map((option, i) => {
        const oy = fieldY + 45 + i * 37;
        return `<g id="device-option-${i + 1}"><rect x="${fieldX + 3}" y="${oy + 2}" width="334" height="33" fill="${option === selected ? C.selected : C.white}"/><circle cx="${fieldX + 18}" cy="${oy + 18}" r="7" fill="white" stroke="${C.blue}"/><circle cx="${fieldX + 18}" cy="${oy + 18}" r="3.5" fill="${option === selected ? C.blue : 'none'}"/>${text(fieldX + 34, oy + 24, option, 14, option === selected ? 700 : 500)}</g>`;
      }).join('')}
    </g>
    ${button(f.cx - 170, f.bottom - 62, 158, 46, '취소', false, 'cancel-button')}
    ${button(f.cx + 12, f.bottom - 62, 158, 46, '변경', true, 'confirm-button')}`;
}

function autoContent(type, f) {
  const isMic = type === 'mic';
  return `${iconRing(type, f.cx, f.y + 105)}
    ${text(f.cx, f.y + 215, isMic ? '기존 음성 학습 데이터로 자동 전환했습니다' : '기존 시선 보정 데이터로 자동 전환했습니다', 22, 800, C.deep, 'middle')}
    ${text(f.cx, f.y + 250, isMic ? "'내 목소리 2' · 마지막 사용 2026.08.12" : "'내 시선 2' · 마지막 사용 2026.08.12", 17, 500, C.deep, 'middle')}
    ${button(f.cx - 92, f.bottom - 74, 184, 50, '확인', true, 'confirm-button')}`;
}

function dataRows(type, count, selected = 2, startY = 0) {
  const label = type === 'mic' ? '내 목소리' : '내 시선';
  const x = 557;
  const w = 486;
  return Array.from({ length: count }, (_, i) => {
    const y = startY + i * 62;
    const active = i + 1 === selected;
    return `<g id="saved-data-row-${i + 1}">
      <rect x="${x}" y="${y}" width="${w}" height="52" rx="3" fill="${active ? C.selected : C.white}" stroke="${active ? C.blue : C.line}"/>
      <circle cx="${x + 28}" cy="${y + 26}" r="11" fill="white" stroke="${C.blue}" stroke-width="1.5"/><circle cx="${x + 28}" cy="${y + 26}" r="5.5" fill="${active ? C.blue : 'none'}"/>
      ${text(x + 51, y + 23, `${label} ${i + 1}`, 15, 700)}
      ${text(x + 51, y + 42, `등록 2026.0${3 + i}.12 · 마지막 사용 2026.0${6 + i}.01`, 11, 400, C.muted)}
    </g>`;
  }).join('');
}

function selectContent(type, f) {
  const isMic = type === 'mic';
  return `${iconRing(type, f.cx, f.y + 74)}
    ${text(f.cx, f.y + 147, isMic ? '이 장치의 음성 학습 데이터가 2개 있습니다' : '이 장치의 시선 보정 데이터가 2개 있습니다', 20, 800, C.deep, 'middle')}
    ${text(f.cx, f.y + 174, '사용할 데이터를 선택해주세요.', 14, 500, C.muted, 'middle')}
    ${dataRows(type, 2, 2, f.y + 192)}
    ${button(f.cx - 246, f.bottom - 62, 226, 46, isMic ? '새로 음성 학습' : '새로 시선 보정', false, 'new-data-button')}
    ${button(f.cx + 20, f.bottom - 62, 226, 46, '선택한 데이터 사용', true, 'use-data-button')}`;
}

function emptyContent(type, f) {
  const isMic = type === 'mic';
  return `${iconRing(type, f.cx, f.y + 101)}
    ${text(f.cx, f.y + 212, isMic ? '이 장치의 음성 학습 데이터가 없습니다' : '이 장치의 시선 보정 데이터가 없습니다', 22, 800, C.deep, 'middle')}
    ${text(f.cx, f.y + 248, isMic ? '지금 음성 학습을 진행해야 사용할 수 있습니다. 약 1분 정도 걸립니다.' : '지금 시선 보정을 진행해야 사용할 수 있습니다. 약 1분 정도 걸립니다.', 14, 500, C.muted, 'middle')}
    ${button(f.cx - 220, f.bottom - 70, 200, 48, '나중에', false, 'later-button')}
    ${button(f.cx + 20, f.bottom - 70, 200, 48, '지금 시작', true, 'start-button')}`;
}

function limitContent(type, f) {
  const isMic = type === 'mic';
  return `${iconRing(type, f.cx, f.y + 70)}
    ${text(f.cx, f.y + 142, '저장 한도(3개)를 초과합니다', 21, 800, C.deep, 'middle')}
    ${text(f.cx, f.y + 170, isMic ? '새로운 음성 학습 데이터를 저장하려면 기존 데이터를 선택해 삭제해주세요.' : '새로운 시선 보정 데이터를 저장하려면 기존 데이터를 선택해 삭제해주세요.', 12, 500, C.muted, 'middle')}
    ${dataRows(type, 3, 1, f.y + 187)}
    ${button(f.cx - 220, f.bottom - 60, 200, 44, '취소', false, 'cancel-button')}
    ${button(f.cx + 20, f.bottom - 60, 200, 44, '선택 후 계속', true, 'continue-button')}`;
}

function defs() {
  return `<defs>
    <linearGradient id="navyGradient" x1="0" y1="0" x2="1" y2="1"><stop stop-color="${C.deep}"/><stop offset=".55" stop-color="${C.navy}"/><stop offset="1" stop-color="#0b365c"/></linearGradient>
    <pattern id="dotGrid" width="7" height="7" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.2" fill="#bce8f7"/></pattern>
    <filter id="softShadow" x="-20%" y="-20%" width="140%" height="160%"><feDropShadow dx="0" dy="8" stdDeviation="8" flood-color="#041d35" flood-opacity=".18"/></filter>
  </defs>`;
}

function buildSvg(screen) {
  const height = screen.kind === 'dropdown' ? 548 : screen.kind === 'select' ? 520 : screen.kind === 'limit' ? 566 : 388;
  const frame = modalFrame(height);
  let content = '';
  if (screen.kind === 'dropdown') content = dropdownContent(screen.type, frame);
  if (screen.kind === 'auto') content = autoContent(screen.type, frame);
  if (screen.kind === 'select') content = selectContent(screen.type, frame);
  if (screen.kind === 'empty') content = emptyContent(screen.type, frame);
  if (screen.kind === 'limit') content = limitContent(screen.type, frame);

  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000" role="img" aria-label="${esc(screen.title)}">
  <title>${esc(screen.title)}</title>
  ${defs()}
  ${settingsBackground()}
  ${dimOverlay()}
  ${frame.open}
  <g id="popup-content">${content}</g>
</svg>`;
}

const screens = [
  { file: '01-mic-device-dropdown.svg', title: '마이크 기기 선택 드롭다운', type: 'mic', kind: 'dropdown' },
  { file: '02-camera-device-dropdown.svg', title: '카메라 기기 선택 드롭다운', type: 'camera', kind: 'dropdown' },
  { file: '03-mic-auto-switch.svg', title: '마이크 음성 학습 데이터 자동 전환', type: 'mic', kind: 'auto' },
  { file: '04-mic-data-select.svg', title: '마이크 음성 학습 데이터 선택', type: 'mic', kind: 'select' },
  { file: '05-mic-no-data.svg', title: '마이크 음성 학습 데이터 없음', type: 'mic', kind: 'empty' },
  { file: '06-mic-storage-limit.svg', title: '마이크 음성 학습 데이터 저장 한도', type: 'mic', kind: 'limit' },
  { file: '07-camera-auto-switch.svg', title: '카메라 시선 보정 데이터 자동 전환', type: 'camera', kind: 'auto' },
  { file: '08-camera-data-select.svg', title: '카메라 시선 보정 데이터 선택', type: 'camera', kind: 'select' },
  { file: '09-camera-no-data.svg', title: '카메라 시선 보정 데이터 없음', type: 'camera', kind: 'empty' },
  { file: '10-camera-storage-limit.svg', title: '카메라 시선 보정 데이터 저장 한도', type: 'camera', kind: 'limit' },
];

for (const screen of screens) {
  fs.writeFileSync(path.join(OUT, screen.file), buildSvg(screen), 'utf8');
}

fs.writeFileSync(path.join(OUT, 'README.md'), `# SIA 기기 변경 팝업 — Figma 편집용 SVG

- 총 10개 화면, 1600×1000
- PNG 또는 base64 이미지 삽입 없음
- 배경, 프레임, 아이콘, 텍스트, 버튼, 드롭다운을 개별 SVG 요소로 구성
- Figma에서 SVG를 가져온 뒤 Ungroup하여 요소별 편집 가능
`, 'utf8');

console.log(`Generated ${screens.length} editable SVG files in ${OUT}`);
