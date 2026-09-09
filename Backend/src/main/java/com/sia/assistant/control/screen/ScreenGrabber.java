package com.sia.assistant.control.screen;

import java.awt.Rectangle;
import java.awt.image.BufferedImage;

/**
 * 화면 픽셀을 읽는 계층. 좌표는 가상 스크린 물리 픽셀이다 — explorer.items 의 bounds, gaze_cursor 와 같은 좌표계.
 * 인식용 스냅샷은 AI 센서가 따로 찍는다(흐름도 02 경계 규칙). 여기는 사용자가 보관할 캡처 결과물을 만드는 쪽이다.
 */
public interface ScreenGrabber {

    /** 전체 가상 스크린 사각형 (모니터 전부). */
    Rectangle virtualScreen();

    /** 창의 화면 사각형. 창이 없거나 죽었으면 null. */
    Rectangle windowRect(long hwnd);

    /** 사각형 영역을 캡처한다. */
    BufferedImage grab(Rectangle rect);
}
