# SIA DOM Text Bridge (크롬 확장)

확장은 두 가지를 한다. 계약은 `Backend/docs/프로토콜.md` §6 참조.

1. **페이지 본문 공급** — "이 뉴스 3줄 요약해줘" 류 발화용. AI 가 `/ws/agent` 로 `dom_text_request` 를
   보내면 BE 가 이 확장(`/ws/ext`)에 중계하고, 확장이 활성 탭에서 본문을 추출해 돌려준다.
   **확장이 없어도 동작은 한다** — BE 가 화면 접근성(UIA)으로 브라우저 창을 직접 읽는 폴백이 있다.
   다만 본문만 골라내지 못해 메뉴·사이드바가 섞이고, 그때마다 사용자에게 "확장이 없다" 팝업이 뜬다.
   **확장을 설치하는 값어치가 여기 있다** (프로토콜.md §6.6).
2. **탭 열기** — `browser.search` 도구의 실행 경로. BE 가 `browser_open_request` 를 보내면
   활성 크롬 창에 새 탭으로 연다. **확장이 없어도 검색은 된다** — 그때는 BE 가 OS 기본 브라우저로
   열고 AI 에게 `domAvailable: false` 로 알린다 (열어 주기만 하고 본문은 못 읽는다는 뜻).

## 설치 (개발자 모드)

1. Chrome → `chrome://extensions` → 우상단 **개발자 모드** 켜기
2. **압축해제된 확장 프로그램을 로드합니다** → 이 `Extension/` 폴더 선택
3. BE 가 떠 있으면 자동으로 `ws://127.0.0.1:61015/ws/ext` 에 붙는다
   (BE 를 나중에 켜도 1분 주기 알람이 재접속한다. `GET /api/status` 의 `extConnected` 로 확인)

## 동작

- 접속 직후 `hello {extVersion}` 송신, 이후 20초마다 `ping` (MV3 서비스 워커 생존 유지)
- `dom_text_request {requestId}` 수신 → 마지막 포커스 창의 활성 탭에
  `chrome.scripting.executeScript` 로 추출 함수 주입 → `article`/`main`/`[role=main]`/`body` 순으로
  `innerText` 를 얻어 공백 정리 후 20,000자 컷 → `dom_text {requestId, available, url, title, text, truncated}` 회신
- `chrome://`, 웹 스토어, PDF 뷰어 등 주입 불가 페이지는 `{available:false, reason}` 으로 답한다
- `browser_open_request {requestId, url}` 수신 → `chrome.tabs.create` 로 새 탭을 열고
  로딩 완료를 최대 2.5초 기다렸다가 `browser_open {requestId, ok, url, title, tabId}` 회신.
  시간 안에 못 끝내면 `title` 만 비운다 (탭은 이미 열려 있으므로 실패가 아니다)

## 보안

- 통신 대상은 루프백(`127.0.0.1:61015`) 하나뿐 — 외부 네트워크로는 아무것도 보내지 않는다
- 확장을 설치하면 BE 의 접근성 폴백이 아예 돌지 않는다 — Chromium 렌더러 접근성 트리를 켜지
  않아도 되므로 브라우저 성능 비용이 생기지 않는다
- 열어 주는 주소는 `http(s)` 뿐이다. BE 가 먼저 막고 확장이 한 번 더 막는다 —
  루프백 소켓이어도 신뢰 경계로 본다 (`file:` · `javascript:` 로 로컬 파일을 열 수 없다)
- 본문 추출은 BE 의 요청이 있을 때만 1회성으로 수행한다 (상시 콘텐츠 스크립트 없음)
- 추출된 텍스트는 BE 를 거쳐 로컬 AI 에게만 전달되고 저장되지 않는다
