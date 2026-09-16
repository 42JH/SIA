import fs from 'node:fs';
import path from 'node:path';

const outDir = path.resolve('design/SIA-gesture-wireframe-editable-svg');
fs.mkdirSync(outDir, { recursive: true });

const W = 1672;
const H = 941;
const C = {
  navy: '#082c59', deep: '#061d3d', deep2: '#0a376b', blue: '#176bd1',
  cyan: '#79c7ff', pale: '#d9e8f7', line: '#9bbce0', bg: '#f7fbff',
  white: '#ffffff', text: '#082756', muted: '#5684bd', disabled: '#c9d5e3',
  red: '#eb4d5c', green: '#2c8a77',
};
const LOGO_DATA = `data:image/png;base64,${fs.readFileSync(path.resolve('design/SIA-logo-original-cutout.png')).toString('base64')}`;
const esc = (value) => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
const t = (x, y, value, size = 22, weight = 500, fill = C.text, anchor = 'start', extra = '') =>
  `<text x="${x}" y="${y}" font-family="Pretendard, Noto Sans KR, Malgun Gothic, sans-serif" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}" ${extra}>${esc(value)}</text>`;
const caps = (x, y, value, size = 12, fill = C.muted, anchor = 'start') =>
  t(x, y, value, size, 700, fill, anchor, 'letter-spacing="4"');
const rect = (x, y, w, h, fill = 'none', stroke = 'none', sw = 0, rx = 0, extra = '') =>
  `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" ${extra}/>`;
const line = (x1, y1, x2, y2, stroke = C.line, sw = 1, extra = '') =>
  `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${sw}" ${extra}/>`;
const circle = (cx, cy, r, fill = 'none', stroke = 'none', sw = 0, extra = '') =>
  `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" ${extra}/>`;
const cut = (x, y, w, h, fill = C.white, stroke = C.blue, sw = 1.5, c = 18, extra = '') =>
  `<path d="M${x + c} ${y}H${x + w - c}L${x + w} ${y + c}V${y + h - c}L${x + w - c} ${y + h}H${x + c}L${x} ${y + h - c}V${y + c}Z" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" ${extra}/>`;
const button = (x, y, w, label, primary = true, disabled = false) =>
  `<g id="button-${esc(label)}">${cut(x, y, w, 58, disabled ? C.disabled : primary ? 'url(#navyButton)' : C.white, disabled ? C.disabled : C.navy, 1.5, 9)}${t(x + w / 2, y + 37, label, 20, 700, disabled ? C.white : primary ? C.white : C.text, 'middle')}</g>`;
const logo = (x = 42, y = 22, scale = .72) =>
  `<image id="sia-logo-original" x="${x}" y="${y}" width="${183.5 * scale}" height="${38.4 * scale}" href="${LOGO_DATA}" preserveAspectRatio="xMidYMid meet"/>`;
const hamburger = (x = W - 72, y = 38) =>
  `<g id="hamburger-button">${rect(x - 18, y - 20, 56, 56, C.white, C.blue, 1.5, 10)}${[-7, 3, 13].map((d) => line(x, y + d, x + 21, y + d, C.navy, 4, 'stroke-linecap="round"')).join('')}</g>`;
const tech = (x, y, w, h, dark = false) => {
  const ink = dark ? C.cyan : C.blue;
  const dot = dark ? C.white : C.navy;
  return `<g id="technical-decoration" fill="none" stroke="${ink}" stroke-width="2">
    <path d="M${x + 22} ${y + 1}H${x + 148}"/><path d="M${x + w - 150} ${y + h - 1}H${x + w - 24}"/>
    <path d="M${x + 1} ${y + 42}V${y + 82}M${x + w - 1} ${y + h - 82}V${y + h - 42}" opacity=".65"/>
    <path d="M${x + 30} ${y + h - 1}h38M${x + w - 92} ${y + 1}h50" opacity=".7"/>
    ${[0, 1, 2, 3].map((i) => circle(x + w - 64 + i * 12, y + 27, 3, dot, 'none', 0)).join('')}
    <g id="edge-stripes" stroke-width="3" opacity=".72">${[0, 1, 2, 3].map((i) => `<path d="M${x + 84 + i * 11} ${y + 2}l-9 9"/>`).join('')}${[0, 1, 2].map((i) => `<path d="M${x + w - 98 + i * 11} ${y + h - 2}l9-9"/>`).join('')}</g>
  </g>`;
};
const header = () => `<g id="global-header">${rect(0, 0, W, 82, C.white)}${line(0, 81, W, 81, C.line)}${logo()}${hamburger()}
  <g id="header-circuit" fill="none" stroke="${C.blue}" stroke-width="1.5" opacity=".75"><path d="M230 18H360L382 42H780L798 60H1175L1194 36H1460"/><path d="M1200 36h120"/>${[0, 1, 2].map((i) => circle(1060 + i * 14, 60, 3, C.navy)).join('')}</g></g>`;
const defs = `<defs>
  <linearGradient id="page" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#edf7ff"/></linearGradient>
  <linearGradient id="navyButton" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#061d3d"/><stop offset="1" stop-color="#0a376b"/></linearGradient>
  <linearGradient id="navyPanel" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#061d3d"/><stop offset=".55" stop-color="#0a376b"/><stop offset="1" stop-color="#082c59"/></linearGradient>
  <pattern id="grid" width="30" height="30" patternUnits="userSpaceOnUse"><rect width="30" height="30" fill="#061f40"/><path d="M30 0H0V30" fill="none" stroke="#1b527d" stroke-width="1" opacity=".45"/></pattern>
  <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="14" stdDeviation="18" flood-color="#061d3d" flood-opacity=".22"/></filter>
  </defs>`;
const wrap = (title, body, includeHeader = true) => `<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><title>${esc(title)}</title>${defs}${rect(0, 0, W, H, 'url(#page)')}${includeHeader ? header() : ''}${body}</svg>`;

const handSilhouette = (cx, cy, kind = 'wave', scale = 1, motion = false, tone = 'light') => {
  const palmFill = tone === 'dark' ? '#3e4349' : '#d6e3f1';
  const edge = tone === 'dark' ? '#f5f7fa' : '#ffffff';
  const joint = tone === 'dark' ? '#ffffff' : '#315f89';
  const cuff = tone === 'dark' ? '#33383e' : '#315f89';
  const inset = tone === 'dark' ? '#555b62' : C.deep2;
  const accent = tone === 'dark' ? '#3e4349' : C.blue;
  const common = `fill="${palmFill}" stroke="${edge}" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"`;
  const detail = `fill="none" stroke="${joint}" stroke-width="2.8" stroke-linecap="round"`;
  const wave = `<g id="open-palm-silhouette">
    <path d="M66 55Q48 55 33 48L13 35L-54 32Q-70 31-72 20Q-73 8-56 7L-15 8L-62-13Q-77-20-72-32Q-67-43-52-37L-4-17L-47-50Q-59-61-51-71Q-42-80-29-68L14-34L-15-72Q-24-85-13-92Q-1-98 8-82L39-38L49-66Q54-81 67-76Q79-71 74-55L62-17Q69-5 78 10L95 39Z" ${common}/>
    <path d="M-15 8Q5 13 27 24M-4-17Q19-10 38 7M14-34Q33-24 48-8M39-38Q51-27 61-14M24 38Q43 27 65 30" ${detail}/>
    <path d="M61 40L99 31L108 73L69 84Z" fill="${cuff}" stroke="${edge}" stroke-width="3.2"/>
  </g>`;
  const thumb = `<g id="thumb-up-silhouette">
    <path d="M-63 76V-4H-22L-7-31L4-86Q7-105 23-102Q38-99 35-79L30-42H75Q94-42 91-23L79 50Q75 76 49 81H-20Z" ${common}/>
    <path d="M-19-4h55M-17 17h83M-16 39h78M31-41q-10 18-8 38" ${detail}/>
    <path d="M-81-8H-46V91H-81Z" fill="${cuff}" stroke="${edge}" stroke-width="3.2"/>
  </g>`;
  const victory = `<g id="victory-hand-silhouette">
    <path d="M-55 86V6Q-55-10-42-10Q-30-10-29 5L-25 28L-17-79Q-16-96-2-96Q12-95 11-77L9-21L32-91Q38-108 52-103Q66-98 60-80L39-12L64-40Q76-53 88-43Q99-33 87-20L58 17Q72 38 61 62Q52 81 27 88L-27 93Z" ${common}/>
    <path d="M-28 29q42 18 80 1M8-21l-2 48M39-11l-15 42" ${detail}/>
    <path d="M-61 82H37L31 110H-56Z" fill="${cuff}" stroke="${edge}" stroke-width="3.2"/>
  </g>`;
  const heart = `<g id="finger-heart-silhouette">
    <path d="M-62 87V20Q-62 5-49 5Q-37 5-36 19L-32 38L-18-34Q-15-50-1-48Q12-45 9-29L2 8L28-29Q38-43 51-34Q63-25 52-11L25 23L66 8Q82 2 88 16Q94 30 78 37L35 57Q29 79 7 89L-34 94Z" ${common}/>
    <path d="M-31 39q29 15 58 6M2 8l-9 34M26 24L9 48" ${detail}/>
    <path d="M-68 83H24L19 111H-63Z" fill="${cuff}" stroke="${edge}" stroke-width="3.2"/>
    <path d="M0-73q16-23 32 0q16-23 32 0q0 18-32 39Q0-55 0-73Z" fill="${accent}" stroke="${edge}" stroke-width="3"/>
  </g>`;
  const fist = `<g id="fist-silhouette">
    <path d="M-61-22Q-61-43-40-43H49Q70-43 70-22V43Q70 72 42 82L-28 88Q-61 82-61 50Z" ${common}/>
    <rect x="-53" y="-63" width="29" height="48" rx="13" ${common}/><rect x="-25" y="-72" width="29" height="57" rx="13" ${common}/><rect x="3" y="-69" width="29" height="54" rx="13" ${common}/><rect x="31" y="-59" width="29" height="44" rx="13" ${common}/>
    <path d="M-48 5Q-14-18 22 4L50 27Q59 37 50 48Q41 57 31 49L7 31Q-13 45-43 34" fill="${inset}" stroke="${edge}" stroke-width="3.2"/>
    <path d="M-37-15v19M-9-15V3M19-15V4M45-14V7" ${detail}/>
    <path d="M-58 78H45L39 108H-53Z" fill="${cuff}" stroke="${edge}" stroke-width="3.2"/>
  </g>`;
  const artwork = ({ wave, thumb, victory, heart, fist })[kind] ?? wave;
  return `<g id="hand-${kind}" transform="translate(${cx} ${cy}) scale(${scale})">${artwork}${motion ? `<g id="motion-trail" fill="none" stroke="${C.white}" stroke-width="4" stroke-linecap="round"><path d="M-132-12Q-6 65 132-28"/><path d="M116-43l22 13-20 17"/><path d="M-119-38q39 16 62 12" opacity=".55"/><path d="M75-70q28 5 48 18" opacity=".55"/></g>` : ''}</g>`;
};
const hand = (cx, cy, motion = false, scale = 1) => handSilhouette(cx, cy, 'wave', scale, motion);
const miniHand = (cx, cy) => handSilhouette(cx, cy + 2, 'wave', .2, false);
const gestureHudBadge = (cx, cy) => `<g id="gesture-hud-badge">
  ${circle(cx, cy, 73, C.white, C.navy, 2.2)}${circle(cx, cy, 62, 'none', C.blue, 1.5)}${circle(cx, cy, 51, C.bg, C.line, 1.2)}${circle(cx, cy, 42, 'none', C.blue, 1, 'stroke-dasharray="3 5"')}
  <path d="M${cx - 67} ${cy - 28}A73 73 0 0 1 ${cx - 31} ${cy - 66}M${cx + 30} ${cy - 66}A73 73 0 0 1 ${cx + 66} ${cy - 30}M${cx + 67} ${cy + 28}A73 73 0 0 1 ${cx + 32} ${cy + 65}" fill="none" stroke="${C.navy}" stroke-width="5"/>
  ${Array.from({ length: 12 }, (_, i) => { const a = i * Math.PI / 6; const x1 = cx + Math.cos(a) * 77; const y1 = cy + Math.sin(a) * 77; const x2 = cx + Math.cos(a) * (i % 3 === 0 ? 88 : 83); const y2 = cy + Math.sin(a) * (i % 3 === 0 ? 88 : 83); return line(x1, y1, x2, y2, C.blue, i % 3 === 0 ? 2.4 : 1.2); }).join('')}
  ${line(cx - 94, cy, cx - 49, cy, C.navy, 1.5)}${line(cx + 49, cy, cx + 94, cy, C.navy, 1.5)}${line(cx, cy - 94, cx, cy - 50, C.navy, 1.5)}${line(cx, cy + 50, cx, cy + 94, C.navy, 1.5)}
  ${circle(cx - 62, cy, 4, C.blue)}${circle(cx + 62, cy, 4, C.blue)}${circle(cx, cy - 62, 4, C.navy)}${circle(cx + 38, cy + 47, 4, C.cyan)}
  ${handSilhouette(cx, cy + 15, 'wave', .25, false)}
</g>`;
const cameraCorners = (x, y, w, h) => {
  const inset = Math.max(14, Math.min(38, w * .12, h * .22));
  const arm = Math.max(18, Math.min(40, w * .13, h * .28));
  return `<g id="camera-corners" fill="none" stroke="${C.pale}" stroke-width="4"><path d="M${x + inset} ${y + inset + arm}V${y + inset}H${x + inset + arm}M${x + w - inset - arm} ${y + inset}H${x + w - inset}V${y + inset + arm}M${x + inset} ${y + h - inset - arm}V${y + h - inset}H${x + inset + arm}M${x + w - inset - arm} ${y + h - inset}H${x + w - inset}V${y + h - inset - arm}"/></g>`;
};
const cameraPanel = (x, y, w, h, mode = 'static', recognizing = false) => `<g id="camera-panel"><g id="captured-media-slot">${cut(x, y, w, h, 'url(#grid)', C.navy, 2, 18)}</g>${tech(x, y, w, h, true)}${cameraCorners(x, y, w, h)}
  ${recognizing ? `${circle(x + 36, y + 34, 8, C.red)}${t(x + 54, y + 41, 'REC 00:02', 17, 600, C.white)}` : ''}
  </g>`;
const titleBlock = (title, subtitle, centered = false) => `<g id="page-title">${t(centered ? W / 2 : 44, 146, title, 54, 800, C.text, centered ? 'middle' : 'start')}${t(centered ? W / 2 : 45, 187, subtitle, 24, 600, C.muted, centered ? 'middle' : 'start')}</g>`;
const toggle = (x, y, on = true) => `<g id="usage-toggle">${rect(x, y, 70, 36, on ? C.navy : C.disabled, 'none', 0, 18)}${circle(x + (on ? 51 : 19), y + 18, 14, C.white)}</g>`;
const statusIcon = (cx, cy, type = 'check') => `<g id="status-icon">${circle(cx, cy, 46, C.white, C.navy, 2)}${type === 'check' ? `<path d="M${cx - 20} ${cy}l14 15 29-34" fill="none" stroke="${C.navy}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>` : `<path d="M${cx} ${cy - 22}v29M${cx} ${cy + 22}v1" stroke="${C.navy}" stroke-width="6" stroke-linecap="round"/>`}</g>`;
const modalFrame = (x, y, w, h) => `<g id="modal-frame" filter="url(#shadow)">${cut(x, y, w, h, C.white, C.navy, 2.5, 22)}${tech(x, y, w, h)}<path d="M${x} ${y + 22}v90l16-16V${y + 22}Z" fill="${C.navy}"/><path d="M${x + w - 134} ${y}h86l18 18h-86Z" fill="${C.navy}"/></g>`;

const registeredGestureIcon = (cx, cy, kind, size = 132) => {
  const x = cx - size / 2;
  const y = cy - size / 2;
  const handScale = size / 390;
  return `<g id="registered-motion-photo-${kind}">
    ${rect(x, y, size, size, C.white, C.disabled, 1.4, 2, 'stroke-dasharray="7 5"')}
    ${handSilhouette(cx, cy - size * .08, kind, handScale, false, 'dark')}
    ${rect(x + 1, y + size - 33, size - 2, 32, C.white, 'none', 0, 0, 'opacity=".9"')}
    ${t(cx, y + size - 11, '등록된 동작 사진', Math.max(11, size * .09), 500, '#69727c', 'middle')}
  </g>`;
};

const listPage = () => wrap('SIA 제스처 목록', `${titleBlock('제스처', '손짓 하나로 SIA의 동작을 실행하고 관리합니다.')}
  ${gestureHudBadge(1450, 133)}
  ${t(44, 280, '기본 제스처', 27, 800)}${button(1390, 232, 236, '＋  새 제스처 등록')}
  ${gestureCard(44, 306, 500, 247, '손 흔들기', '일시정지', 'wave', true, true)}${gestureCard(568, 306, 500, 247, '엄지 척', '좋아요', 'thumb', true, true)}${gestureCard(1092, 306, 534, 247, 'V 사인', '사진 촬영', 'victory', false, true)}
  ${t(44, 592, '내 커스텀 제스처', 27, 800)}${gestureCard(44, 618, 500, 247, '손가락 하트', '음악 재생', 'heart', true, false)}${gestureCard(568, 618, 500, 247, '주먹 쥐기', '화면 캡처', 'fist', true, false)}
  ${cut(1092, 618, 534, 247, C.white, C.pale, 1.5, 16)}${tech(1092, 618, 534, 247)}${circle(1359, 725, 44, C.white, C.line, 2)}${t(1359, 739, '＋', 38, 400, C.muted, 'middle')}${t(1359, 802, '새 커스텀 제스처를 등록할 수 있습니다.', 17, 500, C.muted, 'middle')}`);

function gestureCard(x, y, w, h, name, action, kind, on, isDefault = false) {
  const px = x + 16, py = y + 16, pw = w * .55, ph = h - 32;
  const symbol = isDefault ? registeredGestureIcon(px + pw / 2, py + ph * .54, kind, 132) : '';
  const detailLink = `${line(x + w * .62, y + h * .80, x + w - 26, y + h * .80, C.pale)}${t(x + w * .62, y + h * .91, '상세 보기', 15, 700, C.muted)}${t(x + w - 30, y + h * .91, '›', 24, 500, C.muted, 'end')}`;
  return `<g id="gesture-card-${kind}">${cut(x, y, w, h, C.white, C.line, 1.5, 16)}${tech(x, y, w, h)}<g id="${isDefault ? 'default-gesture-artwork' : 'custom-capture-slot'}">${cut(px, py, pw, ph, 'url(#grid)', C.blue, 1.2, 12)}${cameraCorners(px, py, pw, ph)}${caps(px + 20, py + 27, isDefault ? 'REGISTERED MOTION' : 'CAPTURE', 10, C.white)}${symbol}</g>${toggle(x + w - 82, y + 20, on)}${t(x + w * .62, y + h * .50, name, 23, 800)}${t(x + w * .62, y + h * .67, action, 19, 600, C.blue)}${detailLink}</g>`;
}

const typeSelectPage = () => {
  const base = listPage().replace('</svg>', '');
  return `${base}<g id="dim-layer">${rect(0, 0, W, H, C.deep, 'none', 0, 0, 'opacity=".58"')}</g>
    ${modalFrame(414, 225, 844, 500)}${t(836, 293, '제스처 유형 선택', 34, 800, C.text, 'middle')}${t(836, 329, '등록할 제스처의 촬영 방식을 선택해주세요.', 19, 500, C.muted, 'middle')}
    <g id="static-choice">${cut(454, 365, 365, 252, C.white, C.line, 1.5, 16)}${circle(636, 447, 55, C.bg, C.blue, 2)}${hand(636, 474, false, .28)}${t(636, 540, '정적 제스처', 27, 800, C.text, 'middle')}${t(636, 575, '한 가지 손 모양을 사진으로 등록합니다.', 16, 500, C.muted, 'middle')}${button(500, 632, 272, '정적 제스처 선택')}</g>
    <g id="dynamic-choice">${cut(853, 365, 365, 252, C.white, C.line, 1.5, 16)}${circle(1036, 447, 55, C.bg, C.blue, 2)}${hand(1036, 474, true, .28)}${t(1036, 540, '동적 제스처', 27, 800, C.text, 'middle')}${t(1036, 575, '움직임을 짧은 영상으로 등록합니다.', 16, 500, C.muted, 'middle')}${button(900, 632, 272, '동적 제스처 선택')}</g>
    ${circle(1217, 303, 18, C.white, C.line, 1.2)}${t(1217, 312, '×', 27, 400, C.text, 'middle')}</svg>`;
};

const detailBody = (edit = false) => `${t(44, 147, '‹', 50, 400)}${t(88, 145, edit ? '제스처 수정' : '제스처 상세', 38, 800)}
  <g id="gesture-preview-panel">${cut(44, 188, edit ? 700 : 920, 690, 'url(#navyPanel)', C.navy, 2, 20)}${tech(44, 188, edit ? 700 : 920, 690, true)}${edit ? t(82, 248, '촬영된 동작', 28, 800, C.white) : caps(82, 248, 'GESTURE PREVIEW', 15, C.white)}${cameraPanel(88, 270, edit ? 612 : 832, edit ? 498 : 520, 'static', false)}${caps(edit ? 82 : 88, 842, edit ? 'AI RECOGNITION READY' : 'SIA AI VISION', 12, C.pale)}</g>
  <g id="gesture-info-panel">${cut(edit ? 770 : 990, 188, edit ? 856 : 636, 690, C.white, C.line, 1.5, 18)}${tech(edit ? 770 : 990, 188, edit ? 856 : 636, 690)}
  ${edit ? editForm() : detailInfo()}</g>`;
const detailInfo = () => `${caps(1026, 239, 'GESTURE NAME', 13)}${t(1026, 294, '손가락 하트', 34, 800)}${line(1026, 322, 1588, 322, C.pale)}
  ${caps(1026, 380, 'GESTURE TYPE', 13)}${t(1026, 417, '커스텀 제스처', 22, 700)}${caps(1026, 480, 'LINKED ACTION', 13)}${t(1026, 526, '♪  음악 재생', 25, 700)}${caps(1026, 590, 'REGISTRATION DATE', 13)}${t(1026, 630, '등록일  2026.03.12', 21, 600)}${line(1026, 674, 1588, 674, C.pale)}
  ${cut(1018, 706, 578, 92, C.bg, C.pale, 1.2, 14)}${t(1044, 746, 'U S A G E', 12, 700, C.muted)}${t(1044, 778, '사용 켜기', 20, 700)}${toggle(1500, 735, true)}${button(1235, 810, 170, '수정', false)}${button(1420, 810, 176, '삭제', true)}`;
const editForm = () => `${caps(814, 238, 'GESTURE INFO', 13)}${t(814, 298, '제스처 이름', 23, 800)}${rect(814, 322, 766, 62, C.white, C.line, 1.5, 10)}${t(838, 362, '손가락 하트', 22, 500)}${t(814, 452, '이 제스처로 실행할 기능', 21, 700, C.muted)}${actionRow(814, 480, 766, '1', '음악 앱 실행')}${actionRow(814, 566, 766, '2', '재생목록 ‘집중’ 재생')}${cut(814, 652, 766, 76, C.white, C.line, 1.2, 12, 'stroke-dasharray="6 5"')}${t(844, 700, '＋  기능 추가하기', 21, 600, C.muted)}${button(1245, 790, 160, '취소', false)}${button(1420, 790, 160, '저장', true)}`;
const actionRow = (x, y, w, number, label) => `${rect(x, y, w, 68, C.white, C.pale, 1.2, 10)}${t(x + 24, y + 43, '⠿', 24, 600, C.muted)}${t(x + 72, y + 43, number, 21, 700)}${t(x + 125, y + 43, label, 21, 600)}${circle(x + w - 38, y + 34, 18, C.white, C.line, 1.3)}${t(x + w - 38, y + 42, '×', 24, 400, C.muted, 'middle')}`;
const detailPage = () => wrap('SIA 제스처 상세', detailBody(false));
const editPage = () => wrap('SIA 제스처 수정', detailBody(true));

const defaultGesturePreview = (x, y, w, h, kind = 'wave') => `<g id="default-gesture-preview">${cut(x, y, w, h, 'url(#grid)', C.blue, 1.5, 16)}${cameraCorners(x, y, w, h)}${caps(x + 24, y + 36, 'DEFAULT GESTURE', 12, C.white)}${registeredGestureIcon(x + w / 2, y + h * .53, kind, Math.min(280, h * .58))}</g>`;
const basicGestureDetailBody = (edit = false) => `${t(44, 147, '‹', 50, 400)}${t(88, 145, edit ? '기본 제스처 기능 수정' : '기본 제스처 상세', 38, 800)}
  <g id="basic-gesture-preview-panel">${cut(44, 188, edit ? 700 : 920, 690, 'url(#navyPanel)', C.navy, 2, 20)}${tech(44, 188, edit ? 700 : 920, 690, true)}${t(82, 248, '기본 제스처', 28, 800, C.white)}${defaultGesturePreview(88, 270, edit ? 612 : 832, 520, 'wave')}${caps(88, 842, 'SIA DEFAULT GESTURE', 12, C.pale)}</g>
  <g id="basic-gesture-info-panel">${cut(edit ? 770 : 990, 188, edit ? 856 : 636, 690, C.white, C.line, 1.5, 18)}${tech(edit ? 770 : 990, 188, edit ? 856 : 636, 690)}${edit ? basicGestureEditForm() : basicGestureInfo()}</g>`;
const basicGestureInfo = () => `${caps(1026, 239, 'GESTURE NAME', 13)}${t(1026, 294, '손 흔들기', 34, 800)}${line(1026, 322, 1588, 322, C.pale)}${caps(1026, 380, 'GESTURE TYPE', 13)}${t(1026, 417, '기본 제공 제스처', 22, 700)}${caps(1026, 480, 'LINKED ACTION', 13)}${t(1026, 526, '일시정지', 25, 700)}${t(1026, 566, '기본 제스처의 이름과 동작은 변경할 수 없습니다.', 16, 500, C.muted)}${line(1026, 674, 1588, 674, C.pale)}${cut(1018, 706, 578, 92, C.bg, C.pale, 1.2, 14)}${t(1044, 746, '사용 여부', 16, 700, C.muted)}${t(1044, 778, '기능 켜기', 20, 700)}${toggle(1500, 735, true)}${button(1360, 810, 236, '기능 수정', true)}`;
const basicGestureEditForm = () => `${caps(814, 238, 'DEFAULT GESTURE', 13)}${t(814, 298, '제스처 이름', 23, 800)}${rect(814, 322, 766, 62, C.bg, C.pale, 1.5, 10)}${t(838, 362, '손 흔들기', 22, 600, C.muted)}${t(814, 412, '기본 제스처의 이름과 동작은 고정됩니다.', 16, 500, C.muted)}${t(814, 474, '이 제스처로 실행할 기능', 21, 700, C.muted)}${actionRow(814, 500, 766, '1', '일시정지')}${cut(814, 586, 766, 76, C.white, C.line, 1.2, 12, 'stroke-dasharray="6 5"')}${t(844, 634, '＋ 기능 추가하기', 21, 600, C.muted)}${t(814, 706, '기능의 순서와 실행 항목만 수정할 수 있습니다.', 16, 500, C.muted)}${button(1245, 790, 160, '취소', false)}${button(1420, 790, 160, '저장', true)}`;
const basicGestureDetailPage = () => wrap('SIA 기본 제스처 상세', basicGestureDetailBody(false));
const basicGestureEditPage = () => wrap('SIA 기본 제스처 기능 수정', basicGestureDetailBody(true));
const deleteConfirmPage = () => `${detailPage().replace('</svg>', '')}<g id="dim-layer">${rect(0, 0, W, H, C.deep, 'none', 0, 0, 'opacity=".58"')}</g>${modalFrame(520, 284, 632, 370)}${statusIcon(836, 370, 'alert')}${t(836, 452, '제스처 삭제', 31, 800, C.text, 'middle')}${t(836, 500, '‘손가락 하트’ 제스처를 삭제하시겠습니까?', 19, 500, C.muted, 'middle')}${button(582, 548, 230, '취소', false)}${button(836, 548, 250, '삭제', true)}</svg>`;

const captureTitle = (mode, recognizing = false) => `${mode === 'static' ? '정적' : '동적'} 제스처 촬영`;
const captureSubtitle = (mode, recognizing = false) => recognizing ? (mode === 'static' ? '손 모양을 인식하고 있습니다.' : '동작을 인식하고 있습니다.') : (mode === 'static' ? '한 가지 손 모양을 사진으로 등록합니다.' : '움직임을 짧은 영상으로 등록합니다.');
const takeTile = (x, y, index, state) => `<g id="take-${index}-${state}">${rect(x, y, 225, 106, state === 'active' ? C.bg : C.white, state === 'active' ? C.blue : C.pale, state === 'active' ? 2 : 1.2, 10)}${circle(x + 34, y + 28, 16, state === 'done' ? C.blue : C.white, state === 'active' ? C.navy : C.line, 2)}${state === 'done' ? `<path d="M${x + 26} ${y + 28}l6 7 11-14" fill="none" stroke="${C.white}" stroke-width="3"/>` : state === 'active' ? circle(x + 34, y + 28, 7, C.navy) : `<path d="M${x + 34} ${y + 18}v10l7 5" fill="none" stroke="${C.line}" stroke-width="3"/>`}${miniHand(x + 112, y + 47)}${t(x + 112, y + 93, `${index}회 ${state === 'done' ? '완료' : state === 'active' ? '촬영 준비' : '대기'}`, 18, 700, state === 'waiting' ? '#8196b0' : C.text, 'middle')}</g>`;
const capturePage = (mode, step = 0, recognizing = false) => {
  const title = captureTitle(mode, recognizing);
  const panelX = 366, panelY = 218, panelW = 940, panelH = recognizing ? 332 : 338;
  const states = [1, 2, 3].map((n) => n < step ? 'done' : n === step ? 'active' : 'waiting');
  const guide = step === 0;
  const tileY = 650;
  return wrap(`SIA ${title}`, `${titleBlock(title, captureSubtitle(mode, recognizing), true)}${cameraPanel(panelX, panelY, panelW, panelH, mode, recognizing)}
    ${t(W / 2, panelY + panelH + 48, mode === 'static' ? '손 전체가 가이드 안에 들어오도록 위치해주세요.' : '동작의 시작과 끝이 자연스럽게 이어지도록 보여주세요.', 22, 700, C.text, 'middle')}${t(W / 2, panelY + panelH + 82, mode === 'static' ? '3초 카운트다운 후 촬영됩니다.' : '최대 3초 동안 촬영됩니다.', 17, 500, C.muted, 'middle')}
    ${guide ? '' : `${takeTile(478, tileY, 1, states[0])}${takeTile(724, tileY, 2, states[1])}${takeTile(970, tileY, 3, states[2])}`}
    ${recognizing ? button(656, 810, 360, '촬영 취소', false) : `${button(656, guide ? 720 : 770, 360, mode === 'static' ? '사진으로 촬영' : '영상 촬영 시작', true)}${button(656, guide ? 790 : 840, 360, '취소', false)}`}`);
};

const cameraUnavailablePage = () => wrap('SIA 카메라 사용 불가', `${titleBlock('제스처 촬영', '카메라 연결 상태를 확인해주세요.')}${cut(184, 220, 1304, 610, C.white, C.line, 1.5, 22)}${tech(184, 220, 1304, 610)}${statusIcon(836, 382, 'alert')}${t(836, 480, '카메라를 사용할 수 없어요', 38, 800, C.text, 'middle')}${t(836, 528, '카메라 연결 또는 권한 설정을 확인해주세요.', 21, 500, C.muted, 'middle')}${t(836, 561, '권한을 허용한 뒤 다시 시도할 수 있습니다.', 21, 500, C.muted, 'middle')}${button(558, 640, 260, '시스템 설정 열기', false)}${button(836, 640, 278, '다시 확인', true)}`);

const captureResultPage = () => wrap('SIA 제스처 촬영 결과', `${titleBlock('촬영 결과', '세 번의 촬영 결과를 확인해주세요.', true)}${cameraPanel(410, 214, 852, 300, 'dynamic', true)}${statusIcon(610, 574, 'check')}${t(666, 568, '동작이 선명하게 인식됐어요', 32, 800)}${t(666, 607, '세 번의 촬영에서 손 모양과 움직임이 안정적으로 감지되었습니다.', 17, 500, C.muted)}${[0, 1, 2].map((i) => `${cut(590 + i * 180, 638, 156, 96, 'url(#grid)', C.line, 1.2, 10)}${cameraCorners(590 + i * 180, 638, 156, 96)}${t(668 + i * 180, 760, `${i + 1}회`, 16, 700, C.text, 'middle')}`).join('')}${t(W / 2, 798, '이 동작으로 등록할까요?', 18, 500, C.muted, 'middle')}${button(618, 822, 200, '다시 촬영', false)}${button(836, 822, 218, '다음', true)}`);

const similarWarningPage = () => wrap('SIA 유사 제스처 경고', `${titleBlock('제스처 등록', '새로운 제스처를 학습시켜 더 편리한 일상을 만들어갑니다.')}${statusIcon(836, 254, 'alert')}${t(836, 336, '이미 등록된 제스처와 너무 비슷해요', 34, 800, C.text, 'middle')}${t(836, 378, '둘을 구분하지 못해 잘못 실행될 수 있습니다.', 19, 500, C.muted, 'middle')}${t(836, 410, '손 모양이나 방향을 바꿔 다시 촬영해주세요.', 19, 500, C.muted, 'middle')}${comparisonCard(250, 452, 'N E W   G E S T U R E', '지금 만든 제스처', false)}${comparisonCard(856, 452, 'E X I S T I N G   G E S T U R E', '주먹 쥐기', true)}${button(666, 820, 340, '다시 촬영', true)}`);
const comparisonCard = (x, y, kicker, label, similarity) => `<g id="comparison-${similarity ? 'existing' : 'new'}">${cut(x, y, 566, 320, C.white, C.line, 1.3, 15)}${caps(x + 24, y + 34, kicker, 12)}${t(x + 24, y + 72, label, 26, 800)}${similarity ? `${rect(x + 400, y + 24, 140, 45, C.bg, C.pale, 1, 22)}${t(x + 470, y + 53, '유사도 87%', 18, 700, C.text, 'middle')}` : ''}${cameraPanel(x + 24, y + 92, 518, 204, 'dynamic', true)}</g>`;

const registerShell = (variant = 'base') => `${titleBlock('제스처 등록', '나만의 제스처로 더 편리한 일상을 만들어보세요.')}${registerPreview()}${registerForm(variant)}`;
const registerPreview = () => `<g id="captured-gesture">${cut(44, 208, 650, 650, 'url(#navyPanel)', C.navy, 2, 20)}${tech(44, 208, 650, 650, true)}${t(78, 265, '촬영한 동작', 26, 800, C.white)}${caps(580, 265, 'SIA CAM', 12, C.white, 'end')}${cameraPanel(78, 286, 582, 480, 'dynamic', false)}${rect(286, 788, 166, 42, 'none', C.cyan, 1.2, 21)}${t(369, 816, '손가락 하트', 17, 600, C.white, 'middle')}</g>`;
const registerForm = (variant) => {
  const empty = variant === 'incomplete';
  const rows = variant === 'fileAssigned'
    ? [actionRow(756, 386, 758, '1', '파일 열기 / 실행'), actionRow(756, 466, 758, '2', '회의록.txt 실행')]
    : empty ? [] : [actionRow(756, 386, 758, '1', '음악 앱 실행'), actionRow(756, 466, 758, '2', '재생목록 ‘집중’ 재생'), ...(variant === 'base' ? [actionRow(756, 546, 758, '3', '볼륨 40%로 설정')] : [])];
  const addY = empty ? 454 : variant === 'base' ? 626 : 546;
  return `<g id="registration-form">${cut(712, 208, 914, 650, C.white, C.line, 1.5, 20)}${tech(712, 208, 914, 650)}${t(756, 256, '제스처 이름', 19, 700)}${rect(756, 272, 826, 56, C.white, empty ? C.red : C.line, 1.5, 8)}${t(778, 307, empty ? '예: 손가락 하트' : '손가락 하트', 20, 500, empty ? '#9aaec5' : C.text)}${empty ? t(756, 355, '이름을 입력해주세요', 16, 600, C.red) : ''}${t(756, empty ? 430 : 365, '이 제스처로 실행할 기능', 19, 700)}${rows.join('')}${cut(756, addY, 758, 72, C.white, C.line, 1.2, 10, 'stroke-dasharray="6 5"')}${t(782, addY + 45, '＋  기능 추가하기', 20, 600, C.muted)}${empty ? t(756, 552, '기능을 하나 이상 추가해주세요', 16, 500, C.muted) : ''}${button(1320, 774, 110, '취소', false)}${button(1444, 774, 138, '다음', true, empty)}${variant === 'dropdown' ? functionDropdown() : ''}</g>`;
};
const functionDropdown = () => `<g id="function-dropdown" filter="url(#shadow)">${rect(756, 618, 758, 176, C.white, C.line, 1.2, 10)}${t(780, 650, '미디어', 14, 700, C.muted)}${t(782, 686, '▶  파일 열기 / 실행', 18, 600)}${t(1080, 686, '◖  볼륨 올리기 / 내리기', 18, 600)}${line(778, 708, 1492, 708, C.pale)}${t(780, 737, '시스템', 14, 700, C.muted)}${t(782, 772, '▦  앱 실행', 18, 600)}${t(1080, 772, '▣  창 전환', 18, 600)}</g>`;
const registerPage = (variant) => wrap(`SIA 제스처 등록 ${variant}`, registerShell(variant));
const filePickerPage = () => `${registerPage('dropdown').replace('</svg>', '')}<g id="dim-layer">${rect(0, 0, W, H, C.deep, 'none', 0, 0, 'opacity=".50"')}</g>${modalFrame(380, 220, 912, 520)}${t(416, 270, '파일 선택', 26, 800)}${line(380, 292, 1292, 292, C.pale)}${rect(408, 318, 250, 340, C.bg, C.pale, 1, 8)}${t(438, 370, '☆  바로 가기', 19, 600)}${t(438, 420, '▣  바탕화면', 19, 600)}${rect(420, 446, 220, 48, C.pale, 'none', 0, 7)}${t(438, 478, '▤  문서', 19, 700)}${t(438, 532, '↓  다운로드', 19, 600)}${rect(682, 318, 580, 48, C.bg, C.pale, 1, 6)}${t(704, 350, '이름', 17, 700)}${['2026 상반기 결산.pdf', '회의록.txt', '참고자료.xlsx', '메모.docx'].map((v, i) => `${rect(682, 378 + i * 52, 580, 46, i === 1 ? C.pale : C.white, 'none', 0, 5)}${t(708, 409 + i * 52, `□   ${v}`, 17, i === 1 ? 700 : 500)}`).join('')}${t(416, 700, '파일 이름', 17, 600)}${rect(520, 669, 460, 48, C.white, C.line, 1.2, 7)}${t(540, 700, '회의록.txt', 17, 500)}${button(1000, 660, 120, '취소', false)}${button(1138, 660, 124, '열기', true)}</svg>`;
const completePage = () => wrap('SIA 제스처 등록 완료', `${titleBlock('제스처 등록', '새로운 제스처 등록이 완료되었습니다.')}${cut(268, 220, 1136, 590, C.white, C.line, 1.5, 24)}${tech(268, 220, 1136, 590)}${statusIcon(836, 390, 'check')}${t(836, 494, '등록 완료!', 42, 800, C.text, 'middle')}${t(836, 548, '‘손가락 하트’ 제스처를 사용해 연결된 기능을', 21, 500, C.muted, 'middle')}${t(836, 580, '실행할 수 있습니다.', 21, 500, C.muted, 'middle')}${button(692, 652, 288, '확인', true)}`);

const nativeFilePickerPage = () => `${registerPage('dropdown').replace('</svg>', '')}<g id="os-dim-layer">${rect(0, 0, W, H, '#17202b', 'none', 0, 0, 'opacity=".42"')}</g>
  <g id="windows-native-file-picker" filter="url(#shadow)">${rect(304, 150, 1064, 640, '#ffffff', '#9aa6b2', 1.2, 12)}${rect(304, 150, 1064, 54, '#f5f6f8', 'none', 0, 12)}${t(330, 185, '열기', 18, 600, '#202124')}${t(1328, 185, '×', 24, 400, '#30343b', 'middle')}${line(304, 204, 1368, 204, '#d9dde3')}
  ${rect(330, 224, 1012, 44, '#ffffff', '#b8c0ca', 1, 6)}${t(348, 253, '‹   ›   ↑     내 PC  ›  문서', 16, 500, '#3d4652')}${rect(330, 286, 210, 390, '#f7f8fa', '#e1e5ea', 1, 5)}${t(354, 330, '바로 가기', 16, 600, '#30343b')}${t(354, 374, '바탕 화면', 16, 500, '#30343b')}${rect(342, 394, 186, 40, '#e8f1fb', 'none', 0, 4)}${t(354, 421, '문서', 16, 600, '#1f5f9d')}${t(354, 466, '다운로드', 16, 500, '#30343b')}${t(354, 510, '사진', 16, 500, '#30343b')}
  ${rect(562, 286, 780, 44, '#f4f5f7', '#e1e5ea', 1, 4)}${t(584, 315, '이름', 15, 600, '#30343b')}${t(1198, 315, '수정한 날짜', 15, 600, '#30343b')}${['2026 상반기 결산.pdf', '회의록.txt', '참고자료.xlsx', '메모.docx'].map((v, i) => `${rect(562, 340 + i * 50, 780, 46, i === 1 ? '#dcecff' : '#ffffff', 'none', 0, 3)}${t(584, 370 + i * 50, `□  ${v}`, 16, i === 1 ? 600 : 500, '#30343b')}${t(1212, 370 + i * 50, `2026-09-${12 - i}`, 14, 400, '#5f6874')}`).join('')}
  ${t(330, 724, '파일 이름:', 15, 500, '#30343b')}${rect(426, 695, 650, 42, '#ffffff', '#9da7b3', 1, 5)}${t(444, 723, '회의록.txt', 16, 500, '#30343b')}${rect(1092, 695, 112, 42, '#ffffff', '#7d8793', 1, 5)}${t(1148, 722, '취소', 16, 500, '#30343b', 'middle')}${rect(1218, 695, 124, 42, '#176bd1', '#176bd1', 1, 5)}${t(1280, 722, '열기', 16, 600, '#ffffff', 'middle')}</g></svg>`;

const fullPageCompletePage = () => wrap('42 제스처 등록 완료', `${titleBlock('제스처 등록', '새로운 제스처 등록이 완료되었습니다.')}${registerPreview()}
  <g id="registration-complete-panel">${cut(712, 208, 914, 650, C.white, C.line, 1.5, 20)}${tech(712, 208, 914, 650)}${statusIcon(1169, 354, 'check')}${t(1169, 452, '등록 완료!', 42, 800, C.text, 'middle')}${t(1169, 505, '손가락 하트', 27, 800, C.text, 'middle')}${t(1169, 544, '등록된 기능이 아래 순서대로 실행됩니다.', 18, 500, C.muted, 'middle')}${cut(856, 580, 626, 96, C.bg, C.pale, 1.2, 12)}${t(1169, 619, '음악 앱 실행  →  재생목록 ‘집중’ 재생', 18, 700, C.text, 'middle')}${t(1169, 650, '→  볼륨 40%로 설정', 18, 700, C.text, 'middle')}${button(1024, 730, 290, '확인', true)}</g>`);

const flowHeading = (label) => `<g id="flow-heading">${t(44, 145, '‹', 50, 400)}${t(88, 141, label, 38, 800)}${line(44, 170, 1628, 170, C.pale, 1.2)}</g>`;

const gestureListRow = (x, y, name, action, kind, enabled, isDefault) => `<g id="gesture-row-${kind}">${rect(x, y, 694, 72, C.white, C.line, 1.2, 9)}
  <g id="${isDefault ? 'default-gesture-icon' : 'custom-capture-thumbnail'}">${isDefault ? `${circle(x + 45, y + 36, 27, C.bg, C.navy, 1.5)}${handSilhouette(x + 45, y + 40, kind, .17, false)}` : `${cut(x + 16, y + 13, 58, 46, 'url(#grid)', C.blue, 1, 6)}${cameraCorners(x + 16, y + 13, 58, 46)}`}</g>
  ${t(x + 92, y + 31, name, 20, 800)}${t(x + 92, y + 55, `${isDefault ? '기본 제스처' : '커스텀'}  |  ${action}`, 14, 600, C.muted)}${toggle(x + 554, y + 18, enabled)}${t(x + 664, y + 45, '›', 27, 500, C.muted, 'middle')}</g>`;

const wireListPage = () => wrap('37 제스처 목록', `${flowHeading('제스처')}
  ${t(56, 220, '기본 제스처', 27, 800)}${button(1380, 181, 246, '＋ 새 제스처 등록')}
  ${gestureCard(56, 244, 500, 247, '손 흔들기', '일시정지', 'wave', true, true)}
  ${gestureCard(586, 244, 500, 247, '엄지 척', '좋아요', 'thumb', true, true)}
  ${gestureCard(1116, 244, 510, 247, 'V 사인', '사진 촬영', 'victory', false, true)}
  ${t(56, 570, '내 커스텀 제스처', 27, 800)}
  ${gestureCard(56, 594, 500, 247, '손가락 하트', '음악 재생', 'heart', true, false)}
  ${gestureCard(586, 594, 500, 247, '주먹 쥐기', '화면 캡처', 'fist', true, false)}
  ${cut(1116, 594, 510, 247, C.white, C.pale, 1.5, 16)}${tech(1116, 594, 510, 247)}${circle(1371, 696, 44, C.white, C.line, 2)}${t(1371, 710, '＋', 38, 400, C.muted, 'middle')}${t(1371, 770, '새 커스텀 제스처를 등록할 수 있습니다.', 17, 500, C.muted, 'middle')}`);

const wireCaptureWaitingPage = () => wrap('38 제스처 촬영 대기', `${flowHeading('제스처 촬영')}${cameraPanel(366, 202, 940, 410, 'static', false)}
  ${t(836, 661, '등록하고 싶은 제스처를 취한 뒤 촬영 버튼을 눌러주세요.', 22, 700, C.text, 'middle')}
  ${button(686, 700, 300, '촬영하기', true)}${t(836, 792, '3초 카운트다운 후 2초간 3회 반복 촬영합니다.', 17, 500, C.muted, 'middle')}`);

const wireCameraErrorPage = () => `${wireListPage().replace('</svg>', '')}<g id="dim-layer">${rect(0, 0, W, H, C.deep, 'none', 0, 0, 'opacity=".58"')}</g>
  ${modalFrame(430, 230, 812, 480)}${statusIcon(836, 342, 'alert')}${t(836, 428, '카메라를 사용할 수 없어요', 34, 800, C.text, 'middle')}${t(836, 478, '연결된 외부 카메라와 권한 설정을 확인해주세요.', 19, 500, C.muted, 'middle')}${t(836, 510, '권한을 허용한 뒤 다시 시도할 수 있습니다.', 19, 500, C.muted, 'middle')}${button(548, 592, 270, '시스템 설정 열기', false)}${button(842, 592, 282, '다시 확인', true)}</svg>`;

const wireTypeSelectPage = () => `${wireCaptureWaitingPage().replace('</svg>', '')}<g id="dim-layer">${rect(0, 0, W, H, C.deep, 'none', 0, 0, 'opacity=".58"')}</g>
  ${modalFrame(390, 232, 892, 492)}${t(836, 293, '촬영 방식 선택', 34, 800, C.text, 'middle')}${t(836, 330, '등록할 제스처의 촬영 방식을 선택해주세요.', 18, 500, C.muted, 'middle')}
  <g id="static-choice">${cut(432, 364, 388, 270, C.white, C.line, 1.5, 16)}${circle(626, 434, 47, C.bg, C.blue, 2)}${handSilhouette(626, 451, 'wave', .23)}${t(626, 518, '정적 제스처 등록', 25, 800, C.text, 'middle')}${t(626, 553, '사진으로 촬영합니다.', 16, 500, C.muted, 'middle')}${t(626, 579, '3초 카운트다운 후 3회 반복 촬영', 14, 500, C.muted, 'middle')}${button(493, 646, 266, '사진으로 등록')}</g>
  <g id="dynamic-choice">${cut(852, 364, 388, 270, C.white, C.line, 1.5, 16)}${circle(1046, 434, 47, C.bg, C.blue, 2)}${handSilhouette(1046, 451, 'wave', .23, true)}${t(1046, 518, '동적 제스처 등록', 25, 800, C.text, 'middle')}${t(1046, 553, '영상으로 촬영합니다.', 16, 500, C.muted, 'middle')}${t(1046, 579, '3초 카운트다운 후 2초간 3회 반복', 14, 500, C.muted, 'middle')}${button(913, 646, 266, '영상으로 등록')}</g></svg>`;

const wireRecordingPage = () => wrap('39 촬영 중', `${flowHeading('제스처 촬영')}${cameraPanel(366, 198, 940, 430, 'dynamic', true)}
  ${rect(398, 664, 876, 12, C.pale, 'none', 0, 6)}${rect(398, 664, 584, 12, C.navy, 'none', 0, 6)}${t(398, 711, '2 / 3회 촬영 중', 18, 700)}${t(1274, 711, 'WebM 파일 생성 중', 16, 500, C.muted, 'end')}${button(686, 760, 300, '촬영 취소', false)}`);

const wireResultPage = () => wrap('40 촬영 결과 확인', `${flowHeading('촬영 결과')}${cameraPanel(410, 196, 852, 360, 'dynamic', false)}
  ${[0, 1, 2].map((i) => `${cut(566 + i * 190, 590, 166, 108, 'url(#grid)', C.line, 1.2, 10)}${cameraCorners(566 + i * 190, 590, 166, 108)}${t(649 + i * 190, 727, `${i + 1}회`, 16, 700, C.text, 'middle')}`).join('')}
  ${t(836, 775, '이 동작으로 등록할까요?', 20, 600, C.text, 'middle')}${button(594, 810, 230, '다시 촬영', false)}${button(848, 810, 230, '다음', true)}`);

const wireSimilarWarningPage = () => wrap('40-1 기존 제스처와 유사', `${flowHeading('제스처 만들기')}
  ${statusIcon(836, 226, 'alert')}${t(836, 304, '이미 등록된 제스처와 너무 비슷해요', 34, 800, C.text, 'middle')}
  ${t(836, 346, '둘을 구분하지 못해 잘못 실행될 수 있습니다.', 19, 500, C.muted, 'middle')}${t(836, 378, '손 모양이나 방향을 바꿔 다시 촬영해주세요.', 19, 500, C.muted, 'middle')}
  ${comparisonCard(250, 414, 'N E W   G E S T U R E', '지금 만든 제스처', false)}${comparisonCard(856, 414, 'E X I S T I N G   G E S T U R E', '주먹 쥐기', true)}
  ${button(666, 786, 340, '다시 촬영', true)}${t(836, 874, '혼동 가능한 제스처는 등록할 수 없습니다.', 15, 500, C.muted, 'middle')}`);

const wireRegisterPanel = (variant = 'base') => {
  const empty = variant === 'incomplete';
  const assigned = variant === 'fileAssigned';
  const rows = empty ? [] : assigned
    ? [actionRow(446, 386, 780, '1', '파일 열기 / 실행'), actionRow(446, 470, 780, '2', '회의록.txt 실행')]
    : [actionRow(446, 386, 780, '1', '음악 앱 실행'), actionRow(446, 470, 780, '2', '재생목록 ‘집중’ 재생'), ...(variant === 'base' ? [actionRow(446, 554, 780, '3', '볼륨 40%로 설정')] : [])];
  const addY = empty ? 454 : variant === 'base' ? 640 : 554;
  return `${flowHeading('제스처 등록')}${cut(330, 198, 1012, 650, C.white, C.line, 1.5, 20)}${tech(330, 198, 1012, 650)}
    ${t(402, 263, '제스처 이름', 20, 700)}${rect(402, 282, 868, 58, C.white, empty ? C.red : C.line, 1.5, 9)}${t(426, 319, empty ? '예: 손가락 하트' : '손가락 하트', 20, 500, empty ? '#9aaec5' : C.text)}${empty ? t(402, 368, '이름을 입력해주세요.', 15, 600, C.red) : ''}
    ${t(402, empty ? 430 : 360, '이 제스처로 실행할 기능', 20, 700)}${rows.join('')}${cut(446, addY, 780, 70, C.white, C.line, 1.2, 10, 'stroke-dasharray="6 5"')}${t(472, addY + 44, '＋ 기능 추가하기', 20, 600, C.muted)}
    ${empty ? t(446, 540, '기능을 하나 이상 추가해주세요.', 15, 500, C.muted) : t(446, addY + 99, '위에서 아래 순서대로 실행됩니다. 드래그하여 순서를 바꿀 수 있습니다.', 15, 500, C.muted)}
    ${button(884, 758, 160, '취소', false)}${button(1064, 758, 162, '다음', true, empty)}${variant === 'dropdown' ? functionDropdown() : ''}`;
};
const wireRegisterPage = (variant) => wrap(`41 제스처 등록 ${variant}`, wireRegisterPanel(variant));
const wireFilePickerPage = () => `${wireRegisterPage('fileAssigned').replace('</svg>', '')}<g id="dim-layer">${rect(0, 0, W, H, C.deep, 'none', 0, 0, 'opacity=".50"')}</g>${modalFrame(380, 220, 912, 520)}${t(416, 270, '파일 선택', 26, 800)}${line(380, 292, 1292, 292, C.pale)}${rect(408, 318, 250, 340, C.bg, C.pale, 1, 8)}${t(438, 370, '☆ 바로 가기', 19, 600)}${t(438, 420, '▣ 바탕화면', 19, 600)}${rect(420, 446, 220, 48, C.pale, 'none', 0, 7)}${t(438, 478, '▤ 문서', 19, 700)}${t(438, 532, '↓ 다운로드', 19, 600)}${rect(682, 318, 580, 48, C.bg, C.pale, 1, 6)}${t(704, 350, '이름', 17, 700)}${['2026 상반기 결산.pdf', '회의록.txt', '참고자료.xlsx', '메모.docx'].map((v, i) => `${rect(682, 378 + i * 52, 580, 46, i === 1 ? C.pale : C.white, 'none', 0, 5)}${t(708, 409 + i * 52, `□ ${v}`, 17, i === 1 ? 700 : 500)}`).join('')}${t(416, 700, '파일 이름', 17, 600)}${rect(520, 669, 460, 48, C.white, C.line, 1.2, 7)}${t(540, 700, '회의록.txt', 17, 500)}${button(1000, 660, 120, '취소', false)}${button(1138, 660, 124, '열기', true)}</svg>`;

const wireCompletePage = () => wrap('42 제스처 등록 완료', `${flowHeading('제스처 등록')}${cut(330, 206, 1012, 610, C.white, C.line, 1.5, 22)}${tech(330, 206, 1012, 610)}${statusIcon(836, 366, 'check')}${t(836, 468, '등록 완료!', 42, 800, C.text, 'middle')}${t(836, 526, '이 제스처를 사용하면 “음악 앱 실행 → 재생목록 집중 재생 → 볼륨 40%”를', 18, 500, C.muted, 'middle')}${t(836, 558, '순서대로 바로 실행할 수 있습니다.', 18, 500, C.muted, 'middle')}${button(686, 644, 300, '확인', true)}`);

const files = [
  ['37-gesture-list.svg', wireListPage()],
  ['37-1a-basic-gesture-detail.svg', basicGestureDetailPage()],
  ['37-1b-basic-gesture-function-edit.svg', basicGestureEditPage()],
  ['37-1-gesture-detail.svg', detailPage()],
  ['37-2-gesture-edit.svg', editPage()],
  ['37-3-delete-confirm.svg', deleteConfirmPage()],
  ['38-capture-waiting.svg', wireCaptureWaitingPage()],
  ['38-1-camera-unavailable.svg', wireCameraErrorPage()],
  ['38-2-capture-type-select.svg', wireTypeSelectPage()],
  ['39-recording-recognizing.svg', wireRecordingPage()],
  ['40-capture-result.svg', wireResultPage()],
  ['40-1-similar-gesture-warning.svg', wireSimilarWarningPage()],
  ['41-register-name-actions.svg', registerPage('base')],
  ['41-1-function-dropdown.svg', registerPage('dropdown')],
  ['41-1-1-file-assigned.svg', registerPage('fileAssigned')],
  ['41-1-2-file-picker.svg', nativeFilePickerPage()],
  ['41-2-incomplete-disabled.svg', registerPage('incomplete')],
  ['42-registration-complete.svg', fullPageCompletePage()],
];

for (const [fileName, svg] of files) fs.writeFileSync(path.join(outDir, fileName), svg, 'utf8');

fs.writeFileSync(path.join(outDir, 'README.md'), `# SIA editable gesture wireframe flow\n\n- 18 screens following wireframes 37–42, including basic-gesture detail and function-edit states\n- 1672 × 941 fixed canvas\n- Gesture list uses the same title, split-panel, registered-list, and guide-bar composition as Voice and Gaze\n- Existing SIA visual system retained; only wireframe content and flow applied\n- Custom-gesture camera areas are empty replaceable capture frames with no invented hand artwork\n- Basic gesture cards link to detail and function-edit screens\n- Camera-unavailable is a shared SIA modal over the gesture list page\n- Screens 41–42 are full dashboard-linked pages, not SIA modal popups\n- Screen 41-1-2 represents the operating system native file picker, not a site-styled modal\n- The user-supplied SIA logo is embedded unchanged as one selectable image object\n- Default hand previews are editable vector silhouettes, not raster images\n- All other text, frames, buttons, icons, decorations, states, and guides remain editable in Figma\n- Recommended font: Pretendard\n`, 'utf8');

console.log(`Generated ${files.length} editable gesture SVG screens in ${outDir}`);
