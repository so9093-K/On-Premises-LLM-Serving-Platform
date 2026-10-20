import { promises as fs } from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const root = path.resolve(import.meta.dirname, '..');
const generated = path.resolve(root, '../../src/ai_model_serving/static/control-plane');
const candidate = path.resolve(root, '.build-check');

async function filesUnder(dir) {
  const result = [];
  async function walk(current) {
    for (const entry of await fs.readdir(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) {
        await walk(full);
      } else if (entry.isFile()) {
        result.push(path.relative(dir, full).split(path.sep).join('/'));
      }
    }
  }
  await walk(dir);
  return result.sort();
}

try {
  const [expectedFiles, actualFiles] = await Promise.all([
    filesUnder(generated),
    filesUnder(candidate),
  ]);
  if (JSON.stringify(expectedFiles) !== JSON.stringify(actualFiles)) {
    // 임시 CI 생성물 회수: 최종 변경에서는 삭제한다.
    for (const relative of actualFiles.filter((name) =>
      name === 'index.html' || name === 'asset-manifest.json'
      || (name.startsWith('assets/index-') && name.endsWith('.js'))
    )) {
      const content = await fs.readFile(path.join(candidate, relative), 'utf8');
      for (let i = 0; i < content.length; i += 5000) {
        console.log('ARTGEN_CONSOLE:' + relative + ':' + Math.floor(i / 5000) + ':' + JSON.stringify(content.slice(i, i + 5000)));
      }
    }
    throw new Error(
      `generated Console file-set drift: checked-in=${expectedFiles.join(',')} candidate=${actualFiles.join(',')}`,
    );
  }

  for (const relative of expectedFiles) {
    const [expected, actual] = await Promise.all([
      fs.readFile(path.join(generated, relative)),
      fs.readFile(path.join(candidate, relative)),
    ]);
    if (!expected.equals(actual)) {
      throw new Error(`generated Console artifact drift: ${relative}`);
    }
  }
  console.log(`Control Plane generated artifacts are current (${expectedFiles.length} files).`);
} finally {
  await fs.rm(candidate, { recursive: true, force: true });
}
