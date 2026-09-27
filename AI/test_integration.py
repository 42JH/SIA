# -*- coding: utf-8 -*-
"""AI↔BE 연동 라이브 테스트 — BE 서버가 떠 있을 때만 의미 있다.

배포되는 AgentLink(be_link.py)를 그대로 태워, PROTOCOL 계약의 핵심 지점을
순서대로 확인한다. 부작용 없는 도구(session.extend)만 써서 안전하다.

  1) runtime.json 로드          — BE 접속정보
  2) WS /ws/agent 연결          — AgentLink.connected
  3) MCP context.get            — 세션 불요 읽기 도구 왕복
  4) MCP tools/list             — 카탈로그 수
  5) S 도구 게이트(세션 전)     — session.extend → SESSION_REQUIRED 여야 정상
  6) 세션 개시(WS session_open) — renew(opening=True) → session_state(ACTIVE, deadlineMs) 캐시
  7) S 도구(세션 후)            — session.extend → ok  (★ WS로 연 세션을 MCP가 인식하는지 = 교차상관 핵심)
  8) 정리                        — session_end

실행: python test_integration.py   (BE를 먼저 :61015 에 띄운 뒤)
BE 미기동이면 2)에서 멈추고 "BE 안 떠 있음"을 알린다.
"""
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")  # cp949 콘솔에서 em-dash 등 출력 크래시 방지
except Exception:
    pass

from be_link import AgentLink, read_runtime

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def wait_until(pred, timeout, step=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return False


def main():
    print("=== AI↔BE 연동 테스트 ===")
    rt = read_runtime()
    if not check("1) runtime.json 로드", bool(rt),
                 f"port={rt.get('port')} pid={rt.get('pid')}" if rt else "없음 — %APPDATA%/SIA/runtime.json"):
        return _summary()

    link = AgentLink()
    if not check("2) WS /ws/agent 연결", wait_until(lambda: link.connected, 5.0),
                 "connected" if link.connected else "미연결 — BE가 :{}에 안 떠 있음".format(rt.get("port"))):
        link.close()
        return _summary()

    ok, payload = link.call("context.get")
    fg = payload.get("foreground") if isinstance(payload, dict) else None
    check("3) MCP context.get (세션 불요)", ok is True,
          f"foreground={ (fg or {}).get('title','?') if isinstance(fg,dict) else fg }")

    # 4) 카탈로그 수 — link 내부 McpClient 재사용(이미 connect됨)
    try:
        tools = link.mcp.tools() if link.mcp else []
        check("4) MCP tools/list", len(tools) > 0, f"{len(tools)}개")
    except Exception as e:
        check("4) MCP tools/list", False, str(e))

    # 5) 세션 전 S 도구 게이트 — SESSION_REQUIRED 가 '정상'
    ok, payload = link.call("session.extend")
    code = payload.get("code") if isinstance(payload, dict) else None
    check("5) S도구 게이트(세션 전) session.extend→SESSION_REQUIRED",
          ok is False and code == "SESSION_REQUIRED", f"ok={ok} code={code}")

    # 6) 세션 개시: WS session_open → BE가 session_state(ACTIVE, deadlineMs) push
    link.renew(opening=True)
    opened = wait_until(lambda: link.session_until_mono > time.monotonic(), 4.0)
    left = max(0.0, link.session_until_mono - time.monotonic())
    check("6) 세션 개시(WS session_open→session_state)", opened,
          f"남은 {left:.0f}s, sessionId={link.be_session_id}")

    # 7) ★ 세션 후 S 도구 — WS로 연 세션을 MCP 호출이 인식하는가(교차상관)
    ok, payload = link.call("session.extend")
    check("7) S도구(세션 후) session.extend→ok  [교차상관]", ok is True,
          f"payload={payload}")

    # 8) 정리
    link.end()
    link.close()
    check("8) 세션 종료(session_end) 송신", True)
    return _summary()


def _summary():
    p = sum(1 for r in results if r)
    print(f"\n결과: {p}/{len(results)} PASS")
    return 0 if p == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
