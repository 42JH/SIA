function clean(value, key = '') {
  if (['detail', 'jpegB64', 'npz', 'sample'].includes(key)) return '[생략]';
  if (typeof value === 'string') return value.length > 1000 ? `${value.slice(0, 1000)}…` : value;
  if (Array.isArray(value)) return value.slice(0, 20).map((item) => clean(item));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([childKey, childValue]) => [childKey, clean(childValue, childKey)]));
  }
  return value;
}

export function logCommunication(channel, direction, type, data = {}) {
  const method = direction === '실패' ? 'error' : 'info';
  console[method](`[${channel} ${direction}] ${type}`, clean(data));
}
