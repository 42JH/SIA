# 첫 설정 화면

`npm run dev` 후 `/` 또는 `/onboarding`에서 시작한다. 기존 통신 확인 화면은 `/connection-check`다.

환영 → 기본 설정 → 마이크 시작 → 호출어 5샘플 → 보이스 문장 녹음·판독 결과 확인 5회 → 마이크 완료 → 시선 시작 → 위치 확인 → 측정 안내 → 9점 측정 → 결과 → 시선 완료 → 전체 완료 순서다. 마이크 시작에서 건너뛰면 시선 설정으로 이동한다.

REST는 기존 Axios 인스턴스를 사용하고 `/api/status`를 3초 간격으로 조회한다. 설정 전체와 `updatedAt`을 저장하고 설치 앱 스캔을 호출한다. 장치 목록은 GET /api/devices로 조회한다. 선택한 장치 이름과 ID를 micDevice·micDeviceId·cameraDevice·cameraDeviceId로 함께 저장한다. 시스템 기본 장치는 null로 저장한다. FE는 마이크·카메라 권한을 요청하거나 입력을 수집하지 않는다. 보이스 문장 화면에는 지정 문장과 서버가 중계한 마이크 입력 레벨 파형을 표시하고, 판독 결과 화면에는 녹음 품질과 진행 버튼을 표시한다.

시선은 `calib_start` → `calib_precheck` → `calib_point` → `calib_point_shown` → `calib_result` → `calib_commit` → `calib_saved`로 연결한다. 안내 화면에서 도착한 점은 보관하고 실제 측정 전체화면에 점이 표시된 뒤 좌표를 보낸다. 코 중심을 물리 픽셀로 변환하며 현재 주 모니터 전체화면만 지원한다. 결과 산점도는 서버의 실제 오차 벡터를 사용한다. 재측정은 서버의 남은 횟수를 사용하며 나쁨이 연속 3회면 카메라 설정을 안내한다.

## 보이스 계약 적용

- `voice_sentence`와 `voice_progress`에서 받은 `tempId`를 등록이 끝날 때까지 보관한다.
- 문장 판독 실패는 `voice_sentence_rejected {tempId,n,total,reason,code?}`를 구독한다. 진행 중인 `tempId`와 현재 문장 번호가 모두 일치할 때만 실패 결과를 표시하고, 성공 진행률은 올리지 않는다.
- 알려진 실패 코드 `TOO_SHORT`·`TOO_LONG`·`NOISY`·`INCONSISTENT`·`MISMATCH`는 FE 문구를 표시하고, 코드가 없거나 모르는 값이면 서버의 `reason`을 표시한다.
- 호출어 실패는 `wakeword_rejected`의 `reason`을 표시하고 진행 수를 올리지 않는다. 5번째 샘플 뒤에도 `wakeword_done`을 받아야 완료된다.
- 호출어·보이스 녹음 화면에서는 `mic_preview_start`로 시작한 `mic_preview_level {seq, level}`을 실시간 파형으로 표시하고 화면 이탈 시 `mic_preview_stop`을 보낸다.
- 문장 다시 녹음은 `voice_sentence_retry {tempId}`, 1~4번째 판독 결과 확인은 `voice_sentence_next {tempId}`, 최종 등록은 `voice_commit {tempId, deviceLabel?}`를 사용한다.
- `quality`가 null이거나 빈 문자열이면 `미판정`, 실패 `reason`이 비어 있으면 제대로 녹음되지 않았으니 같은 문장을 다시 읽으라는 공통 안내를 표시한다.
- 다중 모니터 물리 좌표를 정확히 변환하기 위한 원점·배율 계약이 없다.
- 호출어 수집 취소 이벤트가 명세에 없다.

## 실제 연동 확인

1. BE와 AI를 실행하고 연결 표시를 확인한다.
2. 서버에서 받은 장치 목록에서 마이크·카메라를 선택하고 기본 설정을 저장한다. 브라우저 장치 권한 요청이 없어야 한다.
3. 호출어 진행률과 완료 이벤트를 확인한다. 보이스 문장은 녹음 → 판독 결과를 5회 반복하며, 다시 녹음 요청에 저장한 `tempId`가 포함되는지 확인한다.
4. 시선은 마이크 건너뛰기로도 진입 가능하다. 주 모니터에서 위치 확인 후 전체화면 측정을 시작한다.
5. 9개 점과 실제 결과 수신, 재측정, 저장 완료를 확인한다. 전체화면 해제·WS 중단 시 재시작 안내를 확인한다.

빌드 성공은 REST·WS·AI의 실제 인식 성공을 의미하지 않는다. 서버·AI 코드는 수정하지 않았다.
