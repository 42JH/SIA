import fs from 'node:fs';
import path from 'node:path';

const outDir = path.resolve('design/SIA-core-screens-editable-svg');
fs.mkdirSync(outDir, { recursive: true });

const C = { navy:'#08284a', deep:'#061b38', blue:'#1c65aa', mid:'#779bc1', pale:'#dce8f4', line:'#a9c0d8', bg:'#f6f9fc', white:'#fff', text:'#092244' };
const LOGO_DATA = `data:image/png;base64,${fs.readFileSync(path.resolve('design/SIA-logo-original-cutout.png')).toString('base64')}`;
const esc = s => String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const text = (x,y,s,size=24,weight=500,fill=C.text,anchor='start',extra='') => `<text x="${x}" y="${y}" font-family="Pretendard, Noto Sans KR, Malgun Gothic, sans-serif" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}" ${extra}>${esc(s)}</text>`;
const line = (x1,y1,x2,y2,stroke=C.line,w=1,dash='') => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${w}" ${dash ? `stroke-dasharray="${dash}"` : ''}/>`;
const rect = (x,y,w,h,fill=C.white,stroke=C.line,sw=1,r=0) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}"/>`;
const cutCard = (x,y,w,h,fill=C.white,stroke=C.line) => `<path d="M${x+18} ${y}H${x+w-22}L${x+w} ${y+22}V${y+h-18}L${x+w-18} ${y+h}H${x+22}L${x} ${y+h-22}V${y+18}Z" fill="${fill}" stroke="${stroke}" stroke-width="2"/>`;
const bars = (x,y,values,maxH=190,bw=42,gap=32,fill=C.mid) => values.map((v,i)=>`<rect x="${x+i*(bw+gap)}" y="${y+maxH-v}" width="${bw}" height="${v}" rx="2" fill="${fill}"/>`).join('');
const hamburger = (x=1530,y=44) => `<g id="hamburger" stroke="${C.navy}" stroke-width="4" stroke-linecap="round">${line(x,y,x+24,y,C.navy,4)}${line(x,y+9,x+24,y+9,C.navy,4)}${line(x,y+18,x+24,y+18,C.navy,4)}</g>`;
const logo = (x=50,y=28,s=.72) => `<image id="sia-logo-original" x="${x}" y="${y}" width="${183.5*s}" height="${38.4*s}" href="${LOGO_DATA}" preserveAspectRatio="xMidYMid meet"/>`;
const topbar = () => `<g id="topbar">${rect(0,0,1600,86,C.white,'none',0)}${line(0,85,1600,85,C.line,1)}${logo()}${hamburger()}</g>`;
const deco = (y=104) => `<g id="technical-decoration" fill="none" stroke="${C.blue}" stroke-width="1.5" opacity=".75"><path d="M150 ${y}H340L370 ${y+18}H760L790 ${y+38}H1150L1180 ${y+18}H1440"/>${line(930,y+55,1420,y+55,C.line,1)}<circle cx="910" cy="${y+55}" r="6"/><circle cx="1450" cy="${y+55}" r="4" fill="${C.navy}"/></g>`;
const page = (title,subtitle,body,opts={}) => `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000">
<rect id="page-background" width="1600" height="1000" fill="${C.bg}"/>
${topbar()}${deco()}
<g id="page-heading">${text(52,158,title,54,800)}${text(54,198,subtitle,22,500,C.blue)}</g>
${body}
</svg>`;

const appRows = (x,y) => ['크롬','메모장','슬랙','파일 탐색기'].map((s,i)=>`<g id="app-row-${i+1}">${text(x,y+i*48,s,20,600)}${rect(x+145,y-19+i*48,870,14,C.pale,'none',0,7)}${rect(x+145,y-19+i*48,[780,610,500,360][i],14,C.blue,'none',0,7)}${text(x+1045,y+i*48,['92%','68%','54%','38%'][i],18,600,C.mid)}</g>`).join('');
const donut = (cx,cy,pct,label) => `<g id="${label}"><circle cx="${cx}" cy="${cy}" r="48" fill="none" stroke="${C.pale}" stroke-width="12"/><circle cx="${cx}" cy="${cy}" r="48" fill="none" stroke="${C.navy}" stroke-width="12" stroke-dasharray="${pct*3.02} 302" transform="rotate(-90 ${cx} ${cy})"/>${text(cx,cy+8,`${pct}%`,24,800,C.text,'middle')}${text(cx,cy+84,label,16,600,C.text,'middle')}</g>`;

const dashboard = page('SIA 대시보드','AI가 더 편리한 일상을 만들어갑니다.',`
<g id="usage-panel">${cutCard(40,228,920,468,C.navy,C.navy)}${text(72,278,'USAGE',11,600,C.pale)}${text(72,326,'제스처 / 보이스 사용량',30,700,C.white)}${text(72,360,'최근 7일 사용 현황 · 음성 AI, 제스처를 보기',16,400,C.line)}
${[0,1,2,3,4].map(i=>line(115,400+i*55,920,400+i*55,'#315274',1)).join('')}${bars(150,424,[94,132,80,154,108,176,125],190,72,40,C.mid)}
${['월','화','수','목','금','토','일'].map((d,i)=>text(186+i*112,652,d,16,500,C.pale,'middle')).join('')}</g>
<g id="accuracy-panel">${rect(980,228,572,237,C.white,C.pale,2,16)}${text(1005,260,'AI STATUS',11,700,C.mid)}${text(1005,296,'인식 정확도',28,800)}${donut(1080,362,96,'음성 인식 정확도')}${donut(1260,362,91,'시선처리 정확도')}${donut(1440,362,89,'모션인식 정확도')}</g>
<g id="latency-summary">${rect(980,482,572,214,C.white,C.pale,2,16)}${text(1005,520,'RESPONSE',11,700,C.mid)}${text(1005,555,'평균 응답 시간',28,800)}${rect(1000,578,255,92,C.bg,C.pale,1,10)}${text(1024,612,'간단한 작업',17,600)}${text(1024,652,'0.8초',36,800)}${rect(1272,578,255,92,C.bg,C.pale,1,10)}${text(1296,612,'복잡한 작업',17,600)}${text(1296,652,'2.4초',36,800)}</g>
<g id="top-programs">${rect(40,720,1512,238,C.white,C.pale,2,16)}${text(72,758,'TOP PROGRAMS',11,700,C.mid)}${text(72,797,'자주 사용하는 프로그램',28,800)}${appRows(82,838)}</g>`);

const accuracy = page('인식 정확도','AI가 세상을 이해하는 정확도를 한눈에 확인하세요.',`
<g id="accuracy-chart">${cutCard(42,280,1510,470,C.navy,C.navy)}${text(82,320,'RECOGNITION ACCURACY',12,600,C.mid)}${['100%','75%','50%','25%','0%'].map((d,i)=>text(72,425+i*63,d,16,500,C.pale,'end')).join('')}${[0,1,2,3,4].map(i=>line(90,420+i*63,1510,420+i*63,'#315274',1,'6 5')).join('')}
<polyline points="90,448 280,432 470,455 660,435 850,430 1040,462 1230,458 1470,426" fill="none" stroke="#fff" stroke-width="3"/><polyline points="90,474 280,443 470,486 660,482 850,446 1040,444 1230,452 1470,470" fill="none" stroke="${C.pale}" stroke-width="2" stroke-dasharray="8 6"/><polyline points="90,492 280,454 470,466 660,486 850,472 1040,488 1230,460 1470,450" fill="none" stroke="${C.mid}" stroke-width="2" stroke-dasharray="2 5"/>
${['00시','03시','06시','09시','12시','15시','18시','21시'].map((d,i)=>text(90+i*197,710,d,16,500,C.pale,'middle')).join('')}</g>
${[['평균 음성 인식 정확도','95%'],['평균 시선처리 정확도','92%'],['평균 모션인식 정확도','90%']].map((a,i)=>`<g id="accuracy-card-${i+1}">${cutCard(44+i*512,775,490,176,C.white,C.line)}${text(82+i*512,820,a[0],20,600)}${text(82+i*512,895,a[1],58,800)}</g>`).join('')}`);

const latency = page('평균 응답 시간','작업 유형별 평균 응답 시간을 확인할 수 있습니다.',`
<g id="period-tabs">${cutCard(1010,168,520,80,C.white,C.line)}${rect(1024,180,130,56,C.navy,'none',0,8)}${['1일','7일','한달','1년'].map((d,i)=>text(1089+i*130,216,d,20,i?500:700,i?C.text:C.white,'middle')).join('')}</g>
<g id="latency-chart">${cutCard(48,292,1504,430,C.navy,C.navy)}${text(92,344,'시간대별 평균 응답 시간',24,700,C.white)}${[0,1,2,3,4].map(i=>line(128,392+i*62,1310,392+i*62,'#315274',1,'4 4')).join('')}${bars(150,424,[66,154,70,170,82,168,66,123,70,110,72,143,58,128,70,176],220,38,29,C.mid)}${['00시','03시','06시','09시','12시','15시','18시','21시'].map((d,i)=>text(188+i*137,686,d,16,500,C.pale,'middle')).join('')}
<g id="ai-orbit"><circle cx="1430" cy="500" r="78" fill="none" stroke="${C.mid}"/><circle cx="1430" cy="500" r="58" fill="none" stroke="${C.line}"/><circle cx="1430" cy="500" r="35" fill="none" stroke="${C.pale}"/>${text(1430,508,'SIA',18,700,C.pale,'middle')}</g></g>
${[['간단한 작업 평균','0.8초'],['복잡한 작업 평균','2.3초'],['전체 평균','1.5초']].map((a,i)=>`<g id="latency-card-${i+1}">${cutCard(50+i*510,752,490,185,i===2?C.navy:C.white,i===2?C.navy:C.line)}${text(92+i*510,816,a[0],20,600,i===2?C.white:C.text)}${text(92+i*510,886,a[1],58,800,i===2?C.white:C.text)}</g>`).join('')}`);

const settingsBody = `<g id="settings-layout">${cutCard(34,100,390,860,C.navy,C.navy)}<g id="left-orbit"><circle cx="225" cy="535" r="120" fill="none" stroke="${C.blue}"/><circle cx="225" cy="535" r="88" fill="none" stroke="${C.mid}"/><circle cx="225" cy="535" r="50" fill="none" stroke="${C.pale}"/>${Array.from({length:24},(_,i)=>`<circle cx="${225+42*Math.cos(i*Math.PI/12)}" cy="${535+42*Math.sin(i*Math.PI/12)}" r="2" fill="${C.pale}"/>`).join('')}</g>${bars(76,720,[12,22,36,58,95,52,34,70,28,18],100,8,8,'#75cfff')}
<g id="settings-content">${cutCard(424,100,1128,860,C.white,C.pale)}${text(485,174,'설정',52,800)}${line(485,224,1515,224,C.line)}${text(485,282,'▌ 호출명 (Wake Word)',22,700)}${rect(485,306,500,56,C.white,C.line,1,4)}${text(512,343,'시아',20,500)}${rect(1004,306,170,56,C.navy,C.navy,1,4)}${text(1089,343,'저장',20,700,C.white,'middle')}${text(505,389,'한국어 이름으로 입력해주세요.',16,400,C.mid)}
${text(485,456,'▌ 마이크',22,700)}${rect(485,478,490,126,C.white,C.pale,1,4)}${rect(510,516,305,58,C.white,C.line,1,5)}${text(530,553,'시스템 설정 마이크 (기본)',17,600)}${text(790,554,'⌄',25,600)}${rect(832,516,120,58,C.white,C.navy,1,5)}${text(892,553,'변경',17,700,C.text,'middle')}
${text(1038,456,'▌ 카메라',22,700)}${rect(1038,478,480,126,C.white,C.pale,1,4)}${rect(1062,516,305,58,C.white,C.line,1,5)}${text(1082,553,'내장 카메라 (기본)',17,600)}${text(1342,554,'⌄',25,600)}${rect(1380,516,115,58,C.white,C.navy,1,5)}${text(1438,553,'변경',17,700,C.text,'middle')}
${cutCard(485,640,1010,115,C.white,C.line)}${text(510,684,'▌ 동작',22,700)}${text(530,716,'시선 커서 표시',18,700)}${text(530,742,'화면에 현재 보고 있는 지점을 원으로 표시',15,400,C.mid)}${rect(1430,690,62,32,C.blue,'none',0,16)}<circle cx="1475" cy="706" r="13" fill="white"/>
${cutCard(485,770,1010,135,C.white,C.line)}${text(510,814,'▌ 실행',22,700)}${text(530,850,'컴퓨터 시작 시 자동 실행',18,700)}${text(530,878,'컴퓨터 전원을 켜면 SIA가 자동으로 함께 실행됩니다.',15,400,C.mid)}${rect(1430,830,62,32,C.blue,'none',0,16)}<circle cx="1475" cy="846" r="13" fill="white"/></g></g>`;
const settings = `<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000"><rect width="1600" height="1000" fill="${C.bg}"/>${topbar()}${settingsBody}</svg>`;

const ringIcon = (cx,cy,type='mic') => `<g id="${type}-ring"><circle cx="${cx}" cy="${cy}" r="126" fill="none" stroke="${C.mid}"/><circle cx="${cx}" cy="${cy}" r="102" fill="none" stroke="${C.pale}" stroke-width="3"/><circle cx="${cx}" cy="${cy}" r="72" fill="none" stroke="${C.blue}"/>${type==='mic'?`<rect x="${cx-18}" y="${cy-48}" width="36" height="72" rx="18" fill="none" stroke="white" stroke-width="7"/><path d="M${cx-42} ${cy+10}Q${cx-42} ${cy+56} ${cx} ${cy+56}Q${cx+42} ${cy+56} ${cx+42} ${cy+10}M${cx} ${cy+56}V${cy+84}M${cx-24} ${cy+84}H${cx+24}" fill="none" stroke="white" stroke-width="7"/>`:`<circle cx="${cx}" cy="${cy}" r="48" fill="none" stroke="white" stroke-width="3"/><path d="M${cx-78} ${cy}H${cx+78}M${cx} ${cy-78}V${cy+78}" stroke="white" stroke-width="3"/><circle cx="${cx+25}" cy="${cy-14}" r="10" fill="white"/>`}</g>`;
const listRows = (x,y,kind) => [2,3].map((n,i)=>`<g id="${kind}-profile-${n}">${rect(x,y+i*108,560,86,C.white,C.line,1,7)}${kind==='voice'?`<circle cx="${x+48}" cy="${y+43+i*108}" r="30" fill="none" stroke="${C.navy}" stroke-width="2"/>${text(x+48,y+52+i*108,'♩',28,700,C.navy,'middle')}`:`<circle cx="${x+48}" cy="${y+43+i*108}" r="30" fill="none" stroke="${C.navy}" stroke-width="2"/>${line(x+18,y+43+i*108,x+78,y+43+i*108,C.navy,2)}${line(x+48,y+13+i*108,x+48,y+73+i*108,C.navy,2)}`}${text(x+96,y+36+i*108,kind==='voice'?`내 목소리 ${n}`:`내 보정 ${n}`,22,700)}${text(x+96,y+65+i*108,`등록일 2026.0${n+3}.02`,16,500,C.blue)}${rect(x+425,y+20+i*108,116,48,C.white,C.navy,1,5)}${text(x+483,y+52+i*108,'사용으로 설정',15,700,C.navy,'middle')}</g>`).join('');
const profilePage = (kind) => { const voice=kind==='voice'; const title=voice?'보이스':'시선'; const sub=voice?'나만의 목소리로 더 편리한 경험을 시작하세요.':'시선 보정 프로필을 관리합니다.'; return page(title,sub,`
<g id="active-profile">${cutCard(38,280,830,500,C.navy,C.blue)}${text(78,326,voice?'ACTIVE VOICE':'ACTIVE GAZE',12,700,C.pale)}${text(78,382,voice?'현재 사용 중인 보이스':'현재 사용 중인 보정',36,800,C.white)}${ringIcon(455,525,voice?'mic':'gaze')}${text(78,708,voice?'내 목소리 1':'내 보정 1',31,700,C.white)}${text(78,744,'등록일 2026.03.12',19,500,C.pale)}${rect(650,692,165,50,'none',C.white,1,25)}<circle cx="682" cy="717" r="9" fill="white"/>${text(742,725,'사용 중',18,500,C.white,'middle')}</g>
<g id="registered-profiles">${cutCard(895,280,657,500,C.white,C.line)}${text(935,326,voice?'MY VOICES':'MY CALIBRATIONS',12,700,C.navy)}${text(935,378,voice?'등록된 내 목소리':'등록된 보정',36,800)}${rect(1332,328,180,56,C.navy,C.navy,1,5)}${text(1422,365,voice?'+ 보이스 추가':'+ 새 보정',18,600,C.white,'middle')}${listRows(935,418,kind)}</g>
<g id="profile-notice">${cutCard(38,808,1514,120,C.white,C.line)}${text(85,876,'!',30,800,C.navy)}${text(125,874,voice?'목소리 인식이 잘 되지 않으면, 보이스를 추가등록해보세요.':'시선 인식이 잘 되지 않으면, 새로 보정한 뒤 사용할 보정을 설정해보세요.',18,600,C.blue)}${rect(1320,838,190,58,C.white,C.navy,1,5)}${text(1415,875,voice?'보이스 삭제':'보정 삭제',19,700,C.navy,'middle')}</g>`); };

const gesture = page('제스처','손짓 하나로 SIA의 동작을 실행하고 관리합니다.',`
${text(50,318,'기본 제스처',28,800)}${rect(1260,268,280,62,C.navy,C.navy,1,4)}${text(1400,307,'＋  새 제스처 등록',20,600,C.white,'middle')}
<g id="default-gestures">${['손 흔들기|일시정지','엄지 척|좋아요','V 사인|사진 촬영','손바닥|음소거'].map((s,i)=>{const [a,b]=s.split('|');const x=45+i*380;return `${cutCard(x,350,355,225,C.white,C.line)}${rect(x+18,370,190,180,C.deep,C.blue,1,4)}${text(x+113,470,['☝','👍','✌','✋'][i],70,400,'#9ddcff','middle')}${rect(x+258,370,70,34,C.navy,'none',0,17)}<circle cx="${x+306}" cy="387" r="14" fill="white"/>${text(x+226,458,a,22,700)}${text(x+226,494,b,18,600,C.blue)}`}).join('')}</g>
${text(50,638,'내 커스텀 제스처',28,800)}<g id="custom-gestures">${['손가락 하트|음악 재생','주먹 쥐기|화면 캡처'].map((s,i)=>{const [a,b]=s.split('|');const x=45+i*380;return `${cutCard(x,664,355,225,C.white,C.line)}${rect(x+18,684,190,180,C.deep,C.blue,1,4)}${text(x+113,785,['♡','✊'][i],70,400,'#9ddcff','middle')}${rect(x+258,684,70,34,C.navy,'none',0,17)}<circle cx="${x+306}" cy="701" r="14" fill="white"/>${text(x+226,772,a,22,700)}${text(x+226,808,b,18,600,C.blue)}`}).join('')}</g>`);

const menuOpen = dashboard.replace('</svg>',`<g id="menu-dim"><rect width="1600" height="1000" fill="#071b36" opacity=".38"/></g><g id="hamburger-drawer">${rect(1160,0,440,1000,C.white,'none',0)}${[['✋','제스처'],['♩','보이스'],['◎','시선'],['⚙','설정']].map((a,i)=>`${text(1210,120+i*110,a[0],42,500,C.navy)}${text(1280,118+i*110,a[1],24,700)}${text(1540,118+i*110,'›',28,600,C.navy)}${line(1200,150+i*110,1560,150+i*110,C.pale)}`).join('')}</g></svg>`);

const result = (state) => { const good=state==='good', repeated=state==='repeated'; const pts = good?[[792,402],[815,420],[778,436],[830,450],[802,462],[760,446]]:repeated?[[650,414],[725,450],[800,430],[875,470],[950,420],[720,500],[900,512],[810,492]]:[[790,395],[835,412],[820,450],[860,468],[800,486],[845,500]]; const msg=good?'오차 범위 · 양호':repeated?'지속적으로 큰 오차가 발생하고 있습니다.':'오차범위 · 나쁨'; return page('시선 학습 결과','측정된 시선과 목표 위치의 차이를 확인해보세요.',`
<g id="result-card">${cutCard(50,222,1500,700,C.white,C.navy)}${text(86,272,'시선 학습 결과',25,800)}${rect(86,304,1428,390,C.bg,C.pale,1,0)}<circle cx="800" cy="470" r="78" fill="none" stroke="${C.line}" stroke-dasharray="4 4"/><circle cx="800" cy="470" r="10" fill="${C.navy}"/>${pts.map((p,i)=>`<g id="gaze-point-${i+1}"><circle cx="${p[0]}" cy="${p[1]}" r="7" fill="white" stroke="${C.blue}"/><circle cx="${p[0]+8}" cy="${p[1]+8}" r="5" fill="${C.navy}"/></g>`).join('')}${text(800,735,'○ 목표 지점   ● 실제 측정된 시선 위치 (오차)',14,500,C.mid,'middle')}${text(800,775,good?'평균 오차 18px · 최대 오차 31px':repeated?'평균 오차 54px · 최대 오차 86px':'평균 오차 38px · 최대 오차 62px',18,700,C.text,'middle')}${text(800,812,msg,18,700,repeated?'#8a2d37':good?C.blue:'#8a5a22','middle')}${text(800,844,repeated?'카메라 설정을 확인한 후 다시 측정해주세요.':good?'측정이 완료되었습니다.':'오차가 다소 큽니다. 시선을 다시 측정해주세요.',16,500,C.mid,'middle')}${rect(1260,846,210,56,repeated?C.navy:C.white,C.navy,1,5)}${text(1365,882,repeated?'카메라 설정':good?'계속 진행':'다시 측정',18,700,repeated?C.white:C.navy,'middle')}</g>`); };

const files = {
  '01-dashboard-home.svg': dashboard,
  '02-recognition-accuracy.svg': accuracy,
  '03-average-response-time.svg': latency,
  '04-settings.svg': settings,
  '05-voice.svg': profilePage('voice'),
  '06-gaze.svg': profilePage('gaze'),
  '07-gesture.svg': gesture,
  '08-dashboard-menu-open.svg': menuOpen,
  '09-gaze-result-good.svg': result('good'),
  '10-gaze-result-bad.svg': result('bad'),
  '11-gaze-result-bad-repeated.svg': result('repeated'),
};

for (const [name, svg] of Object.entries(files)) fs.writeFileSync(path.join(outDir, name), svg, 'utf8');
fs.writeFileSync(path.join(outDir, 'README.md'), `# SIA editable core screens\n\n- ${Object.keys(files).length} screens with editable SVG UI elements\n- The user-supplied original SIA logo is embedded unchanged as one selectable image object\n- All other text and UI shapes remain editable in Figma\n- Recommended font: Pretendard\n`, 'utf8');
console.log(`Generated ${Object.keys(files).length} SVG files in ${outDir}`);
