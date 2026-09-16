import fs from 'node:fs';
import path from 'node:path';

const outputDir = path.resolve('design/SIA-voice-flow-editable-svg');
fs.mkdirSync(outputDir, { recursive: true });

const P = { navy:'#082c59', deep:'#061d3d', dark:'#0a376b', blue:'#176bd1', cyan:'#71bfff', pale:'#d9e8f7', line:'#9bbce0', bg:'#f7fbff', white:'#ffffff', text:'#082756', muted:'#6089bd', dim:'#092747' };
const LOGO_DATA = `data:image/png;base64,${fs.readFileSync(path.resolve('design/SIA-logo-original-cutout.png')).toString('base64')}`;
const esc = value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const t = (x,y,value,size=24,weight=500,fill=P.text,anchor='start',attrs='') => `<text x="${x}" y="${y}" font-family="Pretendard, Noto Sans KR, Malgun Gothic, sans-serif" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}" ${attrs}>${esc(value)}</text>`;
const rect = (x,y,w,h,fill='none',stroke='none',sw=0,rx=0,attrs='') => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" ${attrs}/>`;
const line = (x1,y1,x2,y2,stroke=P.line,sw=1,attrs='') => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${sw}" ${attrs}/>`;
const circle = (cx,cy,r,fill='none',stroke='none',sw=0,attrs='') => `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" ${attrs}/>`;
const cut = (x,y,w,h,fill=P.white,stroke=P.blue,sw=2,cutSize=22) => `<path d="M${x+cutSize} ${y}H${x+w-cutSize}L${x+w} ${y+cutSize}V${y+h-cutSize}L${x+w-cutSize} ${y+h}H${x+cutSize}L${x} ${y+h-cutSize}V${y+cutSize}Z" fill="${fill}" stroke="${stroke}" stroke-width="${sw}"/>`;
const defs = () => `<defs><linearGradient id="pageGlow" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#edf7ff"/></linearGradient><linearGradient id="navyPanel" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#061d3d"/><stop offset=".55" stop-color="#0a376b"/><stop offset="1" stop-color="#082852"/></linearGradient><filter id="softShadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="10" stdDeviation="16" flood-color="#031a37" flood-opacity=".22"/></filter></defs>`;
const logo = (x,y,s=.72) => `<image id="sia-logo-original" x="${x}" y="${y}" width="${183.5*s}" height="${38.4*s}" href="${LOGO_DATA}" preserveAspectRatio="xMidYMid meet"/>`;
const hamburger = (x,y) => `<g id="hamburger-button">${rect(x-17,y-18,54,54,P.white,P.blue,1.5,10)}${line(x,y-5,x+20,y-5,P.navy,4,'stroke-linecap="round"')}${line(x,y+5,x+20,y+5,P.navy,4,'stroke-linecap="round"')}${line(x,y+15,x+20,y+15,P.navy,4,'stroke-linecap="round"')}</g>`;
const circuit = (W) => `<g id="header-circuit" fill="none" stroke="${P.navy}" stroke-width="2"><path d="M${W*.37} 130H${W*.48}L${W*.5} 148H${W*.66}L${W*.69} 118H${W*.82}"/>${circle(W*.37,130,6,P.white,P.navy,2)}${[0,1,2,3].map(i=>circle(W*.58+i*15,116,4,P.navy)).join('')}<path d="M${W*.66} 102H${W*.74}L${W*.76} 88H${W*.84}" stroke="${P.blue}"/></g>`;
const audioBadge = (x,y) => `<g id="audio-badge">${circle(x,y,70,P.white,P.navy,2)}${circle(x,y,58,'none',P.blue,1)}${[-30,-18,-6,6,18,30].map((dx,i)=>line(x+dx,y-(18+[12,25,38,25,12,6][i])/2,x+dx,y+(18+[12,25,38,25,12,6][i])/2,P.navy,7,'stroke-linecap="round"')).join('')}</g>`;
const header = (W,title='보이스',subtitle='나만의 목소리로 더 편리한 경험을 시작하세요.') => `<g id="header">${rect(0,0,W,82,P.white,'none')}${line(0,81,W,81,P.line,1)}${logo(42,25,.72)}${hamburger(W-70,38)}${t(42,160,title,58,800)}${t(43,201,subtitle,25,600,P.blue)}${circuit(W)}${audioBadge(W-180,102)}</g>`;
const technicalMarks = (x,y,w,h) => `<g id="panel-decoration" fill="none" stroke="${P.blue}" stroke-width="2"><path d="M${x+25} ${y+8}H${x+150}"/><path d="M${x+w-170} ${y+h-10}H${x+w-25}"/>${[0,1,2,3].map(i=>circle(x+w-58+i*12,y+26,3,P.navy)).join('')}<path d="M${x+28} ${y+h-20}l20 0"/><path d="M${x+w-80} ${y+20}l45 0"/></g>`;
const wave = (x,y,w,h,color=P.cyan,count=42,id='waveform') => `<g id="${id}">${Array.from({length:count},(_,i)=>{const p=i/(count-1);const amp=(.18+.82*Math.abs(Math.sin(i*.83)*Math.cos(i*.29)))*(1-Math.abs(p-.5)*.3);const bh=Math.max(5,h*amp);return rect(x+p*w-2,y-bh/2,4,bh,color,'none',0,2,`id="${id}-bar-${i+1}"`)}).join('')}</g>`;
const micIcon = (x,y,s=1,color=P.white) => `<g id="microphone-icon" transform="translate(${x} ${y}) scale(${s})" fill="none" stroke="${color}" stroke-width="7" stroke-linecap="round"><rect x="-20" y="-60" width="40" height="82" rx="20"/><path d="M-45 5Q-45 55 0 55Q45 55 45 5M0 55V86M-25 86H25"/></g>`;
const radarMic = (cx,cy,r=150) => `<g id="microphone-radar">${circle(cx,cy,r,'none',P.cyan,1)}${circle(cx,cy,r*.78,'none',P.white,4)}${circle(cx,cy,r*.62,'none',P.blue,1)}${circle(cx,cy,r*.96,'none',P.line,1,'stroke-dasharray="2 8"')}${micIcon(cx,cy,1.12,P.white)}</g>`;
const button = (x,y,w,h,label,primary=false,id='button') => `<g id="${id}">${rect(x,y,w,h,primary?'url(#navyPanel)':P.white,P.navy,2,6)}${t(x+w/2,y+h/2+8,label,21,700,primary?P.white:P.text,'middle')}</g>`;
const pageOpen = (W,H) => `<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${defs()}${rect(0,0,W,H,'url(#pageGlow)')}`;

function mainPage(W,H,{active=1,renamed=false,selection=false}={}){
  const top=225, bottom=H-115, panelH=bottom-top-20, gap=22, leftW=W*.53, rightX=leftW+gap+28, rightW=W-rightX-28;
  const activeName=`내 목소리 ${active}`; const activeDate=active===2?'2026.05.02':'2026.03.12';
  const names=active===2
    ? ['내 목소리 1','내 목소리 3','내 목소리 4']
    : [renamed?'스튜디오 보이스':'내 목소리 2','내 목소리 3','내 목소리 4'];
  const dates=active===2
    ? ['2026.03.12','2026.07.20','2026.08.22']
    : ['2026.05.02','2026.07.20','2026.08.22'];
  const rowH=(panelH-145)/3;
  return `${header(W)}<g id="voice-main-content"><g id="active-voice-panel">${cut(28,top,leftW,panelH,'url(#navyPanel)',P.blue,2,22)}${technicalMarks(28,top,leftW,panelH)}${t(72,top+48,'A C T I V E   V O I C E',13,700,P.pale)}${t(72,top+100,'현재 사용 중인 보이스',35,800,P.white)}${wave(85,top+panelH*.49,leftW-170,120,P.cyan,48,'active-waveform')}${radarMic(28+leftW*.52,top+panelH*.50,120)}${t(72,top+panelH-76,activeName,30,800,P.white)}${t(72,top+panelH-38,`등록일 ${activeDate}`,21,500,P.pale)}${rect(28+leftW-210,top+panelH-96,165,52,'none',P.white,1.5,26)}${circle(28+leftW-182,top+panelH-70,9,P.white)}${t(28+leftW-110,top+panelH-62,'사용 중',20,500,P.white,'middle')}</g>
  <g id="registered-voices-panel">${cut(rightX,top,rightW,panelH,P.white,P.blue,2,22)}${technicalMarks(rightX,top,rightW,panelH)}${t(rightX+40,top+46,'M Y   V O I C E S',13,700,P.navy)}${t(rightX+40,top+98,'등록된 내 목소리',35,800)}${button(rightX+rightW-210,top+35,175,58,'＋ 보이스 추가',true,'add-voice-button')}${names.map((name,i)=>{const y=top+122+i*(rowH+10);return `<g id="voice-row-${i+1}">${rect(rightX+28,y,rightW-56,rowH,P.white,P.pale,1.5,6)}${selection?`${rect(rightX+45,y+rowH/2-13,26,26,i===0?P.navy:P.white,P.navy,2,5)}${i===0?`<path d="M${rightX+51} ${y+rowH/2}l7 7 12-16" fill="none" stroke="white" stroke-width="3"/>`:''}`:''}${circle(rightX+(selection?105:70),y+rowH/2,34,P.white,P.navy,2)}${micIcon(rightX+(selection?105:70),y+rowH/2+5,.28,P.navy)}${wave(rightX+(selection?150:115),y+rowH/2,155,55,P.muted,26,`voice-${i+1}-waveform`)}${t(rightX+(selection?325:290),y+rowH/2-6,name,21,700)}${t(rightX+(selection?325:290),y+rowH/2+25,`등록일 ${dates[i]}`,16,500,P.blue)}${rect(rightX+rightW-170,y+rowH/2-27,135,54,P.white,P.navy,1.5,24)}${t(rightX+rightW-102,y+rowH/2+7,'사용으로 설정',16,700,P.text,'middle')}</g>`}).join('')}</g>
  <g id="bottom-action-bar">${cut(28,H-100,W-56,78,P.white,P.blue,2,16)}${circle(80,H-61,20,P.white,P.navy,3)}${t(80,H-53,'!',25,800,P.navy,'middle')}${t(120,H-53,'목소리 인식이 잘 되지 않으면, 보이스를 추가등록해보세요.',18,600,P.blue)}${selection?`${button(W-555,H-87,180,54,'취소',false,'cancel-selection')}${button(W-355,H-87,200,54,'완전 삭제',true,'delete-selected')}${line(W-130,H-87,W-130,H-32,P.line,1)}${t(W-70,H-53,'1개 선택됨',17,600,P.blue,'middle')}`:button(W-285,H-87,235,54,'보이스 삭제',false,'delete-voice-button')}</g></g>`;
}

function enrollmentPage(W,H,type='guide'){
  const top=220, x=70, totalW=W-140, panelH=H-top-65, leftW=totalW*.43, rightX=x+leftW;
  let right='';
  if(type==='guide') right=`${t(rightX+totalW*.285,top+205,'조용한 곳에서 3문장을 읽어주세요',35,800,P.text,'middle')}${t(rightX+totalW*.285,top+255,'화면에 나오는 문장을 자연스럽게 읽으면 됩니다.',22,500,P.muted,'middle')}${t(rightX+totalW*.285,top+292,'약 30초 정도 걸립니다.',22,500,P.muted,'middle')}${rect(rightX+65,top+335,totalW-leftW-130,74,P.white,P.line,1.5,6)}${t(rightX+95,top+381,'마이크 · Realtek Audio',21,600)}${t(x+totalW-105,top+381,'정상',20,600,P.blue,'end')}${button(rightX+(totalW-leftW)/2-165,top+445,330,70,'녹음 시작',true,'record-start')}`;
  if(type==='recording') right=`${t(rightX+65,top+70,'2 / 3 문장',22,600,P.blue)}${t(x+totalW-70,top+70,'REC 00:06  ●',21,600,P.blue,'end')}${rect(rightX+65,top+105,totalW-leftW-130,175,P.white,P.pale,1.5,6)}${t(rightX+(totalW-leftW)/2,top+175,'오늘 일정은 오전 열 시에',34,700,P.text,'middle')}${t(rightX+(totalW-leftW)/2,top+225,'회의 하나만 남아 있어요.',34,700,P.text,'middle')}${rect(rightX+65,top+305,totalW-leftW-130,92,P.white,P.pale,1.5,6)}${circle(rightX+110,top+351,30,P.white,P.navy,2)}${micIcon(rightX+110,top+355,.23,P.navy)}${wave(rightX+165,top+351,totalW-leftW-320,60,P.blue,40,'recording-waveform')}${t(x+totalW-92,top+360,'음성 감지 중',17,700,P.blue,'end')}${rect(rightX+65,top+420,totalW-leftW-330,9,P.pale,'none',0,5)}${rect(rightX+65,top+420,(totalW-leftW-330)*.62,9,P.blue,'none',0,5)}${t(x+totalW-70,top+432,'문장을 다 읽으면 자동으로 다음',16,500,P.muted,'end')}${button(rightX+245,top+480,180,60,'이 문장 다시',false,'retry-sentence')}${button(rightX+445,top+480,150,60,'중단',false,'stop-recording')}`;
  if(type==='review') right=`${t(rightX+(totalW-leftW)/2,top+150,'이 목소리로 등록할까요?',36,800,P.text,'middle')}${t(rightX+(totalW-leftW)/2,top+202,'재생해 들어보고, 마음에 들지 않으면 다시 녹음할 수 있습니다.',20,500,P.muted,'middle')}${circle(rightX+90,top+300,34,P.white,P.navy,2)}${micIcon(rightX+90,top+304,.27,P.navy)}${wave(rightX+145,top+300,totalW-leftW-300,70,P.muted,40,'review-waveform')}${t(x+totalW-85,top+308,'00:04',18,500,P.muted,'end')}${rect(rightX+65,top+365,totalW-leftW-130,72,P.white,P.line,1.5,6)}${t(rightX+90,top+410,'녹음 품질 · 양호',19,700)}${t(x+totalW-95,top+410,'주변 소음 없음',18,500,P.muted,'end')}${button(rightX+205,top+470,220,66,'다시 녹음',false,'record-again')}${button(rightX+445,top+470,220,66,'등록',true,'register-voice')}`;
  if(type==='complete') right=`${circle(rightX+(totalW-leftW)/2,top+190,70,P.white,P.navy,2)}<path d="M${rightX+(totalW-leftW)/2-28} ${top+190}l20 22 45-50" fill="none" stroke="${P.navy}" stroke-width="7"/>${t(rightX+(totalW-leftW)/2,top+320,'등록 완료!',42,800,P.text,'middle')}${t(rightX+(totalW-leftW)/2,top+370,'이제 내 목소리를 다른 사람의 말과 구분해',22,500,P.blue,'middle')}${t(rightX+(totalW-leftW)/2,top+408,'명령을 실행합니다.',22,500,P.blue,'middle')}${button(rightX+(totalW-leftW)/2-180,top+455,360,70,'확인',true,'confirm-registration')}`;
  return `${header(W,type==='review'?'녹음 확인':'보이스 녹음',type==='review'?'이 목소리로 등록할지 확인해보세요.':'나만의 목소리로 더 편리한 경험을 시작하세요.')}<g id="enrollment-layout">${cut(x,top,leftW,panelH,'url(#navyPanel)',P.blue,2,24)}${technicalMarks(x,top,leftW,panelH)}${radarMic(x+leftW/2,top+panelH/2,150)}${cut(rightX,top,totalW-leftW,panelH,P.white,P.blue,2,24)}${technicalMarks(rightX,top,totalW-leftW,panelH)}${right}</g>`;
}

function modalLayer(W,H,{kind='info',title,body=[],buttons=[],input=null,detail=null}){
  const mw=Math.min(740,W*.48), mh=input?370:kind==='warning'?420:360, mx=(W-mw)/2, my=(H-mh)/2+25;
  const iconY=my+82;
  const icon=kind==='success'?`${circle(W/2,iconY,48,P.white,P.navy,2)}<path d="M${W/2-20} ${iconY}l15 17 34-38" fill="none" stroke="${P.navy}" stroke-width="5"/>`:kind==='mic'?`${circle(W/2,iconY,48,P.white,P.navy,2)}${micIcon(W/2,iconY+4,.36,P.navy)}${circle(W/2+34,iconY-34,16,P.navy)}${t(W/2+34,iconY-27,'!',20,800,P.white,'middle')}`:`${circle(W/2,iconY,48,P.white,P.navy,2)}${t(W/2,iconY+12,'!',43,700,P.navy,'middle')}`;
  const btnY=my+mh-80, total=buttons.length*220+(buttons.length-1)*18, start=W/2-total/2;
  return `<g id="modal-overlay">${rect(0,0,W,H,P.dim,'none',0,0,'opacity=".58"')}${cut(mx,my,mw,mh,P.white,P.blue,2.5,28)}${technicalMarks(mx,my,mw,mh)}${kind==='input'?'':icon}${kind==='input'?`${t(mx+48,my+78,title,30,800)}${line(mx+48,my+98,mx+90,my+98,P.blue,2)}${t(mx+48,my+150,'보이스 이름',18,600)}${rect(mx+48,my+172,mw-96,62,P.white,P.navy,1.5,5)}${t(mx+70,my+212,input,20,500)}`:`${t(W/2,my+165,title,30,800,P.text,'middle')}${body.map((b,i)=>t(W/2,my+208+i*34,b,19,500,P.muted,'middle')).join('')}${detail?t(W/2,my+235,detail,20,600,P.blue,'middle'):''}`}${buttons.map((b,i)=>button(start+i*238,btnY,220,58,b,i===buttons.length-1,`modal-button-${i+1}`)).join('')}</g>`;
}

const VOICE_CANVAS = [1672, 941];
const dimensions={
  '02-add-voice-popup.svg':VOICE_CANVAS, '03-recording-guide.svg':VOICE_CANVAS, '04-mic-unavailable.svg':VOICE_CANVAS, '05-sentence-recording.svg':VOICE_CANVAS, '06-recording-quality-warning.svg':VOICE_CANVAS, '07-recording-review.svg':VOICE_CANVAS, '08-registration-complete.svg':VOICE_CANVAS, '09-rename-popup.svg':VOICE_CANVAS, '10-rename-complete.svg':VOICE_CANVAS, '11-renamed-list.svg':VOICE_CANVAS, '12-voice-replace-complete.svg':VOICE_CANVAS, '13-replaced-list.svg':VOICE_CANVAS, '14-delete-selection.svg':VOICE_CANVAS, '15-delete-confirm.svg':VOICE_CANVAS
};

function make(name){
  const [W,H]=dimensions[name]; let content='';
  if(name==='02-add-voice-popup.svg') content=mainPage(W,H)+modalLayer(W,H,{kind:'mic',title:'보이스를 추가 등록하시겠습니까?',buttons:['취소','새로 시작']});
  if(name==='03-recording-guide.svg') content=enrollmentPage(W,H,'guide');
  if(name==='04-mic-unavailable.svg') content=enrollmentPage(W,H,'guide')+modalLayer(W,H,{kind:'mic',title:'마이크를 사용할 수 없어요',body:['마이크 연결 또는 권한 설정을 확인해주세요.','권한을 허용한 뒤 다시 시도할 수 있습니다.'],buttons:['시스템 설정 열기','다시 확인']});
  if(name==='05-sentence-recording.svg') content=enrollmentPage(W,H,'recording');
  if(name==='06-recording-quality-warning.svg') content=enrollmentPage(W,H,'recording')+modalLayer(W,H,{kind:'warning',title:'목소리가 잘 들리지 않았어요',body:['주변 소음이 크거나 마이크의 거리가 멀 수 있습니다.','조용한 곳에서 다시 읽어주세요.'],buttons:['그대로 진행','다시 녹음']});
  if(name==='07-recording-review.svg') content=enrollmentPage(W,H,'review');
  if(name==='08-registration-complete.svg') content=enrollmentPage(W,H,'complete');
  if(name==='09-rename-popup.svg') content=mainPage(W,H)+modalLayer(W,H,{kind:'input',title:'보이스 이름 변경',input:'내 목소리 2',buttons:['취소','저장']});
  if(name==='10-rename-complete.svg') content=mainPage(W,H,{renamed:true})+modalLayer(W,H,{kind:'success',title:'이름이 변경되었습니다',detail:'내 목소리 2 → 스튜디오 보이스',buttons:['확인']});
  if(name==='11-renamed-list.svg') content=mainPage(W,H,{renamed:true});
  if(name==='12-voice-replace-complete.svg') content=mainPage(W,H,{active:2})+modalLayer(W,H,{kind:'success',title:'보이스가 교체되었습니다',detail:'내 목소리 1 → 내 목소리 2',buttons:['확인']});
  if(name==='13-replaced-list.svg') content=mainPage(W,H,{active:2});
  if(name==='14-delete-selection.svg') content=mainPage(W,H,{selection:true});
  if(name==='15-delete-confirm.svg') content=mainPage(W,H,{selection:true})+modalLayer(W,H,{kind:'warning',title:'선택한 보이스 1개를 삭제하시겠습니까?',body:['삭제 후에는 되돌릴 수 없습니다.'],buttons:['취소','삭제']});
  return pageOpen(W,H)+content+'</svg>';
}

for(const name of Object.keys(dimensions)) fs.writeFileSync(path.join(outputDir,name),make(name),'utf8');
fs.writeFileSync(path.join(outputDir,'README.md'),`# SIA Voice Flow — Editable SVG\n\n- 14 screens rebuilt with editable SVG UI elements\n- Every screen uses one fixed 1672 × 941 canvas\n- The user-supplied original SIA logo is embedded unchanged as one selectable image object\n- All other text, frames, decorations, waveform bars, icons, and buttons remain editable in Figma\n- Recommended font: Pretendard\n`,'utf8');
console.log(`Generated ${Object.keys(dimensions).length} editable SVG screens in ${outputDir}`);
