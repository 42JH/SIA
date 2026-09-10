import httpClient from './httpClient';
import { parseApiError } from './errors';

async function get(path, params) {
  try {
    return (await httpClient.get(path, { params })).data;
  } catch (error) {
    throw parseApiError(error);
  }
}

export const fetchDashboardOverview = () => get('/api/dashboard/overview');
export const fetchDashboardAccuracy = (period) => get('/api/dashboard/accuracy', { period });
export const fetchDashboardLatency = (period) => get('/api/dashboard/latency', { period });
export const fetchDashboardUsage = (period) => get('/api/dashboard/usage', { period });
export const fetchDashboardApps = (period) => get('/api/dashboard/apps', { period, limit: 10 });
