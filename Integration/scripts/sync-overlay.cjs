// Integration/overlay/ -> Frontend/public/overlay/ 로 복사한다.
// tauri.conf.json의 devUrl(Vite 개발 서버)/frontendDist(Vite 빌드 결과물) 둘 다
// Frontend 쪽 경로만 인식하므로, 오버레이 창(url: "overlay/index.html")이 뜨려면
// 이 파일이 Frontend의 정적 자산 경로(public/)에도 있어야 한다.
// Frontend 소스 자체는 건드리지 않음 — public/overlay/ 는 이 스크립트가 매 실행마다
// 새로 채우는 산출물이라 .gitignore 처리돼 있다 (agents.md 7장: src-tauri/ 는
// 배포 담당자 영역이라는 원칙과 같은 이유로, 이것도 FE 소스가 아니라 배포 산출물).
const fs = require("fs");
const path = require("path");

const src = path.join(__dirname, "..", "overlay");
const dest = path.join(__dirname, "..", "..", "Frontend", "public", "overlay");

fs.rmSync(dest, { recursive: true, force: true });
fs.mkdirSync(dest, { recursive: true });
for (const name of fs.readdirSync(src)) {
  fs.copyFileSync(path.join(src, name), path.join(dest, name));
}
console.log(`[sync-overlay] ${src} -> ${dest}`);
