import axios from "axios";
import { logCommunication } from '../utils/communicationLogger';

// BE 주소는 로컬 고정값 (agents.md 1장). 배포 환경별 주소 분기 로직을 만들지 않는다.
// FE 쪽 REST는 인증 헤더가 필요 없다 (agents.md 4.1) - Authorization 등을 붙이지 않는다.
const httpClient = axios.create({
  baseURL: "http://127.0.0.1:8080",
  timeout: 10000,
});

httpClient.interceptors.request.use((config) => {
  logCommunication('REST', '발신', `${config.method.toUpperCase()} ${config.url}`, config.data ?? {});
  return config;
});

httpClient.interceptors.response.use((response) => {
  logCommunication('REST', '수신', `${response.status} ${response.config.url}`, response.data);
  return response;
}, (error) => {
  logCommunication('REST', '실패', error.config?.url ?? '요청 실패', {
    code: error.response?.data?.code ?? 'NETWORK_ERROR',
    message: error.response?.data?.message ?? '백엔드 연결 실패',
  });
  return Promise.reject(error);
});

export default httpClient;
