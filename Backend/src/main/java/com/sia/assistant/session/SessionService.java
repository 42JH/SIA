package com.sia.assistant.session;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.BlockedException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.common.Times;
import com.sia.assistant.settings.SettingsService;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import jakarta.annotation.PreDestroy;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.core.annotation.Order;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * 세션 타이머의 소유자 = BE. 만료는 지연 평가가 아니라 예약된 end(EXPIRED)가 능동 push 한다.
 * 모든 상태 변화는 feHub·agentHub 양쪽에 "session_state" 로 통지한다.
 */
@Service
public class SessionService {

    public record Active(long id, String startedAt, long deadlineMs) {
    }

    private static final Logger log = LoggerFactory.getLogger(SessionService.class);
    private static final Set<String> END_REASONS = Set.of("EXPIRED", "STOPPED", "WATCHDOG", "SHUTDOWN");

    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final SettingsService settingsService;
    private final FeHub feHub;
    private final AgentHub agentHub;

    // 만료 예약의 소유자는 이 서비스 하나뿐이라 단일 스레드면 충분하다
    private final ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
        Thread t = new Thread(r, "session-expiry");
        t.setDaemon(true);
        return t;
    });

    private Active active;
    private ScheduledFuture<?> expiryTask;
    // 갱신·종료 직후 이미 발화된 낡은 만료 예약이 새 세션을 닫지 못하도록 세대 번호로 무효화한다
    private long generation;

    public SessionService(JdbcTemplate jdbc, PlatformTransactionManager txManager,
                          SettingsService settingsService, FeHub feHub, AgentHub agentHub) {
        this.jdbc = jdbc;
        this.tx = new TransactionTemplate(txManager);
        this.settingsService = settingsService;
        this.feHub = feHub;
        this.agentHub = agentHub;
    }

    public synchronized Map<String, Object> open(String trigger) {
        if (!"WAKEWORD".equals(trigger) && !"UI".equals(trigger)) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "세션 트리거는 WAKEWORD 또는 UI 만 허용됩니다");
        }
        if (active != null) {
            // 이전 세션이 정상 종료되지 못한 채 새 개시가 온 것 — WATCHDOG 으로 닫고 새로 발급한다
            end(active.id(), "WATCHDOG");
        }
        String startedAt = Times.now();
        // AUTOINCREMENT id 회수는 INSERT 와 같은 커넥션이어야 해서 한 트랜잭션으로 묶는다
        Long id = tx.execute(status -> {
            jdbc.update("INSERT INTO session (started_at) VALUES (?)", startedAt);
            return jdbc.queryForObject("SELECT last_insert_rowid()", Long.class);
        });
        if (id == null) {
            throw new ApiException(ErrorCode.INTERNAL_ERROR, "세션을 생성하지 못했습니다");
        }
        int seconds = settingsService.peekSessionSeconds();
        long deadlineMs = System.currentTimeMillis() + seconds * 1000L;
        active = new Active(id, startedAt, deadlineMs);
        scheduleExpiry(id, deadlineMs);

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("state", "ACTIVE");
        payload.put("sessionId", id);
        payload.put("deadlineMs", deadlineMs);
        payload.put("remainingSec", seconds);
        push(payload);
        return payload;
    }

    /**
     * 호출어 감지 시의 세션 개시 — ★ 세션의 시작 시각은 BE 가 이 이벤트를 받은 순간이다.
     * AI 가 보낸 시각을 믿지 않는다(tool_call.ts 와 같은 원칙).
     * 이미 활성이면 아무것도 하지 않고 현재 상태만 돌려준다:
     *   open() 을 다시 부르면 WATCHDOG 으로 닫고 새로 발급해 세션이 끊기고,
     *   renew 로 바꾸면 오인식 호출어가 세션을 연장해 "갱신은 유효 명령 판정 후" 규칙을 어긴다.
     * 상태가 바뀌지 않았으므로 통지(push)도 하지 않는다.
     */
    public synchronized Map<String, Object> openOnWakeword() {
        if (active == null) {
            return open("WAKEWORD");
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("state", "ACTIVE");
        payload.put("sessionId", active.id());
        payload.put("deadlineMs", active.deadlineMs());
        payload.put("remainingSec", remainingSec());
        return payload;
    }

    public synchronized Map<String, Object> renew(Long sessionIdOrNull) {
        if (active == null) {
            throw new BlockedException(ErrorCode.SESSION_REQUIRED, "세션이 활성화되지 않았습니다");
        }
        if (sessionIdOrNull != null && sessionIdOrNull.longValue() != active.id()) {
            throw new BlockedException(ErrorCode.SESSION_REQUIRED, "요청한 세션은 이미 종료되었습니다");
        }
        int seconds = settingsService.peekSessionSeconds();
        long deadlineMs = System.currentTimeMillis() + seconds * 1000L;
        active = new Active(active.id(), active.startedAt(), deadlineMs);
        scheduleExpiry(active.id(), deadlineMs);

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("state", "ACTIVE");
        payload.put("sessionId", active.id());
        payload.put("deadlineMs", deadlineMs);
        payload.put("remainingSec", seconds);
        push(payload);
        return payload;
    }

    public synchronized Map<String, Object> end(Long sessionId, String reason) {
        if (reason == null || !END_REASONS.contains(reason)) {
            throw new ApiException(ErrorCode.INVALID_REQUEST,
                    "세션 종료 사유는 EXPIRED, STOPPED, WATCHDOG, SHUTDOWN 만 허용됩니다");
        }
        if (sessionId != null) {
            jdbc.update("UPDATE session SET ended_at = ?, end_reason = ? WHERE id = ? AND ended_at IS NULL",
                    Times.now(), reason, sessionId);
        }
        boolean endsActive = active != null && (sessionId == null || sessionId.longValue() == active.id());
        if (endsActive) {
            active = null;
            generation++;
            cancelExpiry();
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("state", "PASSIVE");
        payload.put("reason", reason);
        if (endsActive || active == null) {
            push(payload);
        } else {
            // 활성이 아닌 낡은 세션 id 의 종료 요청 — 진행 중인 세션을 PASSIVE 로 오인시키면 안 된다
            log.warn("활성 세션({})이 아닌 세션({}) 종료 요청 — 상태 통지는 생략합니다", active.id(), sessionId);
        }
        return payload;
    }

    public synchronized Active activeOrNull() {
        return active;
    }

    public synchronized long requireActive() {
        if (active == null) {
            throw new BlockedException(ErrorCode.SESSION_REQUIRED, "세션이 활성화되지 않았습니다");
        }
        return active.id();
    }

    public synchronized int remainingSec() {
        if (active == null) {
            return 0;
        }
        long ms = active.deadlineMs() - System.currentTimeMillis();
        // 남아 있는데 0초로 보이면 안 되므로 올림한다
        return ms <= 0 ? 0 : (int) ((ms + 999) / 1000);
    }

    /** 전체 삭제(wipe) 전용 — DB 는 손대지 않고 메모리 상태·예약만 비운다. */
    public synchronized void reset() {
        boolean wasActive = active != null;
        active = null;
        generation++;
        cancelExpiry();
        if (wasActive) {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("state", "PASSIVE");
            payload.put("reason", "STOPPED");
            push(payload);
        }
    }

    @EventListener(ApplicationReadyEvent.class)
    @Order(10)
    public void closeOrphansOnStartup() {
        int n = jdbc.update("UPDATE session SET ended_at = ?, end_reason = 'SHUTDOWN' WHERE ended_at IS NULL",
                Times.now());
        if (n > 0) {
            log.info("미종료 세션 {}건을 SHUTDOWN 으로 정리했습니다", n);
        }
    }

    private void scheduleExpiry(long sessionId, long deadlineMs) {
        cancelExpiry();
        final long gen = ++generation;
        long delay = Math.max(0, deadlineMs - System.currentTimeMillis());
        expiryTask = scheduler.schedule(() -> onExpiry(sessionId, gen), delay, TimeUnit.MILLISECONDS);
    }

    private synchronized void onExpiry(long sessionId, long gen) {
        // cancel 과 발화가 경합했을 수 있다 — 세대가 다르면 이미 갱신·종료된 예약이다
        if (gen != generation || active == null || active.id() != sessionId) {
            return;
        }
        end(sessionId, "EXPIRED");
    }

    private void cancelExpiry() {
        if (expiryTask != null) {
            expiryTask.cancel(false);
            expiryTask = null;
        }
    }

    private void push(Map<String, Object> payload) {
        feHub.send("session_state", payload);
        agentHub.send("session_state", payload);
    }

    @PreDestroy
    void shutdown() {
        scheduler.shutdownNow();
    }
}
