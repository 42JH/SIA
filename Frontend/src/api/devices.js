import httpClient from './httpClient';
import { parseApiError } from './errors';

export async function fetchDevices() {
  try {
    return (await httpClient.get('/api/devices')).data;
  } catch (error) {
    throw parseApiError(error);
  }
}
