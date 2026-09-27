package com.sia.assistant.registration;

import static org.assertj.core.api.Assertions.assertThat;

import com.sia.assistant.config.DataDirs;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.time.Duration;
import java.time.Instant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * previews/ 수명 관리 — 등록 한 건 폐기(discard), 전체 삭제(clearAll), 고아 스윕(sweepOlderThan).
 * 미리보기는 사용자 카메라 영상이라 "언젠가는 지워진다"가 아니라 "쓰임이 끝나면 없다"여야 한다.
 */
class PreviewStoreTest {

    private Path previews;
    private PreviewStore store;

    @BeforeEach
    void setUp(@TempDir Path dir) throws Exception {
        DataDirs dataDirs = new DataDirs(dir.toString());
        previews = Files.createDirectories(dataDirs.previews());
        store = new PreviewStore(dataDirs);
    }

    private Path preview(String name) throws Exception {
        return Files.write(previews.resolve(name), new byte[]{1});
    }

    @Test
    @DisplayName("discard 는 그 tempId 의 회차만 지우고 다른 등록은 건드리지 않는다")
    void discardRemovesOnlyOwnTakes() throws Exception {
        preview("9f3a2c17-1.webm");
        preview("9f3a2c17-2.webm");
        preview("9f3a2c17-3.webm");
        Path other = preview("aa11bb22-1.webm");

        store.discard("9f3a2c17");

        assertThat(previews.toFile().list()).containsExactly(other.getFileName().toString());
    }

    @Test
    @DisplayName("discard 는 tempId 가 비었거나 접두사만 겹치는 파일에는 손대지 않는다")
    void discardIgnoresBlankAndPartialMatches() throws Exception {
        preview("9f3a2c17abc-1.webm"); // 접두사는 겹치지만 다른 등록이다
        store.discard("9f3a2c17");
        store.discard("");
        store.discard(null);

        assertThat(previews.toFile().list()).containsExactly("9f3a2c17abc-1.webm");
    }

    @Test
    @DisplayName("sweepOlderThan 은 나이가 지난 파일만 걷어 간다")
    void sweepRemovesOnlyOldFiles() throws Exception {
        Path old = preview("old-1.webm");
        Files.setLastModifiedTime(old, FileTime.from(Instant.now().minus(Duration.ofHours(9))));
        preview("fresh-1.webm");

        assertThat(store.sweepOlderThan(Duration.ofHours(6))).isEqualTo(1);
        assertThat(previews.toFile().list()).containsExactly("fresh-1.webm");
    }

    @Test
    @DisplayName("clearAll 은 남은 미리보기를 모두 지운다 — 전체 삭제가 카메라 영상을 남기지 않는다")
    void clearAllEmptiesDirectory() throws Exception {
        preview("9f3a2c17-1.webm");
        preview("aa11bb22-3.webm");

        store.clearAll();

        assertThat(previews.toFile().list()).isEmpty();
    }
}
