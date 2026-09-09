import axios from "axios";

// BE 주소는 로컬 고정값 (agents.md 1장). 배포 환경별 주소 분기 로직을 만들지 않는다.
// FE 쪽 REST는 인증 헤더가 필요 없다 (agents.md 4.1) - Authorization 등을 붙이지 않는다.
const httpClient = axios.create({
  baseURL: "http://127.0.0.1:8080",
  timeout: 10000,
});

export default httpClient;
