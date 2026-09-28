# 스와이프 방향 잠금 해제 조건 수정 — 복귀 동작이 반대 방향으로 오발동하는 문제

- 작성일: 2026-09-28
- 기준: `origin/dev/ai`(`a25285e`, `feature/swipe-progress-static-guard` 병합 이후). 작업 브랜치: `fix/swipe-direction-unlock-hold`
- 상태: 재생/유닛 테스트로 검증 완료, 기존 테스트 1건 수정 포함. 실카메라 검증은 아직 안 함.

## 1. 문제

`SwipeDetector`는 스와이프 발동 뒤 반대 방향으로 복귀하는 동작을 새 명령으로 오인하지 않도록 `_direction_lock`을 건다. 잠금은 "시작 위치에서 0.5초 정지"하면 풀리도록 클래스 설명에 문서화돼 있는데, 실제 코드는 그 문턱으로 `unlock_hold_s`(0.5s)가 아니라 `rearm_hold_s`(0.15s)를 쓰고 있었다. 그 결과 다음 동작을 위해 손을 되돌리다 0.15초만 잠깐 멈춰도 잠금이 풀려, 그 복귀 동작 자체가 반대 방향 스와이프로 오발동할 수 있었다.

## 2. 수정

```python
# 수정 전
elif t - self._lock_still_since >= self.rearm_hold_s:
    self._direction_lock = None

# 수정 후
elif t - self._lock_still_since >= self.unlock_hold_s:
    self._direction_lock = None
```

## 3. 기존 테스트와의 충돌 — 원인 확인 후 테스트 쪽을 수정

`test_core.py`의 `test_swipe_detector`가 실패했다. 방향 전환을 확인하는 부분이 새 위치에서 15프레임(0.5초) 정지를 주는데, **그중 첫 프레임은 직전 위치에서 이동한 프레임이라 "정지 시작"으로 잡히지 않아 실제로 정지로 인정되는 시간은 14프레임(≈0.467초)뿐**이었다. 예전엔 버그로 `rearm_hold_s`(0.15s)를 썼기 때문에 0.467초로도 통과했을 뿐, 클래스가 스스로 문서화한 0.5초 기준으로는 원래도 부족한 값이었다.

재현으로 직접 확인: 15프레임 그대로 두면 방향 잠금이 안 풀려 반대 방향 스와이프가 나가지 않고, 18프레임(≈0.567초)으로 늘리면 의도대로 통과한다. `test_core.py`의 두 곳(`feed`, `guarded_feed`)을 15→18로 수정했다 — 검증 내용(방향 전환이 되는지) 자체는 그대로 유지했다.

## 4. 검증

- `test_core.test_swipe_detector` 단독 재확인: 통과
- `unittest discover`: 223개 통과
- bare 함수 스타일 5개 파일(`test_core`/`test_mic_sync`/`test_usage_events`/`test_voice_sync`/`test_wake_template`, `unittest.TestCase` 미상속이라 discover가 못 잡음 — 직접 호출로 확인): 135개 통과
- 합계 358개 전부 통과
- 실카메라 검증은 아직 안 함

## 5. 참고

- 코드: `AI/hands.py`(`SwipeDetector`의 방향 잠금 해제 조건)
- 테스트: `AI/test_core.py`(`test_swipe_detector`)
- 이 문제와 아래 발견 경위: `Docs/gesture-study/full-audit-20260928/report.md`(별도 워크트리 감사)의 "로컬: ... 핵심 함수 5개 중 4개 통과·1개 실패" 기록에서 처음 확인됨
