const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { getRootDirs } = require('@next/eslint-plugin-next/dist/utils/get-root-dirs.js');

test('Next ESLint directory lookup keeps exact project roots', () => {
  const root = process.cwd();
  assert.deepEqual(getRootDirs({ cwd: root, settings: { next: { rootDir: root } } }), [root]);
});

test('Next ESLint directory globs exclude files', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'medwaste-glob-'));
  try {
    fs.mkdirSync(path.join(root, 'app-one')); fs.mkdirSync(path.join(root, 'app-two'));
    fs.writeFileSync(path.join(root, 'app-file.txt'), 'not a directory');
    const found = getRootDirs({ cwd: root, settings: { next: { rootDir: path.join(root, 'app-*') } } });
    assert.deepEqual(found.sort(), [path.join(root, 'app-one'), path.join(root, 'app-two')].sort());
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
