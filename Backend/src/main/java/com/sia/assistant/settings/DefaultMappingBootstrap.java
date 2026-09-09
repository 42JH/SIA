package com.sia.assistant.settings;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.core.annotation.Order;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * 첫 기동에 기본 제스처 매핑을 넣는다 — gesture 테이블이 비어 있을 때만.
 * @Order(5): ToolCatalogSync(0) 가 tool 행을 만든 뒤여야 gesture_step.tool_name FK 가 선다.
 * 사용자가 매핑을 전부 지운 뒤 재기동하면 기본 매핑이 되살아난다 — 전체 삭제(WipeService)와
 * 같은 복원 규칙이다.
 */
@Component
public class DefaultMappingBootstrap {

    private static final Logger log = LoggerFactory.getLogger(DefaultMappingBootstrap.class);

    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;

    public DefaultMappingBootstrap(JdbcTemplate jdbc, PlatformTransactionManager txManager) {
        this.jdbc = jdbc;
        this.tx = new TransactionTemplate(txManager);
    }

    @EventListener(ApplicationReadyEvent.class)
    @Order(5)
    public void seedIfEmpty() {
        Integer count = jdbc.queryForObject("SELECT COUNT(*) FROM gesture", Integer.class);
        if (count != null && count > 0) {
            return;
        }
        int seeded = tx.execute(status -> DefaultMappings.seedInto(jdbc));
        log.info("gesture 테이블이 비어 있어 기본 매핑 {}건을 넣었습니다", seeded);
    }
}
