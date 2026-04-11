import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const dist = resolve(root, "dist");

await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });
await cp(resolve(root, "src"), resolve(dist, "src"), { recursive: true });

const html = await readFile(resolve(root, "index.html"), "utf8");
await writeFile(resolve(dist, "index.html"), html, "utf8");
