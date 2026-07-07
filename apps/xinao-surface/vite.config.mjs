import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const appRoot = dirname(fileURLToPath(import.meta.url));

export default {
  root: resolve(appRoot, 'src/renderer'),
  base: './',
  build: {
    outDir: resolve(appRoot, 'src/renderer-dist'),
    emptyOutDir: true
  }
};
