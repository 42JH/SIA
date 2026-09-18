package com.sia.assistant.api.web;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.time.temporal.TemporalAdjusters;
import java.util.ArrayList;
import java.util.List;

/**
 * 대시보드 기간(period) → 버킷 축. API명세서 §1.18 이 계약이다.
 *
 * <p>★ 축은 <b>로컬 타임존</b>이다. 저장은 전부 UTC 지만 사용자의 "오늘 00시"는 로컬 00시다
 * (UTC 로 그리면 9시간 밀린 하루가 나온다). 여기서만 로컬을 쓰고, 경계는 UTC 문자열로 환산해 바인딩한다.
 *
 * <p>★ 네 기간 모두 <b>달력</b> 축이다 — 오늘 · 이번 주(월~일) · 이번 달 · 올해다.
 * 굴러가는 창이 아니라서 아직 오지 않은 칸이 생기는데, 그 칸도 개수 0 · 평균 null 로 남긴다
 * (day 가 예전부터 그랬던 것과 같은 규칙이다).
 *
 * <p>네 기간 모두 <b>원본</b>(usage_event · tool_call)에서 집계한다 — 보존이 400일이라
 * 가장 긴 축(올해 1월 1일)까지 원본이 살아 있다. 집계 테이블도 롤업 배치도 없다.
 */
public final class DashboardBuckets {

    /** 버킷 하나. {@code [start, end)} 반개구간이다. */
    public record Bucket(String key, String label, ZonedDateTime start, ZonedDateTime end) {
    }

    /**
     * 한 기간의 축 전체.
     *
     * @param averageDivisor 사용량 카드의 "평균" 분모. ★ 버킷 수라고 넘겨짚으면 안 된다 —
     *                       day 는 버킷이 8개지만 "시간당 평균"이라 24 로 나눈다 (§1.22).
     *                       week 은 7, year 는 12, month 만 칸 수(4~6)와 같다.
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
     *               열거값의 오타는 드러나야 한다 (§1.18).
     */
    public static Spec of(String period, ZoneId zone) {
        return of(period, ZonedDateTime.now(zone));
    }

    /**
     * 시계를 직접 받는 형태. 축이 <b>실행 날짜</b>에 따라 달라지므로
     * (월요일이냐, 달의 며칠이냐) 테스트가 임의의 날짜를 재현할 수 있어야 한다.
     */
    static Spec of(String period, ZonedDateTime now) {
        String p = period == null || period.isBlank() ? "day" : period.trim();
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

    /** 이번 주 월요일 00:00 부터 일요일까지 하루 한 칸, 7칸. 라벨은 요일. */
    private static Spec week(ZonedDateTime now) {
        LocalDate monday = now.toLocalDate().with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY));
        List<Bucket> buckets = new ArrayList<>(7);
        for (int i = 0; i < 7; i++) {
            LocalDate d = monday.plusDays(i);
            ZonedDateTime start = d.atStartOfDay(now.getZone());
            buckets.add(new Bucket(d.toString(), WEEKDAY[i], start, start.plusDays(1)));
        }
        return new Spec("week", "DAY", buckets, "DAY", 7);
    }

    /**
     * 이번 달 1일 ~ 말일을 달력 주(월~일) 경계로 쪼갠다. 1일이 든 주가 1주차다.
     *
     * <p>★ 칸 수가 <b>달마다 4~6개로 다르다</b> — 고정이라고 보면 안 된다.
     * 첫 칸과 마지막 칸은 달 경계에서 자른다: 자르지 않으면 "이번 달" 합계가 옆 달을 물어
     * 월별 합을 더해도 연 합계가 안 맞는다. 그 대신 잘린 칸은 표본이 적어 막대가 낮게 보이는데,
     * 달력 축을 택한 대가다.
     *
     * <p>그래서 사용량 평균의 분모도 5 고정이 아니라 <b>이 달의 칸 수</b>다.
     */
    private static Spec month(ZonedDateTime now) {
        LocalDate first = now.toLocalDate().withDayOfMonth(1);
        LocalDate nextMonth = first.plusMonths(1);
        List<Bucket> buckets = new ArrayList<>(6);
        LocalDate cursor = first;
        while (cursor.isBefore(nextMonth)) {
            // 이 주의 일요일 다음 날 = 반개구간의 끝. 달을 넘으면 말일에서 자른다
            LocalDate weekEnd = cursor.with(TemporalAdjusters.nextOrSame(DayOfWeek.SUNDAY)).plusDays(1);
            LocalDate end = weekEnd.isAfter(nextMonth) ? nextMonth : weekEnd;
            buckets.add(new Bucket(cursor.toString(), (buckets.size() + 1) + "주차",
                    cursor.atStartOfDay(now.getZone()), end.atStartOfDay(now.getZone())));
            cursor = end;
        }
        return new Spec("month", "WEEK", buckets, "WEEK", buckets.size());
    }

    /**
     * 올해 1월 ~ 12월 12칸. 축이 한 해 안에 있어 감기지 않으므로
     * <b>1월에만</b> 연도를 붙인다 — 나머지는 "M월"이다 (§1.18).
     */
    private static Spec year(ZonedDateTime now) {
        LocalDate january = now.toLocalDate().withDayOfYear(1);
        List<Bucket> buckets = new ArrayList<>(12);
        for (int i = 0; i < 12; i++) {
            LocalDate m = january.plusMonths(i);
            ZonedDateTime from = m.atStartOfDay(now.getZone());
            String label = m.getMonthValue() == 1
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
