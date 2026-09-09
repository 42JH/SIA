package com.sia.assistant.model;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.config.DataDirs;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.core.annotation.Order;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

/**
 * 인식 모델 파일의 확보(다운로드·sha256 검증)와 AI 적재 상태 추적.
 * 목록: DataDirs.root()/models.json 이 있으면 그것, 없으면 classpath:models.json.
 * 상태는 전부 메모리 플래그 — 재기동하면 파일 검증부터 다시 확인한다.
 */
@Component
public class ModelManager {

    private static final Logger log = LoggerFactory.getLogger(ModelManager.class);

    public record ModelSpec(String name, String url, String sha256, String filename) {
    }

    private final AgentHub agentHub;
    private final FeHub feHub;
    private final DataDirs dataDirs;
    private final ObjectMapper om;
    private final HttpClient http = HttpClient.newBuilder()
            .followRedirects(HttpClient.Redirect.NORMAL)
            .connectTimeout(Duration.ofSeconds(10))
            .build();

    private final ExecutorService downloader = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "model-downloader");
        t.setDaemon(true);
        return t;
    });

    // ---- 메모리 상태 (this 동기화로 보호) ----
    private List<ModelSpec> specs;                       // 지연 로드 — hello 가 onReady 보다 먼저 올 수 있다
    private final Set<String> fileReady = new HashSet<>();     // 파일 존재 + sha256 통과
    private final Set<String> downloading = new HashSet<>();   // 다운로더 스레드가 확보 중인 것 (GET /api/models 표시용)
    private final Set<String> loadRequested = new HashSet<>(); // 이번 hello 사이클에 model_load 를 보낸 것
    private final Set<String> loaded = new HashSet<>();        // AI 가 model_loaded 로 확인한 것
    private boolean agentWaiting;
    private boolean allLoadedFired;
    private Runnable allLoadedCallback;

    public ModelManager(AgentHub agentHub, FeHub feHub, DataDirs dataDirs, ObjectMapper om) {
        this.agentHub = agentHub;
        this.feHub = feHub;
        this.dataDirs = dataDirs;
        this.om = om;
    }

    /** 기동 시 비동기로 모델 파일을 확보한다 (다운로드·검증). */
    @EventListener(ApplicationReadyEvent.class)
    @Order(30)
    public void onReady() {
        downloader.submit(this::ensureAll);
    }

    /**
     * AI hello 이후 호출 — 준비된 모델마다 model_load 를 보내고,
     * 전 모델이 로드되면(또는 모델이 0개면) onAllLoaded 를 정확히 1회 실행한다.
     */
    public synchronized void beginLoading(Runnable onAllLoaded) {
        this.allLoadedCallback = onAllLoaded;
        this.agentWaiting = true;
        this.allLoadedFired = false;
        loaded.clear();
        loadRequested.clear();
        List<ModelSpec> list = specs();
        if (list.isEmpty()) {
            fireAllLoaded(); // 모델 0개 — 즉시 '전부 준비됨'
            return;
        }
        for (ModelSpec spec : list) {
            if (fileReady.contains(spec.name())) {
                requestLoad(spec);
            }
        }
    }

    /** AI 의 model_loaded 수신. */
    public synchronized void onModelLoaded(String name) {
        loaded.add(name);
        feHub.send("model_ready", Map.of());
        if (agentWaiting && !allLoadedFired && loadedAll()) {
            fireAllLoaded();
        }
    }

    /** AI 의 model_load_failed 수신 — FE 안내(재다운로드 유도). */
    public void onModelLoadFailed(String name, String reason) {
        log.warn("모델 {} 적재 실패: {}", name, reason);
        feHub.send("model_error", Map.of("name", name, "reason", reason));
    }

    /** AI 연결이 끊기면 다음 hello 에서 처음부터 반복한다. */
    public synchronized void reset() {
        agentWaiting = false;
        allLoadedFired = false;
        allLoadedCallback = null;
        loaded.clear();
        loadRequested.clear();
    }

    /** GET /api/models — 모델별 상태 [{name, filename, fileReady, loaded, downloading}]. */
    public synchronized List<Map<String, Object>> status() {
        List<Map<String, Object>> out = new ArrayList<>();
        for (ModelSpec spec : specs()) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("name", spec.name());
            m.put("filename", spec.filename());
            m.put("fileReady", fileReady.contains(spec.name()));
            m.put("loaded", loaded.contains(spec.name()));
            m.put("downloading", downloading.contains(spec.name()));
            out.add(m);
        }
        return out;
    }

    /**
     * POST /api/models/{name}/redownload — 기존 파일을 버리고 다시 받는다 (흐름도 01 [정정 3-2] 재다운로드 유도의 목적지).
     * 비동기다. 진행은 FE 에 model_progress, 완료는 model_downloaded, 실패는 model_error 로 간다.
     * 파일이 준비되면 AI 가 접속해 있을 때 model_load 를 다시 보낸다. 이미 받는 중이면 다시 큐에 넣지 않는다.
     */
    public void redownload(String name) {
        ModelSpec spec = specs().stream().filter(s -> s.name().equals(name)).findFirst()
                .orElseThrow(() -> new ApiException(ErrorCode.NOT_FOUND, "알 수 없는 모델입니다: " + name));
        synchronized (this) {
            if (downloading.contains(name)) {
                return;
            }
            downloading.add(name);
            fileReady.remove(name);
            loaded.remove(name);
            loadRequested.remove(name);
        }
        downloader.submit(() -> ensureAndPublish(spec, true));
    }

    // ------------------------------------------------------------------ 내부

    private boolean loadedAll() {
        return specs().stream().map(ModelSpec::name).allMatch(loaded::contains);
    }

    private void fireAllLoaded() {
        allLoadedFired = true;
        Runnable cb = allLoadedCallback;
        if (cb != null) {
            cb.run();
        }
    }

    private void requestLoad(ModelSpec spec) {
        if (loadRequested.add(spec.name())) {
            Path path = dataDirs.models().resolve(spec.filename()).toAbsolutePath();
            agentHub.send("model_load", Map.of("name", spec.name(), "path", path.toString()));
        }
    }

    private void ensureAll() {
        for (ModelSpec spec : specs()) {
            synchronized (this) {
                downloading.add(spec.name());
            }
            ensureAndPublish(spec, false);
        }
    }

    /**
     * 다운로더 스레드 전용. 호출 전에 downloading 에 이름이 들어 있어야 하고 끝나면 뺀다.
     * 파일이 준비되면 fileReady 에 올리고, 실제로 내려받은 경우 FE 에 model_downloaded 를 보낸다.
     * AI 가 기다리고 있으면(hello 가 먼저 온 경우, 재다운로드) 적재 지시도 다시 보낸다.
     */
    private void ensureAndPublish(ModelSpec spec, boolean force) {
        EnsureResult result;
        try {
            result = ensure(spec, force);
        } finally {
            synchronized (this) {
                downloading.remove(spec.name());
            }
        }
        if (result == EnsureResult.FAILED) {
            return;
        }
        if (result == EnsureResult.DOWNLOADED) {
            feHub.send("model_downloaded", Map.of("name", spec.name()));
        }
        synchronized (this) {
            fileReady.add(spec.name());
            if (agentWaiting) {
                requestLoad(spec);
            }
        }
    }

    private enum EnsureResult { READY, DOWNLOADED, FAILED }

    /** 존재+sha256 일치면 스킵(force 면 무조건 다시 받는다), 아니면 다운로드. 불일치·실패는 1회 재시도 후 model_error. */
    private EnsureResult ensure(ModelSpec spec, boolean force) {
        Path target = dataDirs.models().resolve(spec.filename());
        if (!force) {
            try {
                if (Files.isRegularFile(target) && spec.sha256().equalsIgnoreCase(sha256Of(target))) {
                    return EnsureResult.READY;
                }
            } catch (Exception e) {
                log.warn("모델 {} 기존 파일 검증 실패 — 다시 받습니다", spec.name(), e);
            }
        }
        String lastReason = "다운로드에 실패했습니다";
        for (int attempt = 1; attempt <= 2; attempt++) {
            try {
                download(spec, target);
                return EnsureResult.DOWNLOADED;
            } catch (Exception e) {
                lastReason = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
                log.warn("모델 {} 다운로드 {}차 실패: {}", spec.name(), attempt, lastReason);
            }
        }
        feHub.send("model_error", Map.of("name", spec.name(), "reason", lastReason));
        return EnsureResult.FAILED;
    }

    private void download(ModelSpec spec, Path target) throws Exception {
        Path tmp = Files.createTempFile(dataDirs.tmp(), "model-" + spec.name() + "-", ".part");
        try {
            HttpRequest req = HttpRequest.newBuilder(URI.create(spec.url()))
                    .timeout(Duration.ofMinutes(30))
                    .GET().build();
            HttpResponse<InputStream> res = http.send(req, HttpResponse.BodyHandlers.ofInputStream());
            if (res.statusCode() != 200) {
                throw new IOException("HTTP " + res.statusCode());
            }
            long total = res.headers().firstValueAsLong("Content-Length").orElse(-1);
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            try (InputStream in = res.body(); OutputStream out = Files.newOutputStream(tmp)) {
                byte[] buf = new byte[64 * 1024];
                long done = 0;
                int lastPct = -1;
                int read;
                while ((read = in.read(buf)) != -1) {
                    out.write(buf, 0, read);
                    md.update(buf, 0, read);
                    done += read;
                    if (total > 0) {
                        int pct = (int) (done * 100 / total) / 5 * 5; // 5% 단위
                        if (pct > lastPct) {
                            lastPct = pct;
                            feHub.send("model_progress", Map.of("name", spec.name(), "pct", pct));
                        }
                    }
                }
            }
            String hex = toHex(md.digest());
            if (!hex.equalsIgnoreCase(spec.sha256())) {
                throw new IOException("sha256 이 일치하지 않습니다");
            }
            Files.move(tmp, target, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
        } finally {
            Files.deleteIfExists(tmp);
        }
    }

    private synchronized List<ModelSpec> specs() {
        if (specs != null) {
            return specs;
        }
        try {
            JsonNode root;
            Path local = dataDirs.root().resolve("models.json");
            if (Files.isRegularFile(local)) {
                root = om.readTree(Files.readAllBytes(local));
            } else {
                try (InputStream in = new ClassPathResource("models.json").getInputStream()) {
                    root = om.readTree(in);
                }
            }
            List<ModelSpec> list = new ArrayList<>();
            for (JsonNode m : root.path("models")) {
                list.add(new ModelSpec(
                        m.path("name").asText(),
                        m.path("url").asText(),
                        m.path("sha256").asText(),
                        m.path("filename").asText()));
            }
            specs = List.copyOf(list);
        } catch (Exception e) {
            log.error("models.json 읽기 실패 — 모델 0개로 간주합니다", e);
            specs = List.of();
        }
        return specs;
    }

    private static String sha256Of(Path file) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        try (InputStream in = Files.newInputStream(file)) {
            byte[] buf = new byte[64 * 1024];
            int read;
            while ((read = in.read(buf)) != -1) {
                md.update(buf, 0, read);
            }
        }
        return toHex(md.digest());
    }

    private static String toHex(byte[] bytes) {
        StringBuilder sb = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) {
            sb.append(Character.forDigit((b >> 4) & 0xF, 16)).append(Character.forDigit(b & 0xF, 16));
        }
        return sb.toString();
    }

    @PreDestroy
    void shutdown() {
        downloader.shutdownNow();
    }
}
