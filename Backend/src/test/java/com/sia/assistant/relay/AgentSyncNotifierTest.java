package com.sia.assistant.relay;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.sia.assistant.profile.CalibProfileService;
import com.sia.assistant.profile.VoiceProfileService;
import com.sia.assistant.settings.BlobService;
import com.sia.assistant.settings.GestureService;
import com.sia.assistant.settings.SettingsService;
import com.sia.assistant.ws.AgentHub;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import tools.jackson.databind.ObjectMapper;

/**
 * AI 동기화 페이로드의 blobs 형식 — 커스텀 제스처 템플릿은 제스처별 참조 목록 gestures[] 이고
 * 옛 gestures_custom 단일 해시는 없다 (흐름도 03 정합, 2026-09-02).
 */
class AgentSyncNotifierTest {

    @Test
    @SuppressWarnings("unchecked")
    @DisplayName("blobs 는 {gestures: [{id, name, sha256}], wakeword, voice, calib} 순서의 네 키다")
    void blobsShape() {
        BlobService blobs = mock(BlobService.class);
        VoiceProfileService voices = mock(VoiceProfileService.class);
        CalibProfileService calibs = mock(CalibProfileService.class);
        GestureService gestures = mock(GestureService.class);
        Map<String, Object> ref = new LinkedHashMap<>();
        ref.put("id", 14L);
        ref.put("name", "손가락 하트");
        ref.put("sha256", "8c22b1de44a0");
        when(gestures.customNpzRefs()).thenReturn(List.of(ref));
        when(blobs.hashes()).thenReturn(Map.of("wakeword", "b02f11ac37d9"));
        when(voices.activeRefOrNull()).thenReturn(null);
        when(calibs.activeRefOrNull()).thenReturn(null);

        AgentSyncNotifier notifier = new AgentSyncNotifier(mock(AgentHub.class), new ObjectMapper(),
                provider(mock(SettingsService.class)), provider(blobs), provider(voices), provider(calibs),
                provider(gestures));

        Map<String, Object> out = notifier.blobs();

        assertThat(out.keySet()).containsExactly("gestures", "wakeword", "voice", "calib");
        assertThat((List<Map<String, Object>>) out.get("gestures")).singleElement()
                .satisfies(g -> assertThat(g).containsEntry("id", 14L).containsEntry("sha256", "8c22b1de44a0"));
        assertThat(out).containsEntry("wakeword", "b02f11ac37d9").containsEntry("voice", null).containsEntry("calib", null);
        assertThat(out).doesNotContainKey("gestures_custom");
    }

    @SuppressWarnings("unchecked")
    private static <T> ObjectProvider<T> provider(T bean) {
        ObjectProvider<T> p = mock(ObjectProvider.class);
        when(p.getObject()).thenReturn(bean);
        return p;
    }
}
