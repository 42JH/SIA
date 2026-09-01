package com.sia.assistant.mcp;

/** MCP 요청 헤더 X-Caller → ThreadLocal. CallerHeaderFilter 가 채우고 지운다. */
public final class CallerContext {

    private static final ThreadLocal<Caller> CURRENT = ThreadLocal.withInitial(() -> Caller.LLM);

    private CallerContext() {
    }

    public static Caller get() {
        return CURRENT.get();
    }

    public static void set(Caller caller) {
        CURRENT.set(caller);
    }

    public static void clear() {
        CURRENT.remove();
    }
}
