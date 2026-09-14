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
 * 기동마다 기본 제공 제스처 9종이 제자리에 있는지 확인한다 — 없는 이름만 넣고 표시 문구를 맞춘다.
 * ★"gesture 테이블이 비어 있을 때만" 이 아니다: 커스텀 제스처가 한 건이라도 있으면 표가 비지 않아
 *   기본 제공이 영원히 들어오지 못한다. 사용자가 기본 제공 제스처 행을 지울 수 있는 경로는 없지만,
 *   기능(steps)·켜기/끄기는 그 행에 얹히므로 있는 행은 건드리지 않는다 (DefaultGestures 규칙).
 * @Order(5): 스텝이 없어 gesture_step.tool_name FK 에 걸릴 일은 없지만, 시드 순서(도구 → 제스처)를
 *   ToolCatalogSync(0) 뒤로 유지한다.
 */
@Component
public class DefaultGestureBootstrap {

    private static final Logger log = LoggerFactory.getLogger(DefaultGestureBootstrap.class);

    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;

    public DefaultGestureBootstrap(JdbcTemplate jdbc, PlatformTransactionManager txManager) {
        this.jdbc = jdbc;
        this.tx = new TransactionTemplate(txManager);
    }

    @EventListener(ApplicationReadyEvent.class)
    @Order(5)
    public void seedBuiltins() {
        DefaultGestures.Result result = tx.execute(status -> DefaultGestures.seedInto(jdbc));
        if (result == null) {
            return;
        }
        if (!result.conflicts().isEmpty()) {
            log.warn("같은 이름의 커스텀 제스처가 있어 기본 제공 제스처를 넣지 못했습니다 — {}."
                    + " 커스텀 제스처 이름을 바꾸면 다음 기동에 들어옵니다", result.conflicts());
        }
        if (result.inserted() > 0 || result.synced() > 0) {
            log.info("기본 제공 제스처 — 신규 {}건, 표시 문구 갱신 {}건", result.inserted(), result.synced());
        }
    }
}
