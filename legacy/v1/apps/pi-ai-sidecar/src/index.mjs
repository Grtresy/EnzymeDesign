#!/usr/bin/env node

import { loadSidecarConfig, resolveConfigPath } from "./config.mjs";
import { serve } from "./protocol.mjs";

const argv = process.argv.slice(2);
const configPath = resolveConfigPath(argv, process.env);
const sidecarConfig = loadSidecarConfig(configPath);
process.stdin.setEncoding("utf-8");
process.stdin.resume();

await serve(process.stdin, process.stdout, sidecarConfig).catch((error) => {
  process.stderr.write(`${String(error?.stack || error)}\n`);
  process.exitCode = 1;
});
