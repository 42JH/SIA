package com.sia.assistant.common;

import java.security.MessageDigest;

/** sha256 16진 문자열 — blob·프로필의 ETag/캐시 무효화 기준을 만드는 한 곳. */
public final class Sha256 {

    public static String hex(byte[] payload) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] digest = md.digest(payload);
            StringBuilder sb = new StringBuilder(digest.length * 2);
            for (byte b : digest) {
                sb.append(Character.forDigit((b >> 4) & 0xF, 16)).append(Character.forDigit(b & 0xF, 16));
            }
            return sb.toString();
        } catch (Exception e) {
            throw new ApiException(ErrorCode.INTERNAL_ERROR, "해시 계산에 실패했습니다");
        }
    }

    private Sha256() {
    }
}
