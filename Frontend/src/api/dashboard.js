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
export const fetchDashboardAccuracy = (period, extra = {}) => get('/api/dashboard/accuracy', { period, ...extra });
export const fetchDashboardLatency = (period, extra = {}) => get('/api/dashboard/latency', { period, ...extra });
export const fetchDashboardUsage = (period, extra = {}) => get('/api/dashboard/usage', { period, ...extra });
export const fetchDashboardApps = (period, extra = {}) => get('/api/dashboard/apps', { period, limit: 10, ...extra });
