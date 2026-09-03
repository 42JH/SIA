package com.sia.assistant.logging;

import com.sia.assistant.common.Times;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.core.annotation.Order;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * 보존 기간이 지난 사용 기록 정리 — 기동 1회 + 매일 04:00.
 * 기준 시각은 Times.daysAgo(RETENTION_DAYS) 바인딩 (SQL 의 datetime('now') 금지).
 *
 * <p>400일인 이유: 대시보드의 가장 긴 축이 12개월인데 월 버킷 12개를 채우려면 11개월 전 1일까지
 * 필요하다 — 365 로는 달 길이에 따라 가장 오래된 버킷이 잘린다. 여유를 둔 값이다.
 * 덕분에 집계 테이블·롤업 배치가 통째로 필요 없다(BLUEPRINT.md §6).
 *
 * <p>하루치씩 지워져 해제 페이지를 새 행이 재사용하므로 VACUUM 을 따로 걸지 않는다.
 *
 * <p>★ 첫 400일 동안 이 잡은 아무것도 지우지 않는다 — 삭제 경로가 한 번도 실행되지 않은 채
 * 굴러간다. 그래서 컷오프를 받는 {@link #purgeBefore(String)} 를 열어 두고 테스트에서 주입한다.
 */
@Component
public class RetentionJob {

    private static final Logger log = LoggerFactory.getLogger(RetentionJob.class);
    static final int RETENTION_DAYS = 400;

    private final JdbcTemplate jdbc;

    public RetentionJob(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @EventListener(ApplicationReadyEvent.class)
    @Order(20)
    public void onStartup() {
        purge();
    }

    @Scheduled(cron = "0 0 4 * * *")
    public void daily() {
        purge();
    }

    void purge() {
        purgeBefore(Times.daysAgo(RETENTION_DAYS));
    }

    /** 컷오프를 받는 실제 구현 — 테스트가 400일을 기다리지 않고 삭제 경로를 검증할 수 있게 연다. */
    void purgeBefore(String cutoff) {
        try {
            int events = jdbc.update("DELETE FROM usage_event WHERE received_at < ?", cutoff);
            int calls = jdbc.update("DELETE FROM tool_call WHERE ts < ?", cutoff);
            // 진행 중 세션은 남긴다 (기동 직후 SHUTDOWN 정리가 선행되므로 사실상 없다)
            int sessions = jdbc.update(
                    "DELETE FROM session WHERE started_at < ? AND ended_at IS NOT NULL", cutoff);
            if (events + calls + sessions > 0) {
                log.info("보존 기간({}) 정리 — usage_event {}건, tool_call {}건, session {}건 삭제",
                        cutoff, events, calls, sessions);
            }
        } catch (Exception e) {
            log.error("보존 기간 정리 실패", e);
        }
    }
}
