import { sendFeMessage } from "./feSocket";

export function sendUserChoice(choiceId, selection) {
  const data = selection == null
    ? { choiceId, cancelled: true }
    : { choiceId, n: selection };
  if (!sendFeMessage("user_choice", data)) {
    throw new Error("실시간 연결을 기다린 후 다시 시도해주세요.");
  }
}
