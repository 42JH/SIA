import httpClient from './httpClient';
import { parseApiError } from './errors';

async function request(config) {
  try {
    return (await httpClient(config)).data;
  } catch (error) {
    throw parseApiError(error);
  }
}

export const fetchGestures = (params = {}) => request({ method: 'get', url: '/api/gestures', params: { size: 100, ...params } });
export async function fetchAllGestures(params = {}) {
  const first = await fetchGestures({ ...params, page: 0 });
  const items = [...(first.items || [])];
  const pages = Math.ceil((first.total || 0) / (first.pageSize || 100));
  for (let page = 1; page < pages; page += 1) {
    const next = await fetchGestures({ ...params, page });
    items.push(...(next.items || []));
  }
  return items;
}
export const fetchGesture = (id) => request({ method: 'get', url: `/api/gestures/${id}` });
export const fetchGestureTools = () => request({ method: 'get', url: '/api/tools' });
export const fetchRegisteredApps = () => request({ method: 'get', url: '/api/apps' });
export const setGestureEnabled = (id, enabled) => request({ method: 'patch', url: `/api/gestures/${id}`, data: { enabled } });
export const updateGesture = (id, data) => request({ method: 'put', url: `/api/gestures/${id}`, data });
export const deleteGesture = (id) => request({ method: 'delete', url: `/api/gestures/${id}` });

export const mediaUrl = (path) => path ? new URL(path, 'http://127.0.0.1:61015').href : null;
