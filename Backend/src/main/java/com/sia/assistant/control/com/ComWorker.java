package com.sia.assistant.control.com;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sun.jna.platform.win32.Ole32;
import jakarta.annotation.PreDestroy;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * COM 호출 전용 단일 스레드 — 셸(Shell.Application·WScript.Shell)과 UIA 는 아파트 규칙이 있어
 * 아무 요청 스레드에서나 부르면 안 된다. 이 스레드 하나가 MTA 로 초기화되어 모든 COM 작업을 받는다.
 * (in-proc STA 객체는 COM 이 호스트 STA 로 자동 마샬링한다 — 느리지만 정확하다)
 */
@Component
public class ComWorker {

    private static final Logger log = LoggerFactory.getLogger(ComWorker.class);

    private final ExecutorService executor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "com-worker");
        t.setDaemon(true);
        return t;
    });

    public ComWorker() {
        // 스레드 최초 작업으로 COM 초기화 — 이후 제출되는 모든 작업이 같은 스레드라 1회면 된다
        executor.submit(() -> {
            try {
                Ole32.INSTANCE.CoInitializeEx(null, Ole32.COINIT_MULTITHREADED);
                log.info("com-worker COM 초기화 완료 (MTA)");
            } catch (Throwable t) {
                log.warn("com-worker COM 초기화 실패 — COM 기반 기능이 동작하지 않을 수 있다", t);
            }
        });
    }

    /** COM 스레드에서 task 를 실행하고 결과를 기다린다. 예외는 원형(RuntimeException) 그대로 전파한다. */
    public <T> T call(String what, long timeoutMs, Callable<T> task) {
        Future<T> future = executor.submit(task);
        try {
            return future.get(timeoutMs, TimeUnit.MILLISECONDS);
        } catch (TimeoutException e) {
            // COM 호출 도중 인터럽트는 위험하므로 취소하지 않는다 — 작업은 스레드에서 끝까지 돈다
            throw new ApiException(ErrorCode.INTERNAL_ERROR, what + " 처리가 제한 시간 안에 끝나지 않았습니다");
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ApiException(ErrorCode.INTERNAL_ERROR, what + " 처리가 중단되었습니다");
        } catch (ExecutionException e) {
            if (e.getCause() instanceof RuntimeException re) {
                throw re;
            }
            log.warn("{} COM 작업 실패", what, e.getCause());
            throw new ApiException(ErrorCode.INTERNAL_ERROR, what + " 처리에 실패했습니다");
        }
    }

    @PreDestroy
    void shutdown() {
        executor.shutdownNow();
    }
}
