import httpClient from './httpClient';
import { parseApiError } from './errors';

async function request(config) {
  try {
    return (await httpClient(config)).data;
  } catch (error) {
    throw parseApiError(error);
  }
}

export const fetchProfiles = (kind) => request({ method: 'get', url: kind === 'mic' ? '/api/voices' : '/api/calibs' });
export const remapDevice = (kind, deviceLabel) => request({ method: 'post', url: '/api/devices/remap', data: { kind, deviceLabel } });
export const activateProfile = (kind, id) => request({ method: 'post', url: `/api/${kind === 'mic' ? 'voices' : 'calibs'}/${id}/activate` });
export const deleteProfile = (kind, id) => request({ method: 'delete', url: `/api/${kind === 'mic' ? 'voices' : 'calibs'}/${id}` });
export const renameVoiceProfile = (id, name) => request({ method: 'patch', url: `/api/voices/${id}`, data: { name } });

export const voiceSampleUrl = (path) => path?.startsWith('/api/')
  ? `${httpClient.defaults.baseURL}${path}`
  : null;
