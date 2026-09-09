package com.sia.assistant.mcp;

/**
 * tool_call.caller — 이 제품이 실제로 어떻게 쓰이는지(음성 대 제스처 비율)를 아는 유일한 근거.
 *
 * <p>{@code UI} 는 WebUI 발 도구 호출을 위한 예약값이고 <b>지금은 어떤 경로도 만들지 않는다</b> —
 * 확인 게이트를 WebUI 버튼으로 승인해도 보류됐던 <i>원래</i> caller 로 기록되기 때문이다
 * (WebUI 확인 버튼). 그 경로는 사라졌지만 DB CHECK(V1)·이 enum·테스트에 남아 있으므로 지우지 말 것.
 */
public enum Caller {
    LLM, GESTURE, UI
}
