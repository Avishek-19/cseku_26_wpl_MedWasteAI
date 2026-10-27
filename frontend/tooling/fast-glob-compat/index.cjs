"use strict";
// Next's ESLint plugin uses only globSync(pattern, { onlyDirectories: true }).
// Node's built-in glob avoids the vulnerable braces/micromatch dependency tree.
const fs = require("node:fs");
const path = require("node:path");
function globSync(patterns, options = {}) {
  const cwd = options.cwd || process.cwd();
  const matches = [...new Set([patterns].flat().flatMap(pattern =>
    [...fs.globSync(pattern, { cwd, exclude: options.ignore || [] })]))];
  return matches.filter(value => {
    const full = path.resolve(cwd, value);
    try { return !options.onlyDirectories || fs.statSync(full).isDirectory(); }
    catch { return false; }
  }).map(value => options.absolute ? path.resolve(cwd, value) : value);
}
module.exports = { globSync, sync: globSync };
