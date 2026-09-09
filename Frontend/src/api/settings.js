import httpClient from "./httpClient";
import { ApiError, parseApiError } from "./errors";
import { validateSettingsResponse } from './settingsContract';

// GET /api/settings, PUT /api/settings (agents.md 4.2)
export async function fetchSettings() {
  try {
    const { data } = await httpClient.get("/api/settings");
    validateSettingsResponse(data);
    return data;
  } catch (error) {
    throw error instanceof ApiError ? error : parseApiError(error);
  }
}

export async function updateSettings(payload) {
  try {
    const { data } = await httpClient.put("/api/settings", payload);
    validateSettingsResponse(data);
    return data;
  } catch (error) {
    throw error instanceof ApiError ? error : parseApiError(error);
  }
}
