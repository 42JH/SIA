import { on } from './eventBus';
import { sendOnboarding } from './onboarding';
import { useVoiceStore } from '../store/voiceStore';

let initialized = false;

export function initializeVoiceEvents() {
  if (initialized) return;
  initialized = true;
  const store = () => useVoiceStore.getState();
  on('voice_sentence', (data) => {
    if (store().stage !== 'list') store().receiveSentence(data);
  });
  on('voice_progress', (data) => {
    if (store().stage !== 'list') store().receiveProgress(data);
  });
  on('voice_sentence_rejected', (data) => {
    const voice = store();
    const currentN = Number(voice.sentence?.n) || Math.min(voice.completed + 1, voice.total);
    if (voice.stage !== 'list' && data.tempId === voice.tempId && Number(data.n) === currentN) {
      voice.receiveSentenceRejected(data);
    }
  });
  on('voice_quality_warn', (data) => {
    if (store().stage !== 'list') store().receiveWarning(data);
  });
  on('voice_review', (data) => {
    if (store().stage !== 'list') store().receiveReview(data);
  });
  on('voice_saved', () => {
    if (store().stage !== 'list') store().receiveSaved();
  });
  on('voice_reg_denied', ({ message }) => store().change({ stage: 'list', pending: false, error: message }));
  on('error', ({ message, of }) => {
    if (of?.startsWith('voice_')) store().change({ pending: false, error: message });
  });
}

export function sendVoice(type, data = {}) {
  sendOnboarding(type, data);
}
