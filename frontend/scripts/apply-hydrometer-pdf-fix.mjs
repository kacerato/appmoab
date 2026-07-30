import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(scriptDirectory, '..');
const pagePath = path.join(frontendDirectory, 'src/app/(dashboard)/hydrometers/page.tsx');
const blockPath = path.join(scriptDirectory, 'hydrometer-pdf-renderer.block.txt');

const source = await readFile(pagePath, 'utf8');

if (source.includes('const renderStickerBatch = async (')) {
  console.log('Hydrometer PDF renderer already synchronized.');
  process.exit(0);
}

const startMarker = 'const renderStickerSlot =';
const endMarker = '\nexport default function HydrometersPage()';
const start = source.indexOf(startMarker);
const end = source.indexOf(endMarker, start);

if (start < 0 || end < 0) {
  throw new Error('Could not locate the hydrometer PDF renderer block.');
}

const replacement = (await readFile(blockPath, 'utf8')).trimEnd();
const updated = source
  .replace('const STICKER_RENDER_SIZE_PX = 900;', 'const STICKER_RENDER_SIZE_PX = 600;')
  .slice(0, start)
  + replacement
  + source.slice(end);

await writeFile(pagePath, updated, 'utf8');
console.log('Hydrometer PDF renderer synchronized successfully.');
