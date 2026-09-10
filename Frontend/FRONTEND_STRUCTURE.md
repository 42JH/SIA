# Frontend 구조와 파일별 책임

## 1. 전체 구조

현재 프런트엔드는 React, Vite, React Router, Zustand, Axios를 사용한다.

```text
Frontend/
├─ src/
│  ├─ api/                 REST 통신
│  ├─ ws/                  WebSocket 통신
│  ├─ store/               전역 상태
│  ├─ routes/              URL과 페이지 연결
│  ├─ pages/               실제 화면 단위
│  │  ├─ onboarding/       다운로드 후 첫 설정과 장치 재등록
│  │  ├─ dashboard/        대시보드, 그래프 상세, 설정
│  │  └─ connection-check/ 통신 확인 화면
│  ├─ components/          여러 화면에서 사용하는 공통 UI
│  │  ├─ onboarding/       시선 측정과 통신 기록
│  │  └─ popup/            상단 팝업과 우측 하단 실행 알림
│  ├─ styles/              전역 디자인 기준
│  ├─ main.jsx             React 실행 진입점
│  └─ App.jsx              앱 전체 구성
├─ index.html
├─ vite.config.js
├─ package.json
├─ agents.md
├─ COMMUNICATION.md
└─ ONBOARDING.md
```

앱 실행 흐름은 다음과 같다.

```text
index.html
  → main.jsx
    → App.jsx
      ├─ WebSocket 연결 시작
      ├─ 전역 팝업 표시
      └─ router.jsx
          ├─ 온보딩
          ├─ 통신 확인
          └─ 대시보드
```

## 2. 실행 진입점과 라우터

| 파일 | 역할 |
| --- | --- |
| `index.html` | React가 들어갈 `root` 요소와 최초 스크립트를 선언한다. |
| `src/main.jsx` | React 앱을 브라우저에 렌더링하고 전역 CSS를 불러온다. |
| `src/App.jsx` | 프런트 전체를 총괄한다. WebSocket을 한 번만 연결하고 전역 팝업과 라우터를 배치한다. |
| `src/routes/router.jsx` | URL별로 어떤 페이지를 보여줄지 결정한다. |

현재 URL 연결은 다음과 같다.

| URL | 화면 |
| --- | --- |
| `/`, `/onboarding` | 다운로드 후 첫 설정 |
| `/dashboard` | 대시보드와 설정 |
| `/connection-check` | REST·WebSocket 통신 확인 |

## 3. `src/pages`: 실제 화면

### 3.1 `pages/onboarding`

다운로드 후 최초 설정과 대시보드에서 진입하는 장치 재등록 화면을 담당한다.

| 파일 | 역할 |
| --- | --- |
| `OnboardingHome.jsx` | 라우터가 가져오는 온보딩 진입점이다. 실제 구현인 `OnboardingFlow`를 내보낸다. |
| `OnboardingFlow.jsx` | 온보딩 전체 화면 흐름을 총괄한다. 기본 설정, 호출어, 명령 문장, 보이스 등록, 시선 보정, 완료 화면이 들어 있다. 마이크 전용·카메라 전용 재등록도 구분한다. |
| `useOnboarding.js` | 온보딩 WebSocket 수신부다. 백엔드의 진행·완료·오류 이벤트를 화면 상태로 바꾸고 `/api/status`를 주기적으로 확인한다. |
| `enrollmentConstants.js` | 음성 등록 문장 5개와 호출어 1회 제한 안내값 5초를 보관한다. |
| `OnboardingHome.module.css` | 온보딩 카드, 버튼, 입력창, 결과 화면 스타일을 담당한다. |

`OnboardingFlow.jsx`가 현재 온보딩의 화면과 분기 로직을 대부분 담당한다.

### 3.2 `pages/dashboard`

대시보드 홈, 그래프 상세, 설정과 장치 변경을 담당한다.

| 파일 | 역할 |
| --- | --- |
| `DashboardHome.jsx` | 대시보드 전체를 총괄한다. 홈·상세 그래프·설정 화면 전환, 메뉴, 기간 선택과 데이터 조회를 관리한다. |
| `DashboardChart.jsx` | 선 그래프, 세로 막대그래프, 프로그램 사용량 가로 막대그래프를 그린다. 전달받은 실제 API 데이터를 사용한다. |
| `SettingsPanel.jsx` | 장치 목록, 마이크·카메라 변경, 기존 학습 데이터 선택, 새 등록 진입과 설정 토글을 담당한다. |
| `DashboardHome.module.css` | 대시보드, 설정, 그래프, 메뉴 서랍과 모달 스타일을 관리한다. |

장치 변경은 `SettingsPanel.jsx`에서 시작하고 실제 등록 화면은 `OnboardingFlow.jsx`가 담당한다.

- 마이크 변경: 마이크 등록 과정만 실행한다.
- 카메라 변경: 시선 보정 과정만 실행한다.
- 변경할 장치는 등록이 완료된 뒤 실제 설정에 저장한다.
- 중간에 등록을 중단하면 기존 장치 설정을 유지한다.

### 3.3 `pages/connection-check`

| 파일 | 역할 |
| --- | --- |
| `ConnectionCheck.jsx` | 백엔드 연결을 눈으로 확인하는 진단 화면이다. WebSocket 이벤트와 `GET /api/status` 결과를 표시한다. |
| `ConnectionCheck.module.css` | 통신 확인 화면 전용 스타일이다. |

제품의 일반 화면보다는 개발 중 REST·WebSocket 통신을 확인하기 위한 페이지다.

## 4. `src/api`: REST 통신

모든 REST 요청은 `http://127.0.0.1:8080`의 백엔드로 보낸다. 프런트는 AI에 직접 REST 요청을 보내지 않는다.

| 파일 | 역할 및 담당 API |
| --- | --- |
| `httpClient.js` | Axios 공통 설정이다. 백엔드 주소, 요청 제한 시간과 REST 통신 기록을 총괄한다. |
| `errors.js` | 백엔드 오류와 네트워크 오류를 공통 `ApiError` 형식으로 변환한다. |
| `status.js` | `GET /api/status`를 호출한다. |
| `devices.js` | `GET /api/devices`를 호출한다. |
| `settings.js` | 설정 조회와 전체 설정 저장을 담당한다. |
| `settingsContract.js` | 설정 응답에 필수 값이 들어 있는지 검사한다. |
| `onboarding.js` | 설치 앱 스캔과 등록 음성 샘플 URL 변환을 담당한다. |
| `profiles.js` | 음성·시선 프로필 조회, 활성화, 삭제와 장치 재연결을 담당한다. |
| `dashboard.js` | 대시보드 요약, 정확도, 응답 시간, 사용량과 프로그램 통계를 조회한다. |

REST 흐름은 다음과 같다.

```text
페이지 또는 컴포넌트
  → api의 기능별 파일
    → httpClient.js
      → Backend REST API
```

## 5. `src/ws`: 실시간 통신

프런트는 `ws://127.0.0.1:8080/ws/fe` 하나만 사용한다.

| 파일 | 역할 |
| --- | --- |
| `feSocket.js` | WebSocket 연결, 재연결, 송신, 수신 JSON 검사와 통신 기록을 총괄한다. |
| `eventBus.js` | 수신한 이벤트를 `type`별 구독자에게 전달한다. |
| `onboarding.js` | 온보딩 이벤트 발신, 예상 응답 관리와 보이스 `tempId` 검사를 담당한다. |
| `notifications.js` | 선택 팝업에서 사용자의 선택을 `user_choice` 이벤트로 보낸다. |

수신 흐름은 다음과 같다.

```text
Backend WebSocket 메시지
  → feSocket.js
    → eventBus.js
      ├─ sessionStore.js
      ├─ notificationStore.js
      └─ useOnboarding.js
```

송신 흐름은 다음과 같다.

```text
페이지 또는 컴포넌트
  → ws/onboarding.js 또는 ws/notifications.js
    → feSocket.js
      → Backend
        → AI
```

프런트와 AI는 직접 연결하지 않으며 모든 실시간 통신은 `FE ↔ BE ↔ AI` 순서로 진행한다.

## 6. `src/store`: 전역 상태

Zustand를 사용해 여러 화면에서 공유해야 하는 상태를 보관한다.

| 파일 | 역할 |
| --- | --- |
| `sessionStore.js` | WebSocket 연결 여부와 현재 음성 명령 세션 상태를 보관한다. |
| `onboardingStore.js` | 온보딩 단계, 호출어 진행률, 문장 진행률, `tempId`, 시선 결과와 오류를 보관한다. |
| `notificationStore.js` | 상단 팝업 종류와 노출 시간을 관리한다. 삭제 확인은 10초, 요약은 10초다. |
| `communicationStore.js` | 최근 REST·WebSocket 통신 기록 150개를 메모리에 보관한다. |

스토어에는 서버가 보낸 상태를 저장하며 등록 성공이나 진행률을 프런트에서 임의로 만들지 않는다. 호출어 화면은 사용자 확정 기준에 따라 5회까지만 표시하고 진행한다.

## 7. `src/components`: 공통 UI

### 7.1 `components/onboarding`

| 파일 | 역할 |
| --- | --- |
| `GazeMeasurement.jsx` | 전체화면 9점 시선 측정, 표시 좌표 계산과 `calib_point_shown` 전송을 담당한다. |
| `CommunicationLog.jsx` | REST·WebSocket 발신·수신·실패 기록을 펼쳐서 확인하는 공통 진단 UI다. |
| 각 `.module.css` | 해당 컴포넌트 전용 스타일이다. |

### 7.2 `components/popup`

| 파일 | 역할 |
| --- | --- |
| `TopNotification.jsx` | 듣는 중, 실행 중, 성공, 오류, 삭제 확인, 요약, 선택지, 캡처 결과와 세션 카운트다운 팝업을 렌더링한다. |
| `BootToast.jsx` | 앱이 백그라운드에서 정상 실행됐을 때 우측 하단에 3초간 표시한다. |
| `hooks.js` | 삭제 확인과 세션 남은 시간을 초 단위로 계산한다. |
| 각 `.module.css` | 상단 팝업과 우측 하단 팝업 스타일이다. |

`App.jsx`가 전역 팝업을 라우터 바깥에 배치하기 때문에 대시보드 내부 화면이 바뀌어도 팝업이 유지된다. 첫 설정 중에는 팝업을 숨긴다.

## 8. `src/styles`: 디자인 공통 기준

| 파일 | 역할 |
| --- | --- |
| `tokens.css` | 색상, 크기, 간격, 팝업·온보딩·대시보드 치수를 CSS 변수로 관리한다. 후일 디자인 변경 시 중심이 되는 파일이다. |
| `global.css` | 기본 글꼴과 박스 크기 계산 등 앱 전체 공통 스타일을 담당한다. |

화면별 상세 스타일은 해당 JSX 파일 옆의 `.module.css`에 두고, 여러 화면에서 공유하는 디자인 수치는 `tokens.css`에 둔다.

## 9. 최상위 설정과 문서

| 파일 또는 폴더 | 역할 |
| --- | --- |
| `package.json` | React, Router, Zustand, Axios 의존성과 실행 명령을 정의한다. |
| `package-lock.json` | 설치된 패키지 버전을 고정한다. |
| `vite.config.js` | Vite와 React 플러그인 설정이다. |
| `agents.md` | 프런트 구현과 통신 시 지켜야 할 프로젝트 기준이다. |
| `COMMUNICATION.md` | 연결한 REST·WebSocket 흐름과 통신 제약을 기록한다. |
| `ONBOARDING.md` | 온보딩 순서와 확인 방법을 설명한다. |
| `node_modules/` | 설치된 외부 라이브러리다. 직접 수정하지 않는다. |
| `dist/` | `npm run build` 결과물이다. 원본 코드가 아니다. |

## 10. 현재 책임이 큰 파일

유지보수 시 우선 확인할 중심 파일은 다음과 같다.

1. `src/App.jsx`: 앱 전체 WebSocket과 전역 팝업
2. `src/pages/onboarding/OnboardingFlow.jsx`: 온보딩 전체 단계와 화면 분기
3. `src/pages/onboarding/useOnboarding.js`: 온보딩 실시간 수신 처리
4. `src/pages/dashboard/DashboardHome.jsx`: 대시보드 화면 전환과 데이터 조회
5. `src/pages/dashboard/SettingsPanel.jsx`: 설정과 장치 변경 흐름
6. `src/ws/feSocket.js`: WebSocket 연결 자체
7. `src/api/httpClient.js`: 모든 REST 요청의 공통 진입점

## 11. 문서와 코드의 현재 차이

현재 실행 코드는 호출어 등록을 **5회**로 처리한다.

- `src/store/onboardingStore.js`: 최초 진행률 `total: 5`
- `src/pages/onboarding/useOnboarding.js`: 수신 진행률을 최대 5회로 처리
- `src/pages/onboarding/OnboardingFlow.jsx`: 시작 요청과 화면 진행률을 5회로 처리

