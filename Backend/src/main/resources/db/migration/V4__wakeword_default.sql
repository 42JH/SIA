-- ============================================================================
-- V4__wakeword_default.sql
--
-- 호출어(settings_json 의 wakeWord) 초기값 "시아" → "시아야" (2026-09-14).
--   온보딩에서 실제로 5회 녹음하는 문장은 "시아야" 인데 설정 초기값만 "시아" 여서
--   설정 화면과 녹음 문장이 서로 다른 말을 하고 있었다. 초기값을 녹음 문장에 맞춘다.
--
-- V1 은 그대로 둔다 (배포된 DB 의 Flyway 체크섬을 깨지 않는다). 그래서 V1 의 INSERT 와
-- 그 위 주석("seed/default-settings.json 과 동일 값이어야 한다")은 지금 값과 다르게 남아 있다 —
-- 초기값의 정의는 이 파일과 resources/seed/default-settings.json 이다.
--
-- ★ 한 번이라도 저장된 설정은 건드리지 않는다. settings_version 은 V1 이 1 로 넣고
--   PUT /api/settings · 시드 복원이 반드시 올리므로, version = 1 이 "사용자가 손대지 않은
--   초기값" 이라는 뜻이다. 값까지 함께 확인해 사용자가 고른 호출어를 덮는 일을 막는다.
--
-- settings_version · settings_updated_at 은 올리지 않는다. 저장한 적 없는 행만 고치는 것이라
-- 사용자에게는 여전히 초기 상태이고, 에이전트는 접속할 때마다 recognition_start 로 현재 문서를
-- 통째로 받으므로 버전을 올리지 않아도 최신 값을 본다.
-- ============================================================================
UPDATE app_settings
   SET settings_json = json_set(settings_json, '$.wakeWord', '시아야')
 WHERE id = 1
   AND settings_version = 1
   AND json_extract(settings_json, '$.wakeWord') = '시아';
