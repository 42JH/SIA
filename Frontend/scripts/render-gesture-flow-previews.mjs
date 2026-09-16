import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const sharp = require('sharp');
const sourceDir = path.resolve('design/SIA-gesture-wireframe-editable-svg');
const outputDir = path.resolve('design/gesture-wireframe-qa');

fs.mkdirSync(outputDir, { recursive: true });

const fileNames = fs.readdirSync(sourceDir).filter((name) => name.endsWith('.svg')).sort();
for (const fileName of fileNames) {
  await sharp(path.join(sourceDir, fileName), { density: 96 })
    .png()
    .toFile(path.join(outputDir, fileName.replace(/\.svg$/, '.png')));
}

console.log(`Rendered ${fileNames.length} gesture previews`);
