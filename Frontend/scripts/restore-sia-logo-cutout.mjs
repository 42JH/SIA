import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const sharp = require('sharp');
const sourcePath = 'C:/Users/SSAFY/AppData/Local/Temp/codex-clipboard-7585af22-e0fe-429c-9150-a566dabf7d0e.png';
const outputPath = path.resolve('design/SIA-logo-original-cutout.png');

const { data, info } = await sharp(sourcePath).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
let minX = info.width;
let minY = info.height;
let maxX = 0;
let maxY = 0;

for (let y = 0; y < info.height; y += 1) {
  for (let x = 0; x < info.width; x += 1) {
    const index = (y * info.width + x) * 4;
    const r = data[index];
    const g = data[index + 1];
    const b = data[index + 2];
    const blueBias = b - (r + g) / 2;
    if (blueBias > 7 && r < 105 && g < 125 && b < 155) {
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  }
}

if (minX > maxX || minY > maxY) throw new Error('SIA logo pixels were not detected.');

const padding = 6;
const left = Math.max(0, minX - padding);
const top = Math.max(0, minY - padding);
const width = Math.min(info.width, maxX + padding + 1) - left;
const height = Math.min(info.height, maxY + padding + 1) - top;
const cropped = await sharp(sourcePath).extract({ left, top, width, height }).ensureAlpha().raw().toBuffer({ resolveWithObject: true });

for (let i = 0; i < cropped.data.length; i += 4) {
  const r = cropped.data[i];
  const g = cropped.data[i + 1];
  const b = cropped.data[i + 2];
  const blueBias = b - (r + g) / 2;
  const darkness = Math.max(0, 155 - (r * .22 + g * .56 + b * .22));
  const alpha = Math.max(0, Math.min(255, (blueBias - 3) * 20, darkness * 5));
  cropped.data[i + 3] = alpha;
}

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
await sharp(cropped.data, { raw: cropped.info }).png().toFile(outputPath);
console.log(`Restored exact SIA logo cutout: ${width}x${height}`);
