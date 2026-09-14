-- 제스처 형태 축 — 한손/양손(hands) · 정적/동적(motion).
-- AI 인식 파이프라인이 이 두 축으로 매처를 나눈다(AI 팀 요청): hands 는 랜드마크 배열 모양,
-- motion 은 단일 프레임 비교 vs 시퀀스 정합을 정한다.
--
-- kind 는 건드리지 않는다. kind 는 모달리티 축(HAND | FACE)이자 UNIQUE (kind, context, name) 의
-- 일부여서, 여기에 형태를 접으면 같은 이름이 형태별로 중복 등록될 수 있다.
--
-- SQLite 의 ALTER TABLE ... ADD COLUMN 은 CHECK 를 받지 않는다 — 값 검증은 GestureService 가 한다.
ALTER TABLE gesture ADD COLUMN hands  INTEGER;  -- 1 | 2. FACE 는 NULL
ALTER TABLE gesture ADD COLUMN motion TEXT;     -- 'STATIC' | 'DYNAMIC'. FACE 는 NULL

-- 기존 DB backfill: canned 시드(MediaPipe 기본 제스처)는 전부 한손 정적이고, FACE 2행은 NULL 로 남긴다.
-- 새 DB 에서는 gesture 가 비어 있어 no-op 이다 — 시드는 DefaultMappings(Java)가 두 값을 직접 넣는다.
UPDATE gesture SET hands = 1, motion = 'STATIC' WHERE kind = 'HAND';
