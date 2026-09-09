import httpClient from './httpClient';
import { parseApiError } from './errors';

export async function registerInstalledApps() {
  try {
    return (await httpClient.post('/api/apps/scan', undefined, { timeout: 30000 })).data;
  } catch (error) {
    throw parseApiError(error);
  }
}

export function sampleUrl(path) {
  return path?.startsWith('/api/voice-reg/') ? `${httpClient.defaults.baseURL}${path}` : null;
}
