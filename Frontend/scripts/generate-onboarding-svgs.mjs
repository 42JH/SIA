import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const outDir = path.join(root, 'design', 'onboarding-svg');
fs.mkdirSync(outDir, { recursive: true });

const logoSource = 'C:/Users/SSAFY/.codex/generated_images/01a08f6c-b71d-7042-bba4-ab88431fe1fe/exec-902c0ad4-d099-43fa-a6f9-4b5da5b466b1.png';
const moleSource = 'C:/Users/SSAFY/Desktop/시안/mole/mole-cyberpunk-smart-glasses-pixel-lite.png';
const dataUri = (file) => `data:image/png;base64,${fs.readFileSync(file).toString('base64')}`;
const logoPng = dataUri(logoSource);
const molePng = dataUri(moleSource);

const css = `
  text{font-family:"Pretendard","Noto Sans KR","Malgun Gothic",sans-serif;fill:#071d45}
  .h{font-size:38px;font-weight:750}.sub{font-size:21px;fill:#5d79a4}.label{font-size:18px;font-weight:700}
  .body{font-size:20px}.small{font-size:16px;fill:#6680a7}.button{font-size:20px;font-weight:700;fill:white}
  .line{stroke:#0a326c;stroke-width:2;fill:none}.soft{stroke:#a9c5e8;stroke-width:2;fill:none}
  .card{fill:#f9fcff;stroke:#bdd0e7;stroke-width:2}.navy{fill:#061f4b}.cyan{fill:#13bfe8}
`;

const logo = () => `<svg x="176" y="122" width="210" height="88" viewBox="170 125 255 100" preserveAspectRatio="xMidYMid meet"><image href="${logoPng}" width="1584" height="993"/></svg>`;
const popupFrame = () => `
  <path d="M92 74H1410l42 42v760l-32 32H116L84 876V178l12-12V100z" fill="#fff" stroke="#071d45" stroke-width="5"/>
  <path d="M86 78h34v108l-14 14v676H86z" fill="#071d45"/>
  <path d="M116 876h410l18 16h390" class="soft"/>
  <path d="M1002 90h390l34 34" class="soft"/>
  ${logo()}`;

const accent = (x=190,y=354) => `<rect x="${x}" y="${y}" width="76" height="5" rx="2.5" fill="url(#accent)"/>`;
const defs = () => `<defs><linearGradient id="accent"><stop stop-color="#17d4e5"/><stop offset="1" stop-color="#175ae6"/></linearGradient><linearGradient id="btn" x2="1" y2="1"><stop stop-color="#0b3670"/><stop offset="1" stop-color="#03183d"/></linearGradient></defs><style>${css}</style>`;
const button = (label, x=1190, y=794, w=196, outline=false) => `<g><path d="M${x+12} ${y}h${w-24}l12 12v56l-12 12h-${w-24}l-12-12v-56z" fill="${outline?'white':'url(#btn)'}" stroke="#071d45" stroke-width="2"/><text x="${x+w/2}" y="${y+51}" text-anchor="middle" class="${outline?'body':'button'}" font-weight="700">${label}</text></g>`;
const base = (content) => `<svg xmlns="http://www.w3.org/2000/svg" width="1536" height="1024" viewBox="0 0 1536 1024">${defs()}${popupFrame()}${content}</svg>`;
const title = (t, sub='') => `<text x="190" y="330" class="h">${t}</text>${accent()}${sub?`<text x="190" y="420" class="sub">${sub}</text>`:''}`;
const input = (label,value,y,icon='') => `<text x="190" y="${y}" class="label">${label}</text><path d="M190 ${y+18}H1346l12 12v54l-12 12H190z" class="card"/><text x="218" y="${y+68}" class="body" fill="#5d79a4">${value}</text>${icon}`;
const rings = (cx,cy,kind='mic') => {
  const center = kind==='mic' ? `<path d="M${cx-16} ${cy-52}q16-16 32 0v58q-16 28-32 0zm-22 54q0 38 38 38t38-38M${cx} ${cy+40}v26m-22 0h44" class="line" stroke-width="6"/>` : `<path d="M${cx-46} ${cy}h92M${cx} ${cy-46}v92" class="line"/><circle cx="${cx}" cy="${cy}" r="14" class="navy"/><circle cx="${cx+34}" cy="${cy-26}" r="7" class="cyan"/>`;
  return `<circle cx="${cx}" cy="${cy}" r="150" class="soft"/><circle cx="${cx}" cy="${cy}" r="116" class="soft" stroke-dasharray="150 28"/><circle cx="${cx}" cy="${cy}" r="82" class="soft"/>${center}`;
};
const waveform = (x,y,count=19) => Array.from({length:count},(_,i)=>{const h=22+(i%5)*12+(i===9?35:0);return `<rect x="${x+i*25}" y="${y-h/2}" width="8" height="${h}" rx="4" fill="${i>6&&i<13?'#153b78':'#89afe4'}"/>`}).join('');
const check = (cx,cy) => `<circle cx="${cx}" cy="${cy}" r="86" class="line"/><circle cx="${cx}" cy="${cy}" r="118" class="soft" stroke-dasharray="98 26"/><path d="M${cx-38} ${cy}l27 29 54-61" fill="none" stroke="#071d45" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>`;
const plot = (bad=false) => {
  const pts=[[410,438],[770,438],[1130,438],[550,525],[960,525],[410,610],[770,610],[1130,610]];
  return `<rect x="190" y="368" width="1170" height="290" rx="10" class="card"/>${pts.map(([x,y],i)=>`<circle cx="${x}" cy="${y}" r="38" class="soft" stroke-dasharray="7 7"/><circle cx="${x}" cy="${y}" r="10" class="navy"/><circle cx="${x+(bad?(i%2?72:-68):18)}" cy="${y+(bad?(i%3?38:-50):-14)}" r="9" fill="#70a8f2"/>`).join('')}<circle cx="622" cy="690" r="8" class="navy"/><text x="644" y="697" class="small">목표 지점</text><circle cx="774" cy="690" r="8" fill="#70a8f2"/><text x="796" y="697" class="small">실제 측정 위치</text>`;
};

const screens = {
  '02-basic-settings.svg': base(`${title('기본 설정')}${input('비서 이름','시아',404)}${input('마이크 선택(내장 / 외장)','마이크를 선택해주세요',532,'<path d="M1304 574v28m-12-14q12 24 24 0" class="line"/>')}${input('카메라 선택(내장 / 외장)','카메라를 선택해주세요',660,'<rect x="1288" y="700" width="34" height="24" rx="4" class="line"/><circle cx="1305" cy="712" r="7" class="line"/>')}${button('다음')}`),
  '03-microphone-start.svg': base(`${title('마이크 설정','마이크 설정을 시작합니다')}${rings(1060,480,'mic')}${button('시작하기')}`),
  '04-call-name.svg': base(`${title('이름 불러보기') }<text x="190" y="440" class="body">“시아야”라고 불러주세요.</text><text x="190" y="510" class="small">호출명을 인식하고 있습니다.</text><text x="700" y="390" class="sub">REC 00:02</text>${waveform(680,500)}${rings(1260,500,'mic').replace(/r="150"/g,'r="96"').replace(/r="116"/g,'r="72"').replace(/r="82"/g,'r="54"')}${button('다음')}`),
  '05-command-recording.svg': base(`${title('AI에게 명령하듯 말해보세요')}<text x="190" y="430" class="sub">2 / 5 문장</text><rect x="190" y="468" width="660" height="98" rx="10" class="card"/><text x="520" y="526" text-anchor="middle" class="body">“시아야, 오늘 날씨 알려줘”</text><text x="190" y="620" class="small">현재 녹음 중입니다.</text>${rings(1120,476,'scope')}${waveform(520,760)}`),
  '06-recording-confirmation.svg': base(`${title('이 목소리로 등록할까요?','녹음한 목소리를 확인한 뒤 등록해주세요.')}<rect x="190" y="492" width="1170" height="188" rx="12" class="card"/>${rings(302,586,'mic').replace(/r="150"/g,'r="70"').replace(/r="116"/g,'r="54"').replace(/r="82"/g,'r="38"')}${waveform(470,586)}<text x="1270" y="594" class="sub">00:04</text>${button('다시 녹음',870,744,220,true)}${button('등록',1110,744,220)}`),
  '07-microphone-complete.svg': base(`${title('마이크 설정')}${check(1010,465)}<text x="1010" y="620" text-anchor="middle" class="h">마이크 설정 완료!</text><text x="1010" y="672" text-anchor="middle" class="sub">목소리 등록이 완료되었습니다.</text>${button('다음 (카메라 설정)',1110,780,278)}`),
  '08-gaze-start.svg': base(`${title('시선 설정','시선 설정을 시작합니다')}<circle cx="1040" cy="470" r="150" class="soft" stroke-dasharray="110 22"/><circle cx="1040" cy="470" r="105" class="soft"/><path d="M996 438h66v64h-66zM1062 452l46-28v92l-46-28z" class="line" stroke-width="6"/>${button('시작하기')}`),
  '09-position-check.svg': base(`${title('위치 확인')}<rect x="430" y="240" width="930" height="470" rx="10" class="card"/><text x="488" y="286" class="small">● CAMERA LIVE</text><path d="M472 304v-34h34m812 0h34v34M472 646v34h34m812 0h34v-34" class="soft" stroke-width="7"/><circle cx="895" cy="410" r="80" class="soft" stroke-dasharray="9 9"/><path d="M760 622q28-132 135-132t135 132" class="soft" stroke-dasharray="9 9"/><text x="895" y="650" text-anchor="middle" class="body">얼굴이 원 안에 들어오도록 위치해주세요</text><rect x="430" y="724" width="930" height="56" rx="8" class="card"/><text x="458" y="760" class="small">카메라와의 거리를 확인하고 있습니다.</text>${button('다음')}`),
  '10-gaze-guide.svg': base(`${title('시선 측정을 시작하겠습니다')}<rect x="190" y="430" width="650" height="250" rx="12" class="card"/><text x="240" y="492" class="body">• 화면에 나타나는 두더지를 바라보면 됩니다.</text><text x="240" y="555" class="body">• 두더지를 약 1초간 바라보세요.</text><text x="240" y="618" class="body">• 총 9개 위치를 순서대로 측정합니다.</text>${rings(1120,515,'scope')}${button('취소',930,784,190,true)}${button('시작하기',1140,784,250)}`),
  '12-gaze-result-bad.svg': base(`${title('시선 학습 결과')}${plot(true)}<text x="775" y="735" text-anchor="middle" class="sub">평균 오차 74px · 최대 오차 118px</text><text x="775" y="780" text-anchor="middle" class="body" font-weight="700">오차 범위: 나쁨</text><text x="775" y="820" text-anchor="middle" class="small">오차가 다소 큽니다. 시선을 다시 측정해주세요.</text>${button('다시 측정',1160,780,220)}`),
  '13-gaze-result-bad-repeated.svg': base(`${title('시선 학습 결과')}${plot(true)}<circle cx="236" cy="754" r="28" class="line"/><text x="236" y="764" text-anchor="middle" class="body">!</text><text x="286" y="748" class="body" font-weight="700">지속적으로 큰 오차가 발생하고 있습니다.</text><text x="286" y="790" class="small">카메라 설정을 확인한 후 다시 측정해주세요.</text>${button('카메라 설정',1140,770,250,true)}`),
  '14-gaze-result-good.svg': base(`${title('시선 학습 결과')}${plot(false)}<text x="775" y="735" text-anchor="middle" class="sub">평균 오차 38px · 최대 오차 62px</text><text x="775" y="780" text-anchor="middle" class="body" font-weight="700">오차 범위: 양호</text>${button('다시 측정',930,784,210,true)}${button('계속 진행',1160,784,220)}`),
  '15-gaze-complete.svg': base(`${title('시선 설정')}${check(1010,465)}<text x="1010" y="620" text-anchor="middle" class="h">시선 설정 완료!</text><text x="1010" y="672" text-anchor="middle" class="sub">시선 학습이 완료되었습니다.</text>${button('다음')}`),
  '16-setup-complete.svg': base(`${title('설정 완료')}${check(1010,465)}<circle cx="884" cy="396" r="7" class="cyan"/><circle cx="1142" cy="416" r="10" fill="#74b9ee"/><circle cx="1114" cy="590" r="6" class="cyan"/><text x="1010" y="620" text-anchor="middle" class="h">완료!</text><text x="1010" y="672" text-anchor="middle" class="sub">이제 SIA를 시작할 수 있습니다.</text>${button('완료')}`),
};

const game = `<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000">${defs()}<rect width="1600" height="1000" fill="#f7fbff"/><path d="M0 92H1600M0 366H1600M0 640H1600M535 92V1000M1065 92V1000" stroke="#dbe9f8"/><text x="800" y="62" text-anchor="middle" class="body" font-weight="700">튀어나온 두더지를 1초간 바라보면 잡힙니다</text>${button('보정 중단',1400,20,170,true)}${[[270,230],[800,230],[1330,230],[270,505],[800,505],[1330,505],[270,780],[800,780],[1330,780]].map(([x,y],i)=>`<g><circle cx="${x}" cy="${y}" r="120" class="soft"/><circle cx="${x}" cy="${y}" r="100" class="soft"/><path d="M${x-128} ${y}h32m192 0h32M${x} ${y-128}v32m0 192v32" class="line"/><ellipse cx="${x}" cy="${y+18}" rx="105" ry="48" fill="#0a1830"/><ellipse cx="${x}" cy="${y+5}" rx="98" ry="35" fill="#263b59"/>${i===4?`<svg x="${x-98}" y="${y-128}" width="196" height="190" viewBox="260 165 840 820" preserveAspectRatio="xMidYMid meet"><image href="${molePng}" width="1358" height="1159"/></svg><path d="M${x+20} ${y-120}a122 122 0 0 1 78 93" fill="none" stroke="#13bfe8" stroke-width="8"/>`:''}</g>`).join('')}</svg>`;
screens['11-mole-game-fullscreen.svg'] = game;

for (const [name, svg] of Object.entries(screens)) fs.writeFileSync(path.join(outDir, name), svg, 'utf8');

const ordered = Object.keys(screens).sort();
fs.writeFileSync(path.join(outDir, 'README.md'), `# SIA onboarding SVG\n\n${ordered.map((name)=>`- ${name}`).join('\n')}\n`, 'utf8');
console.log(`Generated ${ordered.length} SVG files in ${outDir}`);
