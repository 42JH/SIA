-- ============================================================================
-- V2__calib_grade.sql
--
-- 와이어프레임 시선 섹션 개정 (2026-09-07) — 오차 판정의 소유가 BE → AI 서버로 넘어갔다.
--   * 결과 화면이 "평균 오차 38px (기준 50px 이하)" 대신 "오차 범위: 양호"를,
--     보정 목록이 "상태 : 우수/양호/나쁨"을 보여준다. 등급이 3단계라 단일 threshold 로는
--     만들 수 없으므로 판정 자체를 AI 가 주고 BE 는 받아 적는다
--     (BE 의 CalibProfileService.THRESHOLD_PX 상수는 폐기했다).
--
-- V1 은 그대로 둔다 (배포된 DB 의 Flyway 체크섬을 깨지 않는다). 그래서 V1 의 두 주석은
-- 지금 계약과 다르게 남아 있다 — 정의는 이 파일과 ERD 문서다:
--   * avg_error_px "기준 50px 이하 = 통과" → 통과 기준은 이제 grade 이고 AI 가 판정한다.
--   * points_json  "[{n,x,y,gx,gy}]"      → [{n,dx,dy}] 다. 목표점을 원점으로 둔 오차
--                                            벡터라 결과 화면이 중심점 하나에 9개를 겹쳐 찍는다.
--                                            컬럼 타입은 그대로 TEXT — 담기는 JSON 모양만 바뀐다.
-- ============================================================================

-- 오차 등급 — AI 가 calib_result 로 보낸 값을 그대로 적는다. 보정 목록의 "상태" 칸.
-- SQLite 의 ADD COLUMN 은 CHECK 은 허용한다 (UNIQUE·PRIMARY KEY 는 불가).
-- 기존 행은 NULL 로 남는다 — V2 이전에 만든 프로필은 등급을 모른다 (재보정하면 채워진다).
ALTER TABLE calib_profile
    ADD COLUMN grade TEXT CHECK (grade IS NULL OR grade IN ('excellent', 'good', 'poor'));
