package com.sia.assistant.common;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;

/**
 * 모든 시각 포맷의 유일한 출처.
 * DB 의 모든 시각은 UTC 'yyyy-MM-dd HH:mm:ss.SSS' 23자 고정폭 텍스트다 (특화.sql TSTZ/VARCHAR(23) 주석 그대로).
 * 고정폭 + 전부 UTC 라 문자열 비교 = 시간 비교가 성립한다.
 * ★ 시각 비교에 쓰는 값은 전부 이 클래스가 만들어 바인딩한다 — datetime('now') 는 밀리초가 없어 폭이 다르다.
 */
public final class Times {

    private static final DateTimeFormatter FMT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss.SSS");

    private Times() {
    }

    public static String now() {
        return of(Instant.now());
    }

    public static String of(Instant instant) {
        return FMT.format(LocalDateTime.ofInstant(instant, ZoneOffset.UTC));
    }

    public static String ofEpochMs(long epochMs) {
        return of(Instant.ofEpochMilli(epochMs));
    }

    public static String daysAgo(int days) {
        return of(Instant.now().minus(Duration.ofDays(days)));
    }

    public static Instant parse(String text) {
        return LocalDateTime.parse(text, FMT).toInstant(ZoneOffset.UTC);
    }
}
