package com.sia.assistant.registration;

import com.sia.assistant.config.DataDirs;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import ws.schild.jave.process.ffmpeg.DefaultFFMPEGLocator;

/**
 * 등록 프레임(jpeg) 시퀀스 → 미리보기 webm 인코더.
 * ffmpeg 실행 파일은 jave-nativebin 이 번들한 것을 DefaultFFMPEGLocator 로 얻는다.
 * 프레임 간격이 고르지 않으므로 concat demuxer 의 duration 지시자로 수신 타임스탬프 간격을 그대로 옮긴다.
 */
@Component
public class WebmEncoder {

    private static final Logger log = LoggerFactory.getLogger(WebmEncoder.class);
    private static final long TIMEOUT_SEC = 120;

    /** 등록 구간의 프레임 한 장 — 수신 순서(seq)와 수신 시각(tsMs)이 재생 타이밍의 근거다. */
    public record Frame(long seq, long tsMs, byte[] jpeg) {
    }

    private final DataDirs dataDirs;

    public WebmEncoder(DataDirs dataDirs) {
        this.dataDirs = dataDirs;
    }

    /**
     * @param baseName 출력 파일 이름(확장자 제외) — 회차별 미리보기는 "{tempId}-{take}" 다
     * @return 생성된 webm 경로 (outDir/baseName.webm)
     * @throws IOException 인코딩 실패 — 호출자가 reg_recorded 의 해당 회차 webmUrl:null 로 처리한다
     */
    public Path encode(String baseName, List<Frame> frames, Path outDir) throws IOException {
        if (frames == null || frames.isEmpty()) {
            throw new IOException("녹화된 프레임이 없습니다");
        }
        String ffmpeg = new DefaultFFMPEGLocator().getExecutablePath();
        Path work = Files.createDirectories(dataDirs.tmp().resolve("reg_" + baseName));
        try {
            int n = frames.size();
            for (int i = 0; i < n; i++) {
                Files.write(work.resolve(String.format("frame_%05d.jpg", i + 1)), frames.get(i).jpeg());
            }

            double[] durations = durations(frames);
            StringBuilder list = new StringBuilder("ffconcat version 1.0\n");
            for (int i = 0; i < n; i++) {
                list.append(String.format("file 'frame_%05d.jpg'%n", i + 1));
                list.append(String.format(Locale.ROOT, "duration %.3f%n", durations[i]));
            }
            // concat demuxer 는 마지막 duration 을 무시하므로 마지막 프레임을 한 번 더 나열해 보정한다.
            list.append(String.format("file 'frame_%05d.jpg'%n", n));
            Path listFile = work.resolve("list.txt");
            Files.writeString(listFile, list.toString(), StandardCharsets.UTF_8);

            Path out = outDir.resolve(baseName + ".webm");
            ProcessBuilder pb = new ProcessBuilder(
                    ffmpeg, "-y", "-f", "concat", "-safe", "0",
                    "-i", listFile.toAbsolutePath().toString(),
                    "-c:v", "libvpx", "-b:v", "1M", "-crf", "30", "-pix_fmt", "yuv420p",
                    out.toAbsolutePath().toString());
            pb.directory(work.toFile());
            pb.redirectErrorStream(true);
            Process process = pb.start();

            // 출력을 소비하지 않으면 파이프가 차서 ffmpeg 이 멈춘다 — 별도 스레드로 로그에 흘린다.
            StringBuilder tail = new StringBuilder();
            Thread gobbler = new Thread(() -> {
                try (BufferedReader r = new BufferedReader(
                        new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = r.readLine()) != null) {
                        log.debug("[ffmpeg] {}", line);
                        if (tail.length() < 2000) {
                            tail.append(line).append('\n');
                        }
                    }
                } catch (IOException ignored) {
                }
            }, "webm-ffmpeg-log");
            gobbler.setDaemon(true);
            gobbler.start();

            boolean finished;
            try {
                finished = process.waitFor(TIMEOUT_SEC, TimeUnit.SECONDS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                process.destroyForcibly();
                throw new IOException("인코딩이 중단되었습니다");
            }
            if (!finished) {
                process.destroyForcibly();
                throw new IOException("인코딩이 " + TIMEOUT_SEC + "초를 초과해 중단했습니다");
            }
            if (process.exitValue() != 0) {
                log.warn("ffmpeg 종료 코드 {}\n{}", process.exitValue(), tail);
                throw new IOException("영상 인코딩에 실패했습니다 (ffmpeg 종료 코드 " + process.exitValue() + ")");
            }
            return out;
        } finally {
            deleteRecursively(work);
        }
    }

    /** 프레임별 표시 시간(초). 수신 타임스탬프 간격이 근거, 마지막 프레임은 앞선 간격들의 평균. */
    private static double[] durations(List<Frame> frames) {
        int n = frames.size();
        double[] d = new double[n];
        double sum = 0;
        for (int i = 0; i < n - 1; i++) {
            double gap = (frames.get(i + 1).tsMs() - frames.get(i).tsMs()) / 1000.0;
            d[i] = Math.max(gap, 0.001);
            sum += d[i];
        }
        d[n - 1] = n > 1 ? sum / (n - 1) : 1.0 / 30;
        return d;
    }

    private static void deleteRecursively(Path dir) {
        try (Stream<Path> walk = Files.walk(dir)) {
            Deque<Path> stack = new ArrayDeque<>();
            walk.forEach(stack::push); // 자식 먼저 지우도록 역순
            for (Path p : stack) {
                Files.deleteIfExists(p);
            }
        } catch (IOException e) {
            log.warn("등록 임시 디렉터리 정리 실패: {}", dir, e);
        }
    }
}
