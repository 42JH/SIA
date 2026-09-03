# SIA DOM Text Bridge (크롬 확장)

"이 뉴스 3줄 요약해줘" 류 발화에 필요한 **페이지 본문 텍스트 공급원**이다.
AI 가 `/ws/agent` 로 `dom_text_request` 를 보내면 BE 가 이 확장(`/ws/ext`)에 중계하고,
확장이 활성 탭에서 본문을 추출해 돌려준다. 계약은 `Backend/docs/프로토콜.md` §6 참조.

## 설치 (개발자 모드)

1. Chrome → `chrome://extensions` → 우상단 **개발자 모드** 켜기
2. **압축해제된 확장 프로그램을 로드합니다** → 이 `Extension/` 폴더 선택
3. BE 가 떠 있으면 자동으로 `ws://127.0.0.1:8080/ws/ext` 에 붙는다
   (BE 를 나중에 켜도 1분 주기 알람이 재접속한다. `GET /api/status` 의 `extConnected` 로 확인)

## 동작

- 접속 직후 `hello {extVersion}` 송신, 이후 20초마다 `ping` (MV3 서비스 워커 생존 유지)
- `dom_text_request {requestId}` 수신 → 마지막 포커스 창의 활성 탭에
  `chrome.scripting.executeScript` 로 추출 함수 주입 → `article`/`main`/`[role=main]`/`body` 순으로
  `innerText` 를 얻어 공백 정리 후 20,000자 컷 → `dom_text {requestId, available, url, title, text, truncated}` 회신
- `chrome://`, 웹 스토어, PDF 뷰어 등 주입 불가 페이지는 `{available:false, reason}` 으로 답한다

## 보안

- 통신 대상은 루프백(`127.0.0.1:8080`) 하나뿐 — 외부 네트워크로는 아무것도 보내지 않는다
- 본문 추출은 BE 의 요청이 있을 때만 1회성으로 수행한다 (상시 콘텐츠 스크립트 없음)
- 추출된 텍스트는 BE 를 거쳐 로컬 AI 에게만 전달되고 저장되지 않는다
