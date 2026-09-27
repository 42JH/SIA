package com.sia.assistant.control.process;

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
 * 기동마다 Windows 기본 앱(메모장·계산기)이 app_target 에 있는지 보고 없는 것만 넣는다
 * — 판단·삽입 규칙은 전부 DefaultAppTargets 에 있다.
 * @Order(6): app_target 은 tool·gesture 와 FK 관계가 없어 순서 제약은 없지만, 기동 로그가
 * 카탈로그 동기화(0) · 기본 매핑(5) 다음에 읽히도록 뒤에 둔다.
 * 전체 삭제(WipeService) 뒤 복원도 같은 시드를 쓴다.
 */
@Component
public class DefaultAppTargetBootstrap {

    private static final Logger log = LoggerFactory.getLogger(DefaultAppTargetBootstrap.class);

    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;

    public DefaultAppTargetBootstrap(JdbcTemplate jdbc, PlatformTransactionManager txManager) {
        this.jdbc = jdbc;
        this.tx = new TransactionTemplate(txManager);
    }

    @EventListener(ApplicationReadyEvent.class)
    @Order(6)
    public void seedMissing() {
        Integer seeded = tx.execute(status -> DefaultAppTargets.seedInto(jdbc));
        if (seeded != null && seeded > 0) {
            log.info("Windows 기본 앱 {}건을 실행 가능 앱으로 등록했습니다", seeded);
        }
    }
}
