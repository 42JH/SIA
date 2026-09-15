# 기본 제공 제스처 예시 미리보기

기본 제공 제스처 9종의 목록·상세에 뜨는 그림이다. 여기 둔 파일은 jar 에 함께 실려
`GET /api/gestures/{id}/video` 로 나간다 (`DefaultGestureImages`). 커스텀 제스처의 미리보기는
사용자가 등록 때 찍은 보관본(`%APPDATA%/SIA/gestures/`)이고, 이쪽은 촬영 단계가 없는 기본 제공 몫이다.

## 파일 이름

`{name}.{확장자}` — `name` 은 `DefaultGestures` 카탈로그의 이름 그대로이고 **대소문자를 구분한다**.
확장자는 `motion` 이 정한다(`RegistrationMedia`): FE 가 `motion` 으로 `<img>` / `<video>` 를 고르기 때문이다.

| 파일명 | motion | 태그 |
|---|---|---|
| `Closed_Fist.jpg` | STATIC | `<img>` |
| `Open_Palm.jpg` | STATIC | `<img>` |
| `Pointing_Up.jpg` | STATIC | `<img>` |
| `Thumb_Down.jpg` | STATIC | `<img>` |
| `Thumb_Up.jpg` | STATIC | `<img>` |
| `Victory.jpg` | STATIC | `<img>` |
| `ILoveYou.jpg` | STATIC | `<img>` |
| `Swipe_Left.webm` | DYNAMIC | `<video>` |
| `Swipe_Right.webm` | DYNAMIC | `<video>` |

## 규칙

- 없는 파일은 없는 대로 둔다 — 그 제스처만 `videoUrl: null` 이고 `/video` 는 404 다. 나머지는 그대로 뜨므로
  9장을 한꺼번에 준비하지 않아도 되고, 넣은 것부터 목록에 보인다.
- 확장자를 규칙과 다르게 넣으면(정적인데 `.webm`) 찾지 못한다 — 태그가 어긋난 채 깨져 보이지 않도록
  일부러 한쪽만 본다. 넣지 않은 것과 같은 상태가 된다.
- 목록 썸네일 크기다. 가로 512px 안팎, 한 장 200KB 이하를 권한다 (9장이 그대로 jar 에 들어간다).
  스와이프 2종은 손이 좌/우로 지나가는 1~2초 webm 이면 충분하다.
- 파일을 넣거나 바꾸면 재기동해야 반영된다 (클래스패스 리소스).
- 사용자 카메라 촬영본이 아니라 BE 가 싣는 배포물이다 — 커스텀 보관본과 달리 반출 금지 대상이 아니다.
