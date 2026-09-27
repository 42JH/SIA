# 브이 → 검지 오인식 재현 및 수정 (2026-09-18)

카메라 촬영 없이 프로젝트의 실제 `gesture_recognizer.task`를 실행해 동일 유형의 오류를 재현했다. 공개 HaGRID 손등 브이 사진을 -30도 회전하고 좌우 반전한 입력에서, VIDEO 모드 45프레임 모두 `Pointing_Up`을 반환했다. 수정 후 같은 입력의 45프레임 모두 `Victory`로 판정됐다. 팀원의 원본 영상/모델 출력은 없으므로 해당 촬영의 정확한 원인까지 단정하지 않는다.

## 확인된 원인

1. **손 모양과 모순되는 모델 분류를 그대로 신뢰했다.** 재현 프레임의 분류 점수는 IMAGE 모드 약 0.723, VIDEO 첫 프레임 약 0.72다. 낮은 신뢰도만 제거하거나 같은 분류가 반복되는지 검사하는 방식으로는 이 사례를 해결하지 못한다. 모델이 반환한 world 좌표에서 검지와 중지는 모두 펴져 있었다. 각 손가락의 MCP→TIP 거리/뼈 길이 합은 각각 약 0.981, 0.986이었다. 즉, 이 재현에서는 손가락 검출 자체보다 최종 제스처 분류가 잘못됐다.
2. **필요한 3D 관절 정보를 버렸다.** 기존 `parse_hands`는 2D 좌표와 제스처 이름/점수만 넘겼고, 분류 결과를 손가락 굽힘과 대조하지 않았다. MediaPipe는 원래 이미지 좌표와 world 좌표를 함께 제공한다. [공식 결과 형식](https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/GestureRecognizerResult)
3. **등록 안내는 최빈 후보가 아니라 먼저 나타난 후보를 선택했다.** `builtin_hits`를 삽입 순서로 순회하며 20% 임계값을 넘는 첫 이름으로 거절했다. 검지가 초반 25%, 브이가 이후 75%인 경우에도 검지와 중복이라고 안내했다. 프레임 비율을 유사도로 표시하는 문제는 앞선 수정에서 별도로 제거했다.

## 적용한 변경

- `AI/gesture_pose.py`: 브이/검지 후보에 한정해 3D 관절의 굽힘, 손목으로부터의 뻗음, 두 손끝 간격을 검증한다. 브이 후보는 엄지도 확인한다. 좌우 손, 위치, 회전, 크기에 의존하는 화면 x/y 비교는 사용하지 않는다. 근거가 명확하면 브이↔검지를 교정하고, 불명확하면 `None`으로 보류한다. `None`이나 다른 제스처를 무조건 브이로 승격하지 않는다.
- `AI/hands.py`: 단일/다중 손 파서를 하나의 경로로 통일해 등록과 실제 실행에 동일한 검증을 적용한다. 원본 라벨/점수, world 좌표, 검증 결과를 보존한다. 교정된 브이에 원래 검지 점수를 붙이지 않도록 교정 후 `score`는 `None`으로 둔다. 사용 통계 큐는 이 필드를 생략한다.
- `AI/gesture_be.py`: 최빈 기본 동작을 선택하고 동률이면 특정 동작을 지목하지 않는다. 손가락 판별이 불명확한 관측이 기존 중복 기준인 20% 이상이고 확정된 기본 동작 중복이 없으면, 커스텀 등록으로 조용히 통과시키지 않고 품질 안내를 한다.
- `AI/gesture_diagnostics.py`: 최종 라벨과 원본 모델 라벨/점수, world 좌표를 함께 저장한다. 기존 좌표/비교 기록도 유지한다.

기존 커스텀 저장 파일과 모델 가중치는 변경하지 않았다. 추가 학습/네트워크 호출/두 번째 모델 추론도 없다. 관절 검증 1,000회 실행의 평균은 약 0.117ms, p95는 약 0.216ms였다. 이는 현재 머신에서 다른 검증과 함께 실행한 값이며 전체 모델 추론 시간은 아니다. [측정값](overhead.json)

## 검증 결과

| 검사 | 수정 전 | 수정 후 |
| --- | --- | --- |
| 재현 사진 VIDEO 45프레임 | 검지 45회 | 브이 45회 |
| 실제 등록 수집→검증 경로 | `similarTo=Pointing_Up` | `similarTo=Victory` |
| 안정화→홀드 실행 판정 | 원본 분류가 검지 후보로 들어감 | 브이 1회, 검지 0회 |
| 초반 검지 25%, 이후 브이 75% 집계 | 삽입 순서 때문에 검지 선택 | 브이 선택 |
| 자동 회귀 검사 | — | 110개 통과, 실패/오류/스킵 0 |

기본 브이는 이미 제공되는 동작이므로 커스텀 등록은 계속 거절하며, **검지 대신 브이와 중복이라고 안내**하는 것이 정상이다. 실제 BE 명령 전송은 하지 않았고 로컬 실행 판정까지만 검증했다.

공개 사진 변형 708건의 결과:

- MediaPipe 공개 사진 4종 × 회전/반전/크기 48가지 = 192건: 기존 분류가 바뀐 사례 없음.
- HaGRID 예제 24종 × 회전/반전 14가지 = 336건: 손등 브이의 검지 오분류 1건을 브이로 교정, 검지와 새끼손가락을 편 rock의 검지 오분류 1건을 보류. 나머지 출력은 동일했다.
- 브이 사진의 가로 압축/회전/반전/축소 스트레스 180건: 기존 브이 판정 46건 중 3건이 보류로 바뀌었다. 불확실한 형태에서 잘못된 확정을 줄이는 대신 일부 브이 검출을 놓칠 수 있는 한계다. 가로 압축은 실제 측면 촬영과 동일하지 않다.

**708건은 변환 이미지 수이며, 독립적인 사람 708명의 정확도 시험이 아니다.** 다른 각도에서 원래 `None`으로 나오던 사례도 모두 해결한 것은 아니다. 손가락 좌표 자체가 가림 때문에 잘못 추정되면 이 보정 역시 정답을 보장하지 못한다. 프런트엔드 소스가 없어 화면의 아이콘/퍼센트 표시까지 검증하지는 않았다.

원시 결과와 재현 정보: [708건 결과 및 VIDEO/등록 결과](evaluation.json), [회귀 검사 목록/결과](tests.json), [실제 모델 좌표 회귀 자료](../../AI/testdata/builtin_finger_poses.json).

## 재실행

저장소 루트에서 공개 자료 다운로드와 평가:

```powershell
.\AI\.venv\Scripts\python.exe AI/evaluate_builtin_finger_pose.py --download --output Docs/gesture-finger-fix-2026-09-18/evaluation.json
```

자료가 `AI/.gesture_research/`에 있으면 `--download` 없이 오프라인 실행할 수 있다. 이 폴더의 공개 이미지와 임시 실험 결과는 Git에서 제외했다. 평가 스크립트는 임시 디렉터리의 가짜 연결 객체로 등록을 검증하며 사용자 템플릿이나 서버에 쓰지 않는다.

핵심 회귀 검사 (`AI` 폴더에서):

```powershell
.\.venv\Scripts\python.exe -m unittest test_gesture_finger_pose test_gesture_builtin_feedback test_custom_motion test_gesture_runtime test_gesture_handedness test_gesture_take_consistency test_gesture_frame_bounds test_gesture_motion_features test_gesture_motion_boundaries test_gesture_occlusion test_gesture_registration_matrix test_gesture_preview
```

검증 환경: MediaPipe `1.0.1`; 모델 SHA-256 `97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482`. 각 공개 이미지의 URL/SHA-256은 `evaluation.json`에 기록했다. 예제 출처: [HaGRID 제공자 저장소](https://github.com/hukenovs/hagrid), [MediaPipe 브이 예제](https://storage.googleapis.com/mediapipe-assets/victory.jpg).
