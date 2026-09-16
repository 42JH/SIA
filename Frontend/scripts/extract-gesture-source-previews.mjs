import fs from 'node:fs';
import path from 'node:path';

const sourceDir = 'C:/Users/SSAFY/Desktop/시안/gesture';
const outputDir = path.resolve('design/gesture-source-previews');

fs.mkdirSync(outputDir, { recursive: true });

for (const fileName of fs.readdirSync(sourceDir).filter((name) => name.endsWith('.svg'))) {
  const svg = fs.readFileSync(path.join(sourceDir, fileName), 'utf8');
  const match = svg.match(/<image[^>]+href="data:image\/png;base64,([^"]+)/);
  if (!match) continue;
  fs.writeFileSync(
    path.join(outputDir, fileName.replace(/\.svg$/, '.png')),
    Buffer.from(match[1], 'base64'),
  );
}

console.log(`Extracted ${fs.readdirSync(outputDir).length} gesture previews`);
