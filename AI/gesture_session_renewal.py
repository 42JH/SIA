"""Read-only BE policy cache; never queue or execute gestures."""
import threading
import time


class GestureRenewalPolicy:
    def __init__(self, read_json, clock=time.monotonic):
        self.read_json = read_json
        self.clock = clock
        self._lock = threading.Lock()
        self._generation = 0
        self._snapshot = None

    def invalidate(self):
        with self._lock:
            self._generation += 1
            self._snapshot = None

    def refresh(self):
        with self._lock:
            generation = self._generation
        tools = {t['name']: t['sessionRequired']
                 for t in self.read_json('/api/tools?all=true')}
        rows, page = [], 0
        while True:
            result = self.read_json(f'/api/gestures?page={page}&size=100')
            items = result['items']
            rows.extend(items)
            if len(rows) >= result['total']:
                break
            if not items:
                raise ValueError('Incomplete gesture policy response')
            page += 1
        with self._lock:
            if generation == self._generation:
                self._snapshot = (self.clock(), tools, rows)

    def can_renew(self, name, context, context_chain=None):
        """Only a fresh, unambiguous, enabled mapping is a renewal candidate."""
        with self._lock:
            snapshot = self._snapshot
        if snapshot is None or self.clock() - snapshot[0] > 3.0:
            return False
        _, tools, rows = snapshot
        chain = [context] if context is not None else context_chain
        if chain is None:
            return False
        candidates = sorted((r for r in rows if r['name'] == name), key=lambda r: r['id'])
        selected = None
        for ctx in [c for c in chain if c] + [None]:
            selected = next((r for r in candidates if r.get('context') == ctx), None)
            if selected is not None:
                break
        return bool(selected and selected.get('enabled') is True
                    and selected.get('steps')
                    and all(s.get('tool') in tools for s in selected['steps']))


def foreground_context_chain(hwnd=None):
    """Mirror BE ContextService.chainFor; return None if unavailable."""
    try:
        import ctypes
        from ctypes import wintypes
        api = ctypes.windll.user32
        api.GetForegroundWindow.restype = wintypes.HWND
        api.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        target = hwnd if hwnd is not None else api.GetForegroundWindow()
        if not target:
            return []
        title = ctypes.create_unicode_buffer(32768)
        api.GetWindowTextW(target, title, len(title))
        return ['youtube', 'video'] if 'youtube' in title.value.lower() else []
    except (AttributeError, OSError, TypeError):
        return None
