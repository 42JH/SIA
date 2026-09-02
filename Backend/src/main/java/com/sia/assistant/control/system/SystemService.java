package com.sia.assistant.control.system;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.control.window.User32Ext;
import java.util.Map;
import org.springframework.stereotype.Service;

/**
 * system.lock 의 실행부 — LockWorkStation (와이어프레임 기능 선택 드롭다운 "시스템 > 화면 잠금").
 * 세션을 잠글 뿐 로그아웃·종료가 아니다 — 데이터 손실이 없어 확인 게이트(C) 대상이 아니다.
 */
@Service
public class SystemService {

    public Map<String, Object> lock() {
        if (!User32Ext.INSTANCE.LockWorkStation()) {
            throw new ApiException(ErrorCode.INTERNAL_ERROR, "화면 잠금에 실패했습니다");
        }
        return Map.of("locked", true);
    }
}
