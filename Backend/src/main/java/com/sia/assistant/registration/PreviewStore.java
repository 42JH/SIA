package com.sia.assistant.registration;

import com.sia.assistant.config.DataDirs;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.stream.Stream;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.core.annotation.Order;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * previews/ 디렉터리의 유일한 관리자 — 등록 미리보기(동적 webm · 정적 jpg)의 수명을 여기 모은다.
 *
 * <p>미리보기는 reg_recorded 로 회차 3개를 보여 주고 사용자가 하나를 고를 때까지만 쓰는 임시 파일이다.
 * 고른 회차는 gestures/ 로 승격되므로(RegistrationOrchestrator.promoteVideo) 그 뒤로는 3개 전부 쓸모가 없다.
 * ★ 사용자 카메라 영상이라 쓰임이 끝나면 남기지 않는다 — 승격·거절·등록 교체 때 {@link #discard(String)},
 * 전체 삭제 때 {@link #clearAll()}, 그리고 어느 경로로도 안 지워진 고아는 기동·일일 스윕이 걷어 간다.
 *
 * <p>기동 스윕이 나이를 안 따지고 전량 지우는 이유: 재기동하면 진행 중이던 등록 상태(tempId·임시 npz)가
 * 메모리와 함께 사라져 macro_assign 이 어차피 거절된다. 그래서 기동 시점에 남아 있는 파일은 전부 고아다.
 */
@Component
public class PreviewStore {

    private static final Logger log = LoggerFactory.getLogger(PreviewStore.class);
    /** 일일 스윕이 고아로 보는 나이. 등록 한 판(촬영~선택)보다 넉넉히 길게 잡는다. */
    static final Duration ORPHAN_AGE = Duration.ofHours(6);

    private final DataDirs dataDirs;

    public PreviewStore(DataDirs dataDirs) {
        this.dataDirs = dataDirs;
    }

    /** 등록 한 건({tempId}-{take}.{webm|jpg} 전부) 폐기 — 승격 완료·거절·등록 교체 시. */
    public void discard(String tempId) {
        if (tempId == null || tempId.isBlank()) {
            return;
        }
        // 이름 접두사로만 고른다 — tempId 에 경로 문자가 섞여도 resolve 하지 않으니 탈출이 없다.
        String prefix = tempId + "-";
        int deleted = deleteMatching(p -> {
            String name = p.getFileName().toString();
            return name.startsWith(prefix) && RegistrationMedia.isMediaFile(name);
        });
        if (deleted > 0) {
            log.debug("등록 {} 미리보기 {}개 정리", tempId, deleted);
        }
    }

    /** 전체 삭제(WipeService)용 — 남은 미리보기 일괄 제거. */
    public void clearAll() {
        deleteMatching(p -> true);
    }

    @EventListener(ApplicationReadyEvent.class)
    @Order(30)
    public void onStartup() {
        clearAll();
    }

    @Scheduled(cron = "0 30 4 * * *")
    public void daily() {
        sweepOlderThan(ORPHAN_AGE);
    }

    /** 나이를 받는 실제 구현 — 테스트가 6시간을 기다리지 않고 스윕 경로를 검증할 수 있게 연다. */
    int sweepOlderThan(Duration age) {
        Instant cutoff = Instant.now().minus(age);
        int deleted = deleteMatching(p -> {
            try {
                return Files.getLastModifiedTime(p).toInstant().isBefore(cutoff);
            } catch (IOException e) {
                return false; // 못 읽는 파일은 건드리지 않는다
            }
        });
        if (deleted > 0) {
            log.info("주인 없는 등록 미리보기 {}개를 정리했습니다", deleted);
        }
        return deleted;
    }

    private int deleteMatching(java.util.function.Predicate<Path> match) {
        Path dir = dataDirs.previews();
        List<Path> targets;
        try (Stream<Path> files = Files.list(dir)) {
            targets = files.filter(Files::isRegularFile).filter(match).toList();
        } catch (IOException e) {
            log.warn("미리보기 폴더를 읽지 못했습니다: {}", dir, e);
            return 0;
        }
        int deleted = 0;
        for (Path p : targets) {
            try {
                if (Files.deleteIfExists(p)) {
                    deleted++;
                }
            } catch (IOException e) {
                log.warn("미리보기 삭제 실패: {}", p, e);
            }
        }
        return deleted;
    }
}
