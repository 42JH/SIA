# -*- coding: utf-8 -*-
"""화면 오버레이: 응시 링 + 상태 배지 (둘 다 click-through, 포커스 불가).

- 링: Active 중 응시 지점 표시 (Vision Pro의 하이라이트 느낌)
- 배지: 화면 상단 중앙에 PASSIVE/ACTIVE/PINCH 상시 표시 — 미리보기 창을
  안 봐도 현재 상태를 알 수 있게 (오작동 방지 UX의 일부)

tkinter는 스레드 안전하지 않으므로 tk 호출은 전부 데몬 스레드 하나에서만.
밖에서는 좌표·상태 문자열만 넘긴다.
"""
import ctypes
import threading
import time

RING = 26  # 반지름 px
BADGE_W, BADGE_H = 150, 28
TOAST_W, TOAST_H = 760, 38
PANEL_W, PANEL_H = 560, 300
STATE_COLORS = {
    "PASSIVE": "#8a8a8a", "ACTIVE": "#7fd47f", "PINCH": "#7fb2ff", "DRAG": "#ffb27f",
    # 자비스(assistant) 모드 상태
    "IDLE": "#8a8a8a", "LISTENING": "#ff9a9a", "THINKING": "#ffd47f",
}

_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000


def _click_through(tk_window):
    """래퍼 HWND에 click-through/포커스불가 스타일 적용. 최초 map 후에 호출할 것."""
    hwnd = ctypes.windll.user32.GetParent(tk_window.winfo_id())
    if hwnd:
        style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(
            hwnd, _GWL_EXSTYLE,
            style | _WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE,
        )


class Overlay:
    def __init__(self):
        self._ring_target = None  # (x, y) 화면 px, None이면 숨김
        self._state = "PASSIVE"
        self._suffix = ""        # 배지 상태 뒤에 붙는 짧은 텍스트 (세션 남은 시간 등)
        self._toast = ("", 0.0)  # (텍스트, 만료 시각)
        self._panel = ("", 0.0)  # 긴 응답용 플로팅 패널
        self._lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    def show_ring(self, x, y):
        with self._lock:
            self._ring_target = (int(x), int(y))

    def hide_ring(self):
        with self._lock:
            self._ring_target = None

    def set_state(self, state, suffix=""):
        with self._lock:
            self._state = state
            self._suffix = suffix

    def toast(self, text, seconds=4.0):
        """상단에 비서 응답/알림 한 줄을 잠깐 띄운다."""
        with self._lock:
            self._toast = (str(text)[:80], time.monotonic() + seconds)

    def panel(self, text, seconds=18.0):
        """긴 응답(요약 등)용 플로팅 패널 — 우상단에 여러 줄 표시."""
        with self._lock:
            self._panel = (str(text)[:800], time.monotonic() + seconds)

    # --- 이하 전부 오버레이 스레드 내부 ---
    def _run(self):
        import tkinter as tk

        size = RING * 2 + 8
        root = tk.Tk()  # 링 창
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-transparentcolor", "black")
        root.geometry(f"{size}x{size}+20000+20000")  # 화면 밖에서 최초 map
        canvas = tk.Canvas(root, width=size, height=size, bg="black", highlightthickness=0)
        canvas.pack()
        pad = 4
        canvas.create_oval(pad, pad, size - pad, size - pad, outline="#7fd4ff", width=3)

        badge = tk.Toplevel(root)  # 상태 배지 창
        badge.overrideredirect(True)
        badge.attributes("-topmost", True)
        badge.attributes("-transparentcolor", "black")
        bx = (root.winfo_screenwidth() - BADGE_W) // 2
        badge.geometry(f"{BADGE_W}x{BADGE_H}+{bx}+6")
        bc = tk.Canvas(badge, width=BADGE_W, height=BADGE_H, bg="black", highlightthickness=0)
        bc.pack()
        dot = bc.create_oval(8, 8, BADGE_H - 8, BADGE_H - 8, fill=STATE_COLORS["PASSIVE"], outline="")
        label = bc.create_text(BADGE_H + 4, BADGE_H // 2, anchor="w", text="PASSIVE",
                               fill=STATE_COLORS["PASSIVE"], font=("Segoe UI", 10, "bold"))

        toast = tk.Toplevel(root)  # 비서 응답 토스트
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.attributes("-transparentcolor", "black")
        tx = (root.winfo_screenwidth() - TOAST_W) // 2
        toast.geometry(f"{TOAST_W}x{TOAST_H}+{tx}+{6 + BADGE_H + 6}")
        tc = tk.Canvas(toast, width=TOAST_W, height=TOAST_H, bg="black", highlightthickness=0)
        tc.pack()
        tc.create_rectangle(0, 0, TOAST_W, TOAST_H, fill="#141414", outline="#3a3a3a")
        toast_label = tc.create_text(TOAST_W // 2, TOAST_H // 2, text="",
                                     fill="#e8e8e8", font=("Malgun Gothic", 11))

        panel = tk.Toplevel(root)  # 긴 응답(요약) 플로팅 패널 — 우상단
        panel.overrideredirect(True)
        panel.attributes("-topmost", True)
        panel.attributes("-transparentcolor", "black")
        panel.geometry(f"{PANEL_W}x{PANEL_H}+{root.winfo_screenwidth() - PANEL_W - 16}+{6 + BADGE_H + 6}")
        pc = tk.Canvas(panel, width=PANEL_W, height=PANEL_H, bg="black", highlightthickness=0)
        pc.pack()
        pc.create_rectangle(0, 0, PANEL_W - 1, PANEL_H - 1, fill="#141414", outline="#3a3a3a")
        panel_label = pc.create_text(16, 14, anchor="nw", text="", width=PANEL_W - 32,
                                     fill="#e8e8e8", font=("Malgun Gothic", 11))

        # 래퍼 HWND는 최초 map 후에야 생기므로 update()로 먼저 map시킨다
        root.update_idletasks()
        root.update()
        _click_through(root)
        _click_through(badge)
        _click_through(toast)
        _click_through(panel)
        root.withdraw()
        toast.withdraw()
        panel.withdraw()

        pos = [0.0, 0.0]

        def tick():
            with self._lock:
                target, state, suffix = self._ring_target, self._state, self._suffix
                toast_text, toast_until = self._toast
                panel_text, panel_until = self._panel
            now = time.monotonic()
            if toast_text and now < toast_until:
                tc.itemconfigure(toast_label, text=toast_text)
                toast.deiconify()
            else:
                toast.withdraw()
            if panel_text and now < panel_until:
                pc.itemconfigure(panel_label, text=panel_text)
                panel.deiconify()
            else:
                panel.withdraw()
            if target is None:
                root.withdraw()
            else:
                # 표시 좌표만 lerp — 원본 신호는 건드리지 않고 눈에만 부드럽게
                pos[0] += (target[0] - pos[0]) * 0.35
                pos[1] += (target[1] - pos[1]) * 0.35
                root.geometry(f"+{int(pos[0]) - size // 2}+{int(pos[1]) - size // 2}")
                root.deiconify()
            color = STATE_COLORS.get(state, "#8a8a8a")
            bc.itemconfigure(dot, fill=color)
            bc.itemconfigure(label, text=state + suffix, fill=color)
            root.after(30, tick)

        tick()
        root.mainloop()


GazeRing = Overlay  # 하위 호환 별칭
