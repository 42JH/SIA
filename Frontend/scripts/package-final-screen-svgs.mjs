import fs from 'node:fs';
import path from 'node:path';

const screens = [
  {
    name: '01-welcome-popup.svg',
    source: 'C:/Users/SSAFY/AppData/Local/Temp/codex-clipboard-b8b49aae-90e3-400a-bfd5-17a32376a1c1.png',
    popup: true,
  },
  {
    name: '02-response-time-analysis.svg',
    source: 'C:/Users/SSAFY/AppData/Local/Temp/codex-clipboard-f5bc2032-08bb-4135-9a84-bd2aeb6455da.png',
  },
  {
    name: '03-dashboard.svg',
    source: 'C:/Users/SSAFY/AppData/Local/Temp/codex-clipboard-cef8ce25-5a34-4dbb-be23-ebb5098bd49d.png',
  },
  {
    name: '04-settings.svg',
    source: 'C:/Users/SSAFY/AppData/Local/Temp/codex-clipboard-f4e1b958-f242-46d2-8579-5c9e183cc5ab.png',
  },
  {
    name: '05-voice.svg',
    source: 'C:/Users/SSAFY/AppData/Local/Temp/codex-clipboard-3f97f1e0-51ed-4a69-b7e7-0976d776765c.png',
  },
  {
    name: '06-gaze.svg',
    source: 'C:/Users/SSAFY/AppData/Local/Temp/codex-clipboard-0832e3d8-d21d-4305-bfea-4979960c110d.png',
  },
  {
    name: '07-gesture.svg',
    source: 'C:/Users/SSAFY/AppData/Local/Temp/codex-clipboard-55e6f971-a8b2-42fd-b6b8-d2b7de1e3ea1.png',
  },
];

const outputDir = path.resolve('design/final-screen-svg');
fs.mkdirSync(outputDir, { recursive: true });

function pngSize(buffer) {
  const signature = buffer.subarray(1, 4).toString('ascii');
  if (signature !== 'PNG') throw new Error('PNG 파일이 아닙니다.');
  return {
    width: buffer.readUInt32BE(16),
    height: buffer.readUInt32BE(20),
  };
}

function fullScreenSvg(buffer, width, height, title) {
  const image = buffer.toString('base64');
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${title}">
  <title>${title}</title>
  <image width="${width}" height="${height}" preserveAspectRatio="none" href="data:image/png;base64,${image}" xlink:href="data:image/png;base64,${image}"/>
</svg>
`;
}

function welcomePopupSvg(buffer) {
  const image = buffer.toString('base64');
  const cropX = 104;
  const cropY = 90;
  const cropWidth = 1378;
  const cropHeight = 821;
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${cropWidth}" height="${cropHeight}" viewBox="0 0 ${cropWidth} ${cropHeight}" role="img" aria-label="SIA 환영 팝업">
  <title>SIA 환영 팝업</title>
  <defs>
    <clipPath id="popup-shape">
      <path d="M0 0H1337L1378 40V782L1340 821H26L0 796V125L25 99V0Z"/>
    </clipPath>
  </defs>
  <g clip-path="url(#popup-shape)">
    <image x="-${cropX}" y="-${cropY}" width="1584" height="993" preserveAspectRatio="none" href="data:image/png;base64,${image}" xlink:href="data:image/png;base64,${image}"/>
  </g>
</svg>
`;
}

for (const screen of screens) {
  const buffer = fs.readFileSync(screen.source);
  const { width, height } = pngSize(buffer);
  const title = path.basename(screen.name, '.svg');
  const svg = screen.popup
    ? welcomePopupSvg(buffer)
    : fullScreenSvg(buffer, width, height, title);
  fs.writeFileSync(path.join(outputDir, screen.name), svg, 'utf8');
}

const readme = `# SIA 최종 화면 SVG

- 01: 환영 팝업 — 팝업 외부 투명 처리
- 02: 평균 응답 시간 분석
- 03: SIA 대시보드
- 04: 설정
- 05: 보이스
- 06: 시선
- 07: 제스처

첨부된 최종 시안의 픽셀, 문구, 배치를 그대로 유지하기 위해 원본 화면을 SVG 내부에 포함한 독립형 파일입니다. 외부 PNG 파일 연결 없이 각 SVG만으로 열립니다.
`;
fs.writeFileSync(path.join(outputDir, 'README.md'), readme, 'utf8');

console.log(`Generated ${screens.length} SVG files in ${outputDir}`);
