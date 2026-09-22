package com.sia.assistant.gestureexec;

import com.sia.assistant.context.ContextService;
import com.sia.assistant.mcp.Caller;
import com.sia.assistant.mcp.ToolCatalog;
import com.sia.assistant.mcp.ToolInvoker;
import com.sia.assistant.mcp.ToolResult;
import com.sia.assistant.session.SessionService;
import com.sia.assistant.settings.GestureService;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import jakarta.annotation.PreDestroy;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;

/**
 * 제스처 매크로 실행부 — 실행자는 BE 다 (다이어그램 01).
 * WS 스레드에서 돌리지 않는다: 제스처는 순차 실행이 의미라 단일 스레드 Executor 를 쓴다.
 */
@Component
public class GestureExecutor {

    private static final Logger log = LoggerFactory.getLogger(GestureExecutor.class);

    private final GestureService gestureService;
    private final ContextService contextService;
    private final ToolInvoker toolInvoker;
    private final SessionService sessionService;
    private final AgentHub agentHub;
    private final FeHub feHub;

    private final ExecutorService executor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "gesture-exec");
        t.setDaemon(true);
        return t;
    });

    public GestureExecutor(GestureService gestureService, ContextService contextService,
                           ToolInvoker toolInvoker, SessionService sessionService,
                           AgentHub agentHub, FeHub feHub) {
        this.gestureService = gestureService;
        this.contextService = contextService;
        this.toolInvoker = toolInvoker;
        this.sessionService = sessionService;
        this.agentHub = agentHub;
        this.feHub = feHub;
    }

    /** AI 의 gesture_exec {name, hwnd?, context?} 처리 — 즉시 리턴하고 자체 스레드에서 돈다. */
    public void execute(JsonNode data) {
        final String name = data.path("name").asText("");
        final Long hwnd = data.hasNonNull("hwnd") ? data.path("hwnd").asLong() : null;
        final String context = data.hasNonNull("context") ? data.path("context").asText() : null;
        executor.submit(() -> run(name, hwnd, context));
    }

    private void run(String name, Long hwnd, String context) {
        List<Map<String, Object>> stepResults = new ArrayList<>();
        try {
            List<String> contextChain = context != null ? List.of(context) : contextService.chainFor(hwnd);
            Optional<GestureService.GestureDef> found = gestureService.find(name, contextChain);
            if (found.isEmpty()) {
                sendResult(name, false, "등록되지 않은 제스처예요", stepResults);
                return;
            }
            GestureService.GestureDef def = found.get();
            // 꺼진 제스처는 AI 감지에서 빠지는 게 정상이지만(gesture_toggled), 경합·재연결 직후를 대비해
            // BE 도 실행을 막는다 — 켜기/끄기의 최종 집행 지점은 여기다.
            if (!def.enabled()) {
                sendResult(name, false, "꺼져 있는 제스처예요. 제스처 목록에서 켠 뒤 사용할 수 있습니다", stepResults);
                return;
            }
            // 기본 제공 제스처는 기능이 빈칸으로 태어난다 (DefaultGestures) — 빈 매크로를 그대로 돌리면
            // 스텝 0개짜리 성공 보고가 나가 "실행했다는데 아무 일도 안 일어나는" 상태가 된다.
            if (def.steps().isEmpty()) {
                sendResult(name, false, "아직 기능이 지정되지 않은 제스처예요. 제스처 목록에서 기능을 지정해 주세요",
                        stepResults);
                return;
            }
            // 세션 게이트는 매크로 단위다 — S 도구가 하나라도 있으면 첫 스텝 전에 확인한다 (프로토콜 §8.6).
            // 스텝마다 검사하면 앞 스텝이 이미 실행된 뒤 중간에서 막혀 반쯤 실행된 매크로가 남는다.
            if (needsSession(def) && sessionService.activeOrNull() == null) {
                sendResult(name, false, "세션이 활성화되지 않았습니다", stepResults);
                return;
            }
            // 매크로가 유효하다고 판정된 자리에서 세션을 갱신한다 — 제스처를 쓰는 동안은 세션이 살아 있어야 한다.
            // ★ 첫 스텝 전이어야 한다: 스텝 뒤로 미루면 실행 도중 마감이 지나 뒤 스텝이 세션 게이트에 걸린다.
            // 활성 세션이 없으면 건너뛴다 — S 도구가 없는 매크로는 세션 없이도 실행되는데 renew 는 던진다.
            if (sessionService.activeOrNull() != null) {
                sessionService.renew(null);
            }

            boolean ok = true;
            String message = null;
            for (GestureService.Step step : def.steps()) {
                if (step.delayMs() != null && step.delayMs() > 0) {
                    try {
                        Thread.sleep(step.delayMs());
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                        ok = false;
                        message = "제스처 실행이 중단되었습니다";
                        break;
                    }
                }
                ToolResult r = toolInvoker.invoke(step.tool(), step.args(), Caller.GESTURE);
                stepResults.add(stepEntry(step.tool(), r));
                if (!r.ok()) {
                    ok = false;
                    message = r.message() != null ? r.message() : "제스처 실행이 중단되었습니다";
                    break; // ok 가 아니면 남은 스텝은 실행하지 않는다
                }
            }
            if (ok && message == null) {
                message = def.label() != null
                        ? "'" + def.label() + "' 동작을 실행했습니다"
                        : "제스처 동작을 실행했습니다";
            }
            sendResult(name, ok, message, stepResults);
        } catch (Exception e) {
            log.warn("제스처 {} 실행 실패", name, e);
            sendResult(name, false, "제스처 실행 중 오류가 발생했습니다", stepResults);
        }
    }

    /** 매크로에 S 도구가 하나라도 있는가 — 카탈로그에 없는 이름은 어차피 스텝에서 failed 로 걸린다. */
    private static boolean needsSession(GestureService.GestureDef def) {
        return def.steps().stream().anyMatch(s -> {
            ToolCatalog.ToolSpec spec = ToolCatalog.spec(s.tool());
            return spec != null && spec.sessionRequired();
        });
    }

    private static Map<String, Object> stepEntry(String tool, ToolResult r) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("tool", tool);
        entry.put("outcome", outcomeOf(r));
        if (r.message() != null) {
            entry.put("message", r.message());
        }
        return entry;
    }

    /** ToolResult → tool_call outcome 어휘로 환원 (AI 가 같은 어휘로 읽는다). */
    private static String outcomeOf(ToolResult r) {
        if (r.ok()) {
            return "EXECUTED";
        }
        // CONFIRM_PENDING 은 더 이상 나오지 않는다 — BE 확인 게이트가 없고,
        // 애초에 C 도구는 제스처 매크로에 넣을 수 없다(GestureService.validateSteps).
        // INVALID_REQUEST(인자 형식 오류)도 정책 차단이 아니라 실패다 — ToolGate 의 기록과 어휘를 맞춘다.
        return "FAILED".equals(r.code()) || "INVALID_REQUEST".equals(r.code()) ? "FAILED" : "BLOCKED";
    }

    private void sendResult(String name, boolean ok, String message, List<Map<String, Object>> steps) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("name", name);
        body.put("ok", ok);
        body.put("message", message);
        body.put("steps", steps);
        agentHub.send("gesture_result", body);
        feHub.send("gesture_result", body);
    }

    @PreDestroy
    void shutdown() {
        executor.shutdownNow();
    }
}
