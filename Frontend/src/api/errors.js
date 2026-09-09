// REST 공통 에러 처리 (agents.md 4.4)
// 서버 에러는 {code, message, detail?} 형태로 온다.
// code 기준으로 분기하고, 화면에는 message만 노출한다. detail은 절대 노출하지 않는다.

export class ApiError extends Error {
  constructor(code, message, detail) {
    super(message);
    this.code = code;
    this.detail = detail;
  }
}

export function parseApiError(error) {
  const body = error?.response?.data;
  if (body && body.code && body.message) {
    return new ApiError(body.code, body.message, body.detail);
  }
  // 서버 응답 자체가 없는 경우 (BE 미기동, 네트워크 오류 등)
  return new ApiError("NETWORK_ERROR", "백엔드에 연결할 수 없습니다.", error?.message);
}
