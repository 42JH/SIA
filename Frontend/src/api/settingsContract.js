import { ApiError } from './errors.js';

export function validateSettingsResponse(data) {
  const settings = data?.settings;
  const validDevice = (value) => value === null || typeof value === 'string';
  // TODO(BE): /api/settings가 설정값 대신 JsonNode 내부 속성(nodeType, containerNode 등)을 반환함. 응답 직렬화 수정 필요
  if (!settings || typeof settings.wakeWord !== 'string' || !settings.wakeWord.trim()
    || !Number.isInteger(settings.sessionSeconds) || settings.sessionSeconds < 1
    || typeof settings.autoStart !== 'boolean' || typeof settings.gazeCursor !== 'boolean'
    || !validDevice(settings.micDevice) || !validDevice(settings.cameraDevice)) {
    throw new ApiError('INVALID_SETTINGS_RESPONSE', '백엔드 설정 응답에 필요한 설정값이 없습니다. 백엔드 응답 수정 후 설정 다시 불러오기를 눌러주세요.');
  }
}
