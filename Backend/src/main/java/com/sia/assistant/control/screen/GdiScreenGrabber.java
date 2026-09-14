package com.sia.assistant.control.screen;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sun.jna.Memory;
import com.sun.jna.Pointer;
import com.sun.jna.platform.win32.GDI32;
import com.sun.jna.platform.win32.User32;
import com.sun.jna.platform.win32.WinDef;
import com.sun.jna.platform.win32.WinGDI;
import com.sun.jna.platform.win32.WinNT;
import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import org.springframework.stereotype.Component;

/**
 * GDI BitBlt 로 화면 DC 를 읽는다 — 프로세스가 PER_MONITOR_AWARE_V2 라 GetWindowRect·GetSystemMetrics·화면 DC 가
 * 전부 물리 픽셀이다 (java.awt.Robot 은 논리 좌표로 환산해 배율 모니터에서 어긋난다).
 */
@Component
public class GdiScreenGrabber implements ScreenGrabber {

    private static final int SM_XVIRTUALSCREEN = 76;
    private static final int SM_YVIRTUALSCREEN = 77;
    private static final int SM_CXVIRTUALSCREEN = 78;
    private static final int SM_CYVIRTUALSCREEN = 79;
    /** BitBlt 래스터 연산 — 원본을 그대로 복사. */
    private static final int SRCCOPY = 0x00CC0020;

    private static final String FAIL_MESSAGE = "화면 캡처에 실패했습니다. 잠시 후 다시 시도해주세요";

    @Override
    public Rectangle virtualScreen() {
        User32 u = User32.INSTANCE;
        return new Rectangle(u.GetSystemMetrics(SM_XVIRTUALSCREEN), u.GetSystemMetrics(SM_YVIRTUALSCREEN),
                u.GetSystemMetrics(SM_CXVIRTUALSCREEN), u.GetSystemMetrics(SM_CYVIRTUALSCREEN));
    }

    @Override
    public Rectangle windowRect(long hwnd) {
        WinDef.HWND h = new WinDef.HWND(new Pointer(hwnd));
        if (!User32.INSTANCE.IsWindow(h)) {
            return null;
        }
        WinDef.RECT rect = new WinDef.RECT();
        if (!User32.INSTANCE.GetWindowRect(h, rect)) {
            return null;
        }
        return new Rectangle(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top);
    }

    @Override
    public BufferedImage grab(Rectangle r) {
        if (r == null || r.width <= 0 || r.height <= 0) {
            throw new ApiException(ErrorCode.INTERNAL_ERROR, FAIL_MESSAGE, "캡처 영역이 비어 있습니다");
        }
        WinDef.HDC screen = User32.INSTANCE.GetDC(null);
        if (screen == null) {
            throw new ApiException(ErrorCode.INTERNAL_ERROR, FAIL_MESSAGE, "GetDC 실패");
        }
        WinDef.HDC mem = null;
        WinDef.HBITMAP bitmap = null;
        try {
            mem = GDI32.INSTANCE.CreateCompatibleDC(screen);
            bitmap = GDI32.INSTANCE.CreateCompatibleBitmap(screen, r.width, r.height);
            if (mem == null || bitmap == null) {
                throw new ApiException(ErrorCode.INTERNAL_ERROR, FAIL_MESSAGE, "GDI 객체 생성 실패");
            }
            WinNT.HANDLE previous = GDI32.INSTANCE.SelectObject(mem, bitmap);
            boolean copied = GDI32.INSTANCE.BitBlt(mem, 0, 0, r.width, r.height, screen, r.x, r.y, SRCCOPY);
            GDI32.INSTANCE.SelectObject(mem, previous);
            if (!copied) {
                throw new ApiException(ErrorCode.INTERNAL_ERROR, FAIL_MESSAGE, "BitBlt 실패");
            }

            WinGDI.BITMAPINFO info = new WinGDI.BITMAPINFO();
            info.bmiHeader.biWidth = r.width;
            info.bmiHeader.biHeight = -r.height; // 음수 = top-down 행 순서
            info.bmiHeader.biPlanes = 1;
            info.bmiHeader.biBitCount = 32;
            info.bmiHeader.biCompression = WinGDI.BI_RGB;
            Memory buffer = new Memory((long) r.width * r.height * 4);
            int lines = GDI32.INSTANCE.GetDIBits(screen, bitmap, 0, r.height, buffer, info, WinGDI.DIB_RGB_COLORS);
            if (lines == 0) {
                throw new ApiException(ErrorCode.INTERNAL_ERROR, FAIL_MESSAGE, "GetDIBits 실패");
            }
            int[] pixels = buffer.getIntArray(0, r.width * r.height);
            BufferedImage image = new BufferedImage(r.width, r.height, BufferedImage.TYPE_INT_RGB);
            image.setRGB(0, 0, r.width, r.height, pixels, 0, r.width);
            return image;
        } finally {
            if (bitmap != null) {
                GDI32.INSTANCE.DeleteObject(bitmap);
            }
            if (mem != null) {
                GDI32.INSTANCE.DeleteDC(mem);
            }
            User32.INSTANCE.ReleaseDC(null, screen);
        }
    }
}
