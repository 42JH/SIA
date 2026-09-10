# 첫 설정 통신 연결

FE는 `http://127.0.0.1:8080` REST와 `ws://127.0.0.1:8080/ws/fe`만 사용한다. AI와 직접 연결하거나 브라우저 마이크·카메라 권한을 요청하지 않는다.

## 연결한 흐름

| 화면 | FE 발신 | FE 수신·처리 |
|---|---|---|
| 기본 설정 | GET /api/settings, GET /api/devices | 설정·장치 목록 표시 |
| 설정 저장 | PUT /api/settings | 전체 settings와 updatedAt 전송. 장치 이름과 ID 포함 |
| 앱 등록 | POST /api/apps/scan | 실제 응답 이후 마이크 단계로 이동 |
| 호출어 | wakeword_enroll_start | wakeword_progress, wakeword_done |
| 명령 문장 | command_enroll_start | command_sentence, command_progress, command_done |
| 보이스 | voice_reg_start | voice_sentence, voice_progress, command_rejected, voice_quality_warn, voice_review, voice_reg_denied |
| 보이스 재시도 | voice_sentence_retry, voice_reg_retry | voice_sentence 수신 후 진행 |
| 품질 경고 무시 | voice_accept_anyway | voice_review 수신 후 샘플 확인 |
| 보이스 저장 | voice_commit | voice_saved 이후 마이크 완료 |
| 보이스 중단 | voice_reg_cancel | 현재 계약에 완료 응답 없음. 전송만 기록 |
| 시선 시작 | calib_start | calib_precheck, calib_point, calib_denied |
| 점 표시 | calib_point_shown {n,x,y} | 다음 calib_point 또는 calib_result |
| 시선 재측정 | calib_restart | calib_point, calib_limit |
| 시선 저장 | calib_commit | calib_saved 이후 시선 완료 |
| 시선 중단 | calib_cancel | 현재 계약에 완료 응답 없음. 전송만 기록 |
| 연결 상태 | GET /api/status 주기 조회 | agent_status, settings_sync도 반영 |

`voiceTempId`는 서버가 제공한 값만 저장·재사용한다. FE가 임의로 생성하지 않는다. 문장은 사용자 확정 원문 5개를 순번에 맞춰 표시한다. 등록 진행률이나 성공을 가짜로 생성하지 않는다. 보이스 문장 처리 중 수신한 `command_rejected`는 현재 문장 번호와 일치할 때만 실패 결과로 반영하고, 같은 문장의 `voice_sentence_retry`만 허용한다.

시선은 안내 중 받은 점을 보관한 뒤 주 모니터 전체화면의 실제 코 중심 좌표를 물리 픽셀로 보내며, 오차는 서버 결과를 표시한다.

## 통신 확인 방법

사용자가 개발 서버를 실행한 뒤 첫 설정 화면 아래의 **통신 기록**을 펼친다. `/connection-check`에서도 같은 메모리 기록을 볼 수 있다. 최근 150건의 REST·WS 발신/수신/실패를 표시하며 페이지를 새로고침하면 초기화된다. 내부 오류 상세와 바이너리는 기록에서 제외한다.

발신 기록은 브라우저의 전송 성공만 의미하며 BE 처리나 AI 수신 성공을 의미하지 않는다. 예를 들어 `wakeword_enroll_start` 발신 뒤 `wakeword_progress`가 오지 않으면 BE 중계·AI 처리 로그를 대조해야 한다.

명시적 응답을 기다리는 요청은 30초 동안 응답이 없으면 지연 안내를 표시하며, 늦게 도착한 응답도 계속 처리한다. 이 시간은 AI의 녹음 제한이 아니며 서버 작업을 취소하지 않는다. 저장·등록 요청은 자동 재전송하지 않는다. WS 또는 AI 연결 중단 시에도 자동 성공·자동 이어하기를 하지 않는다.

## AI 음성 등록 재확인 (2026-09-10)

확인한 경로는 `S15P21D106/AI`다. 음성 등록 기능은 존재한다.

- `voice_enroll.py`의 `PHRASES`에는 사용자 확정 원문 5개가 들어 있다.
- `record_one()`은 AI에서 마이크 입력을 받아 발화 종료까지 녹음한다.
- `enroll()`은 5개 녹음을 `SpeakerVerifier.enroll()`에 넘긴다.
- `speaker.py`는 화자 특징과 임계값을 `models/speaker.npz`에 저장한다.
- `assistant.py`는 등록된 화자 프로필을 사용한다.

이 기능의 존재와 WS 시작 이벤트 연결은 별도로 확인해야 한다. 현재 확인한 `be_link.py`의 `_on_event()`에는 세션·시선 분기가 있으며, 위 등록 함수를 호출하는 보이스 등록 이벤트 분기는 찾지 못했다. 이는 이 로컬 소스의 확인 결과이며, AI 음성 등록 기능이 없다는 뜻이 아니다. 별도 실행본의 반영 여부는 검증하지 않았다.

## 등록은 진행하되 초기 식별자에 따른 제약

FE는 `voice_reg_start {}`를 보내고, `tempId`가 없는 `voice_sentence {n,total}`와 `voice_progress {n,total}`도 처리한다. 식별자가 없다는 이유로 문장 수집을 중단하지 않는다. 문장은 확정된 5개를 사용한다.

| 상태 | 가능한 동작 | 제한 |
|---|---|---|
| 초기 tempId 미수신 | 문장 표시와 진행 이벤트 수신 | 이 문장 다시·중단 비활성화 |
| sentence/progress/warning/review에서 tempId 수신 | 서버가 준 식별자 보관·재사용 | 작업 중에는 중복 요청 방지 |
| 품질 경고 + tempId 수신 | voice_accept_anyway 전송 | 식별자 없으면 계속 진행 버튼 비활성화 |
| review + tempId + 5문장 진행 수신 | 샘플 재생, voice_commit 전송 | voice_saved 수신 후에만 등록 완료 표시 |
| review에도 tempId 미수신 | 제공된 샘플 재생 | 저장·다시 녹음 비활성화 및 사유 표시 |

초기 재시도·중단을 지원하려면 BE가 첫 `voice_sentence`에 해당 등록의 `tempId`를 제공해야 한다. FE는 임시 번호를 만들거나 빈 번호로 요청하지 않는다. 리뷰에서 번호를 받으면 전체 다시 녹음은 가능하다. 서버가 일단 제공한 번호는 이후 이벤트에서 생략되어도 유지한다.

30초 응답 지연은 실패나 서버 작업 취소로 간주하지 않는다. FE는 기다리면서 후속 이벤트를 처리하며 시작·저장 요청을 자동 재전송하지 않는다.

## 장치 API 기준

`GET /api/devices`는 백엔드 담당자가 제공한 `{mics, cameras}` 계약을 사용한다. 각 장치의 `name`, `id`, 선택적 `isDefault`를 읽고, 설정 저장 시 장치 이름과 ID를 함께 보낸다. 로컬 검색 결과만으로 API가 없다고 판단하지 않는다.

## 사용자 통신 확인 순서

1. BE·AI·FE 실행 후 기본 설정에서 장치를 선택하고 저장한다.
2. 호출어 5회, 명령 5문장을 진행한다.
3. 통신 기록에서 `voice_reg_start` 발신과 `voice_sentence`·`voice_progress` 수신을 확인한다. tempId가 없어도 5문장 수집이 이어져야 한다.
4. tempId 수신 전 재시도·중단이 비활성화되고, 수신 후 활성화되는지 확인한다.
5. `voice_review`의 샘플 확인 후 등록을 누른다. `voice_commit`에 서버가 준 tempId가 포함되는지 확인한다.
6. `voice_saved` 수신 후 마이크 설정 완료 화면으로 이동하는지 확인한다.
7. 시작 이벤트만 있고 응답이 없다면 FE 발신 기록과 BE 중계·AI 수신 로그를 대조한다. 30초 이후에도 도착한 응답은 처리해야 한다.

BE·AI 코드는 수정하지 않았다. 빌드·실행·실제 통신 검증은 사용자가 진행한다.
## 카메라·시선 FE 보완

- 새 시선 설정은 이전 precheck를 재사용하지 않는다. 첫 측정 지점과 위치 확인 응답을 받은 뒤 다음으로 이동한다.
- calib_point가 먼저 도착해도 위치 확인 대기는 별도로 추적한다. precheck가 30초 동안 없으면 지연 안내를 표시하고, 늦게 도착한 응답도 반영한다.
- 위치 확인 화면에서 취소하거나 카메라 설정으로 돌아갈 수 있다. 카메라 설정 복귀 시 calib_cancel을 보내고 설정·장치 목록을 다시 조회한다. 저장 후에는 마이크 등록을 반복하지 않고 시선 설정으로 돌아간다.
- 같은 측정 지점의 좌표는 한 번만 전송해 중복 수집 시작을 방지한다. 전체화면 이탈·크기 변경으로 진행이 중단되어도 BE 연결이 있으면 측정 중단 요청을 보낼 수 있다.
- 결과 수신은 파일 저장 성공을 뜻하지 않는다. calib_commit 이후 calib_saved를 받아야 완료 화면으로 이동하며, 저장 오류는 서버 메시지를 표시한다.

FE에서 해결할 수 없는 사항:

1. AI가 실행 옵션으로 카메라를 여는 로컬 코드에서는 저장된 cameraDeviceId 적용 경로를 확인하지 못했다. FE는 장치 이름·ID를 PUT /api/settings로 보내지만 실제 카메라 전환 성공을 단정하지 않는다.
2. AI는 새 보정 시작마다 calib_precheck를 보내야 한다. FE가 얼굴 인식 성공을 만들거나 이전 값을 재사용해 통과시키지 않는다.
3. 거리·조명의 ok는 현재 AI가 고정으로 보내는 값이다. 화면은 서버 확인값으로 표시하며 FE가 실측하지 않는다.
4. AI의 npz 업로드 실패 후 결과 전송 문제는 AI·BE 보완 대상이다. FE는 calib_saved 이전에 저장 완료를 표시하지 않는다.

빌드와 실행·통신 테스트는 수행하지 않았다. 사용자는 위치 확인 응답 지연, 카메라 변경 후 시선 설정 복귀, 9점 좌표 송신, 저장 오류 및 calib_saved 수신을 확인한다.
