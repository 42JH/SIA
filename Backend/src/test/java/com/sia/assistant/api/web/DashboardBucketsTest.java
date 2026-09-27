package com.sia.assistant.api.web;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.sia.assistant.api.web.DashboardBuckets.Bucket;
import com.sia.assistant.api.web.DashboardBuckets.Spec;
import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class DashboardBucketsTest {

    private static final ZoneId SEOUL = ZoneId.of("Asia/Seoul");

    @Test
    @DisplayName("기간마다 버킷 수와 단위가 정해져 있다 — 8·7·12, month 만 달마다 4~6")
    void bucketShapePerPeriod() {
        assertThat(DashboardBuckets.of("day", SEOUL).buckets()).hasSize(8);
        assertThat(DashboardBuckets.of("day", SEOUL).bucketUnit()).isEqualTo("HOUR_3");
        assertThat(DashboardBuckets.of("week", SEOUL).buckets()).hasSize(7);
        assertThat(DashboardBuckets.of("year", SEOUL).buckets()).hasSize(12);
        assertThat(DashboardBuckets.of("year", SEOUL).bucketUnit()).isEqualTo("MONTH");
        // ★ month 는 달력 주 경계로 쪼개므로 고정이 아니다
        assertThat(DashboardBuckets.of("month", SEOUL).buckets()).hasSizeBetween(4, 6);
        assertThat(DashboardBuckets.of("month", SEOUL).bucketUnit()).isEqualTo("WEEK");
    }

    @Test
    @DisplayName("period 를 생략하면 day 다")
    void defaultsToDay() {
        assertThat(DashboardBuckets.of(null, SEOUL).period()).isEqualTo("day");
        assertThat(DashboardBuckets.of("  ", SEOUL).period()).isEqualTo("day");
    }

    @Test
    @DisplayName("모르는 period 는 조용히 클램프하지 않고 INVALID_REQUEST 다")
    void unknownPeriodIsRejected() {
        assertThatThrownBy(() -> DashboardBuckets.of("month ly", SEOUL))
                .isInstanceOfSatisfying(ApiException.class,
                        e -> assertThat(e.code).isEqualTo(ErrorCode.INVALID_REQUEST));
    }

    @Test
    @DisplayName("day 는 로컬 자정부터 3시간씩 — 라벨이 00시·03시…21시다")
    void dayBucketsStartAtLocalMidnight() {
        Spec spec = DashboardBuckets.of("day", SEOUL);

        assertThat(spec.buckets()).extracting(Bucket::label)
                .containsExactly("00시", "03시", "06시", "09시", "12시", "15시", "18시", "21시");
        assertThat(spec.from().getHour()).isZero();
        assertThat(spec.from().getZone()).isEqualTo(SEOUL);
        // 아직 오지 않은 칸도 남긴다 — 축이 끊기지 않아야 한다
        assertThat(spec.to()).isEqualTo(spec.from().plusDays(1));
    }

    @Test
    @DisplayName("사용량 평균의 분모는 버킷 수가 아니다 — day 는 버킷 8개인데 24로 나눈다")
    void averageDivisorIsNotBucketCount() {
        Spec day = DashboardBuckets.of("day", SEOUL);
        assertThat(day.buckets()).hasSize(8);
        assertThat(day.averageDivisor()).isEqualTo(24);
        assertThat(day.averageUnit()).isEqualTo("HOUR");

        assertThat(DashboardBuckets.of("week", SEOUL).averageDivisor()).isEqualTo(7);
        assertThat(DashboardBuckets.of("year", SEOUL).averageDivisor()).isEqualTo(12);
        // month 만 예외다 — 칸 수가 달마다 달라서 분모도 칸 수를 따른다
        Spec month = DashboardBuckets.of("month", SEOUL);
        assertThat(month.averageDivisor()).isEqualTo(month.buckets().size());
        assertThat(month.averageUnit()).isEqualTo("WEEK");
    }

    @Test
    @DisplayName("week 은 굴러가는 7일이 아니라 이번 주 월요일부터다")
    void weekStartsOnThisMondayNotSevenDaysAgo() {
        Spec spec = DashboardBuckets.of("week", SEOUL);

        assertThat(spec.buckets()).extracting(Bucket::label)
                .containsExactly("월", "화", "수", "목", "금", "토", "일");
        assertThat(spec.from().getDayOfWeek()).isEqualTo(DayOfWeek.MONDAY);
        assertThat(spec.from().getHour()).isZero();
        assertThat(spec.to()).isEqualTo(spec.from().plusDays(7));
        // 오늘은 반드시 축 안에 있다 — 주 중 어느 요일이든
        ZonedDateTime today = ZonedDateTime.now(SEOUL).toLocalDate().atStartOfDay(SEOUL);
        assertThat(today).isAfterOrEqualTo(spec.from()).isBefore(spec.to());
    }

    @Test
    @DisplayName("year 는 올해 1~12월이라 1월에만 연도를 붙인다")
    void yearIsThisCalendarYear() {
        Spec spec = DashboardBuckets.of("year", SEOUL);
        List<Bucket> buckets = spec.buckets();
        int thisYear = ZonedDateTime.now(SEOUL).getYear();

        assertThat(spec.from().getMonthValue()).isEqualTo(1);
        assertThat(spec.from().getDayOfMonth()).isEqualTo(1);
        assertThat(spec.from().getYear()).isEqualTo(thisYear);
        assertThat(spec.to()).isEqualTo(spec.from().plusYears(1));

        assertThat(buckets.get(0).label()).matches("\\d{2}년 1월");
        for (Bucket b : buckets.subList(1, buckets.size())) {
            assertThat(b.label()).as(b.key()).matches("\\d{1,2}월");
        }
        // key 에는 언제나 연도가 있다 — 정확한 시점이 필요하면 이쪽을 쓴다
        assertThat(buckets).allSatisfy(b -> assertThat(b.key()).startsWith(thisYear + "-"));
    }

    @Test
    @DisplayName("month 는 이번 달을 달력 주(월~일)로 쪼갠다 — 첫 칸·마지막 칸은 달 경계에서 잘린다")
    void monthIsSplitOnCalendarWeekBoundaries() {
        Spec spec = DashboardBuckets.of("month", SEOUL);
        List<Bucket> buckets = spec.buckets();

        // 축은 이번 달 1일 ~ 말일 정확히다
        assertThat(spec.from().getDayOfMonth()).isEqualTo(1);
        assertThat(spec.from().getHour()).isZero();
        assertThat(spec.to()).isEqualTo(spec.from().plusMonths(1));

        assertThat(buckets).extracting(Bucket::label)
                .containsExactlyElementsOf(java.util.stream.IntStream.rangeClosed(1, buckets.size())
                        .mapToObj(i -> i + "주차").toList());

        for (int i = 0; i < buckets.size(); i++) {
            Bucket b = buckets.get(i);
            assertThat(b.start()).as("칸이 끊기면 안 된다")
                    .isEqualTo(i == 0 ? spec.from() : buckets.get(i - 1).end());
            // 잘리는 건 양 끝뿐이다 — 가운데 칸은 월요일에 시작해 7일이다
            if (i > 0) {
                assertThat(b.start().getDayOfWeek()).as(b.key()).isEqualTo(DayOfWeek.MONDAY);
            }
            if (i < buckets.size() - 1) {
                assertThat(b.end().getDayOfWeek()).as(b.key()).isEqualTo(DayOfWeek.MONDAY);
            }
        }
    }

    @Test
    @DisplayName("어느 날짜에 물어도 축이 성립한다 — 2년치 매일로 쓸어 본다")
    void axesHoldOnEveryDate() {
        LocalDate start = LocalDate.of(2025, 1, 1);
        for (int i = 0; i < 730; i++) {
            ZonedDateTime now = start.plusDays(i).atTime(9, 30).atZone(SEOUL);
            LocalDate today = now.toLocalDate();

            Spec week = DashboardBuckets.of("week", now);
            assertThat(week.buckets()).as("week %s", today).hasSize(7);
            assertThat(week.from().getDayOfWeek()).as("week %s", today).isEqualTo(DayOfWeek.MONDAY);
            assertThat(now).as("week 는 오늘을 담는다 %s", today)
                    .isAfterOrEqualTo(week.from()).isBefore(week.to());

            Spec month = DashboardBuckets.of("month", now);
            assertThat(month.buckets()).as("month %s", today).hasSizeBetween(4, 6);
            assertThat(month.from().toLocalDate()).as("month %s", today)
                    .isEqualTo(today.withDayOfMonth(1));
            assertThat(month.to()).as("month %s", today).isEqualTo(month.from().plusMonths(1));
            assertThat(month.averageDivisor()).isEqualTo(month.buckets().size());
            assertContiguous(month, today);

            Spec year = DashboardBuckets.of("year", now);
            assertThat(year.buckets()).as("year %s", today).hasSize(12);
            assertThat(year.from().toLocalDate()).as("year %s", today)
                    .isEqualTo(today.withDayOfYear(1));
            assertThat(year.to()).as("year %s", today).isEqualTo(year.from().plusYears(1));
            assertContiguous(year, today);
        }
    }

    /** 칸이 끊기거나 겹치면 이벤트가 새거나 두 번 세어진다. */
    private static void assertContiguous(Spec spec, LocalDate today) {
        List<Bucket> buckets = spec.buckets();
        for (int i = 1; i < buckets.size(); i++) {
            assertThat(buckets.get(i).start()).as("%s %s 칸 %d", spec.period(), today, i)
                    .isEqualTo(buckets.get(i - 1).end());
        }
        assertThat(buckets).allSatisfy(b -> assertThat(b.start()).isBefore(b.end()));
    }

    @Test
    @DisplayName("UTC 시각을 로컬 버킷에 넣는다 — 범위 밖이면 -1")
    void utcHourMapsIntoLocalBucket() {
        Spec spec = DashboardBuckets.of("week", SEOUL);
        List<Bucket> buckets = spec.buckets();

        // 마지막 버킷(오늘) 시작 시각을 UTC 로 되돌리면 마지막 칸을 가리켜야 한다
        String utcHour = DashboardBuckets.utc(buckets.get(6).start()).substring(0, 13);
        assertThat(DashboardBuckets.indexOf(buckets, utcHour, SEOUL)).isEqualTo(6);

        String longAgo = DashboardBuckets.utc(spec.from().minusDays(30)).substring(0, 13);
        assertThat(DashboardBuckets.indexOf(buckets, longAgo, SEOUL)).isEqualTo(-1);
        assertThat(DashboardBuckets.indexOf(buckets, null, SEOUL)).isEqualTo(-1);
    }
}
