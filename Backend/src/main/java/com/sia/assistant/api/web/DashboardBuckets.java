package com.sia.assistant.api.web;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.util.ArrayList;
import java.util.List;

/**
 * 대시보드 기간(period) → 버킷 축. API.md §1.14 가 계약이다.
 *
 * <p>★ 축은 <b>로컬 타임존</b>이다. 저장은 전부 UTC 지만 사용자의 "오늘 00시"는 로컬 00시다
 * (UTC 로 그리면 9시간 밀린 하루가 나온다). 여기서만 로컬을 쓰고, 경계는 UTC 문자열로 환산해 바인딩한다.
 *
 * <p>네 기간 모두 <b>원본</b>(usage_event · tool_call)에서 집계한다 — 보존이 400일이라
 * 가장 긴 축(12개월)까지 원본이 살아 있다. 집계 테이블도 롤업 배치도 없다.
 */
public final class DashboardBuckets {

    /** 버킷 하나. {@code [start, end)} 반개구간이다. */
    public record Bucket(String key, String label, ZonedDateTime start, ZonedDateTime end) {
    }

    /**
     * 한 기간의 축 전체.
     *
     * @param averageDivisor 사용량 카드의 "평균" 분모. ★ 버킷 수가 아니다 —
     *                       day 는 버킷이 8개지만 "시간당 평균"이라 24 로 나눈다 (§1.18).
     */
    public record Spec(String period, String bucketUnit, List<Bucket> buckets,
                       String averageUnit, int averageDivisor) {

        public ZonedDateTime from() {
            return buckets.get(0).start();
        }

        public ZonedDateTime to() {
            return buckets.get(buckets.size() - 1).end();
        }
    }

    private static final String[] WEEKDAY = {"월", "화", "수", "목", "금", "토", "일"};

    private DashboardBuckets() {
    }

    /**
     * @param period day | week | month | year. 그 밖의 값은 <b>클램프하지 않고</b> 400 이다 —
     *               열거값의 오타는 드러나야 한다 (§1.14).
     */
    public static Spec of(String period, ZoneId zone) {
        String p = period == null || period.isBlank() ? "day" : period.trim();
        ZonedDateTime now = ZonedDateTime.now(zone);
        return switch (p) {
            case "day" -> day(now);
            case "week" -> week(now);
            case "month" -> month(now);
            case "year" -> year(now);
            default -> throw new ApiException(ErrorCode.INVALID_REQUEST,
                    "period 는 day | week | month | year 중 하나여야 합니다");
        };
    }

    /** 오늘 로컬 00:00 부터 3시간씩 8칸. 아직 오지 않은 칸도 0 으로 남긴다. */
    private static Spec day(ZonedDateTime now) {
        ZonedDateTime midnight = now.toLocalDate().atStartOfDay(now.getZone());
        List<Bucket> buckets = new ArrayList<>(8);
        for (int i = 0; i < 8; i++) {
            ZonedDateTime start = midnight.plusHours(i * 3L);
            buckets.add(new Bucket(
                    start.toLocalDate() + "T" + String.format("%02d", start.getHour()),
                    String.format("%02d시", start.getHour()),
                    start, start.plusHours(3)));
        }
        return new Spec("day", "HOUR_3", buckets, "HOUR", 24);
    }

    /** 오늘 포함 최근 7일, 하루 한 칸. 라벨은 요일. */
    private static Spec week(ZonedDateTime now) {
        LocalDate today = now.toLocalDate();
        List<Bucket> buckets = new ArrayList<>(7);
        for (int i = 6; i >= 0; i--) {
            LocalDate d = today.minusDays(i);
            ZonedDateTime start = d.atStartOfDay(now.getZone());
            buckets.add(new Bucket(d.toString(),
                    WEEKDAY[d.getDayOfWeek().getValue() - 1],
                    start, start.plusDays(1)));
        }
        return new Spec("week", "DAY", buckets, "DAY", 7);
    }

    /**
     * 오늘부터 7일씩 거슬러 5칸 — <b>가장 최근 7일이 5주차</b>다.
     * 달력 주(월요일 시작)가 아니라 굴러가는 7일이다: 주 시작 요일을 무엇으로 잡든
     * 첫 칸이 잘려 "1주차"만 표본이 적어지는 문제가 생기는데, 그걸 피한다.
     */
    private static Spec month(ZonedDateTime now) {
        LocalDate today = now.toLocalDate();
        List<Bucket> buckets = new ArrayList<>(5);
        for (int i = 4; i >= 0; i--) {
            LocalDate start = today.minusDays(7L * i + 6);
            ZonedDateTime from = start.atStartOfDay(now.getZone());
            buckets.add(new Bucket(start.toString(), (5 - i) + "주차", from, from.plusDays(7)));
        }
        return new Spec("month", "WEEK", buckets, "WEEK", 5);
    }

    /**
     * 이번 달 포함 12개월. 롤링이라 축이 감긴다(9월…12월·1월…8월).
     * 그래서 <b>첫 칸과 해가 바뀌는 칸(1월)에만</b> 연도를 붙인다 (§1.14).
     */
    private static Spec year(ZonedDateTime now) {
        LocalDate firstOfThisMonth = now.toLocalDate().withDayOfMonth(1);
        List<Bucket> buckets = new ArrayList<>(12);
        for (int i = 11; i >= 0; i--) {
            LocalDate m = firstOfThisMonth.minusMonths(i);
            ZonedDateTime from = m.atStartOfDay(now.getZone());
            boolean showYear = (i == 11) || m.getMonthValue() == 1;
            String label = showYear
                    ? String.format("%02d년 %d월", m.getYear() % 100, m.getMonthValue())
                    : m.getMonthValue() + "월";
            buckets.add(new Bucket(String.format("%04d-%02d", m.getYear(), m.getMonthValue()),
                    label, from, from.plusMonths(1)));
        }
        return new Spec("year", "MONTH", buckets, "MONTH", 12);
    }

    /**
     * DB 바인딩용 UTC 문자열 (Times 와 같은 23자 고정폭).
     * 시각 비교 값은 전부 Java 가 만들어 바인딩한다 — SQL 의 datetime('now') 는 폭이 다르다.
     */
    public static String utc(ZonedDateTime t) {
        return com.sia.assistant.common.Times.of(t.toInstant());
    }

    /**
     * {@code substr(received_at,1,13)} 이 준 UTC 시각("yyyy-MM-dd HH")이 몇 번째 버킷인가.
     * 없으면 -1.
     *
     * <p>시간 단위로 집계한 뒤 Java 에서 버킷에 넣는다 — 1년치라도 최대 8,760행이라 싸고,
     * 로컬 경계(자정·3시간·월초)를 UTC SQL 표현식으로 억지로 옮기지 않아도 된다.
     * 전제는 로컬 오프셋이 <b>정시 단위</b>라는 것이다(Asia/Seoul 은 +09:00 고정).
     */
    public static int indexOf(List<Bucket> buckets, String utcHour, ZoneId zone) {
        if (utcHour == null || utcHour.length() < 13) {
            return -1;
        }
        LocalDateTime hour = LocalDateTime.parse(utcHour.substring(0, 13).replace(' ', 'T') + ":00");
        ZonedDateTime local = hour.atOffset(ZoneOffset.UTC).atZoneSameInstant(zone);
        for (int i = 0; i < buckets.size(); i++) {
            Bucket b = buckets.get(i);
            if (!local.isBefore(b.start()) && local.isBefore(b.end())) {
                return i;
            }
        }
        return -1;
    }
}
