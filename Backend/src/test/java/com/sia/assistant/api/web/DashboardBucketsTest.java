package com.sia.assistant.api.web;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.sia.assistant.api.web.DashboardBuckets.Bucket;
import com.sia.assistant.api.web.DashboardBuckets.Spec;
import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import java.time.ZoneId;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class DashboardBucketsTest {

    private static final ZoneId SEOUL = ZoneId.of("Asia/Seoul");

    @Test
    @DisplayName("기간마다 버킷 수와 단위가 정해져 있다 — 8·7·5·12")
    void bucketShapePerPeriod() {
        assertThat(DashboardBuckets.of("day", SEOUL).buckets()).hasSize(8);
        assertThat(DashboardBuckets.of("day", SEOUL).bucketUnit()).isEqualTo("HOUR_3");
        assertThat(DashboardBuckets.of("week", SEOUL).buckets()).hasSize(7);
        assertThat(DashboardBuckets.of("month", SEOUL).buckets()).hasSize(5);
        assertThat(DashboardBuckets.of("year", SEOUL).buckets()).hasSize(12);
        assertThat(DashboardBuckets.of("year", SEOUL).bucketUnit()).isEqualTo("MONTH");
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
        assertThat(DashboardBuckets.of("month", SEOUL).averageDivisor()).isEqualTo(5);
        assertThat(DashboardBuckets.of("year", SEOUL).averageDivisor()).isEqualTo(12);
    }

    @Test
    @DisplayName("year 라벨은 첫 칸과 1월에만 연도를 붙인다 — 감긴 축을 읽을 수 있게")
    void yearLabelsCarryYearOnlyAtBoundaries() {
        List<Bucket> buckets = DashboardBuckets.of("year", SEOUL).buckets();

        assertThat(buckets.get(0).label()).matches("\\d{2}년 \\d{1,2}월");
        for (Bucket b : buckets) {
            boolean january = b.key().endsWith("-01");
            boolean first = b == buckets.get(0);
            if (january || first) {
                assertThat(b.label()).as(b.key()).matches("\\d{2}년 \\d{1,2}월");
            } else {
                assertThat(b.label()).as(b.key()).matches("\\d{1,2}월");
            }
        }
        // key 에는 언제나 연도가 있다 — 정확한 시점이 필요하면 이쪽을 쓴다
        assertThat(buckets).allSatisfy(b -> assertThat(b.key()).matches("\\d{4}-\\d{2}"));
    }

    @Test
    @DisplayName("month 는 굴러가는 7일 5칸이다 — 가장 최근 7일이 5주차")
    void monthIsRollingSevenDayChunks() {
        Spec spec = DashboardBuckets.of("month", SEOUL);

        assertThat(spec.buckets()).extracting(Bucket::label)
                .containsExactly("1주차", "2주차", "3주차", "4주차", "5주차");
        for (Bucket b : spec.buckets()) {
            assertThat(b.end()).isEqualTo(b.start().plusDays(7));
        }
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
