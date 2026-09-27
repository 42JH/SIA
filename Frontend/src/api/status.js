import httpClient from "./httpClient";
import { parseApiError } from "./errors";

// GET /api/status - 상태 폴링 (agents.md 4.1, 4.2)
export async function fetchStatus() {
  try {
    const { data } = await httpClient.get("/api/status");
    return data;
  } catch (error) {
    throw parseApiError(error);
  }
}
