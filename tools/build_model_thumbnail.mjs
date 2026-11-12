import {build} from '../apps/workbench/node_modules/vite/dist/node/index.js';
import {fileURLToPath} from 'node:url';

const root=fileURLToPath(new URL('../apps/workbench/',import.meta.url));
await build({configFile:false,root,publicDir:false,build:{
  outDir:fileURLToPath(new URL('../output/compact-workbench-20261021/workbench-dist/',import.meta.url)),
  emptyOutDir:false,
  lib:{entry:fileURLToPath(new URL('../apps/workbench/src/modelThumbnailRenderer.ts',import.meta.url)),
    formats:['iife'],name:'OntoVisModelThumbnail',fileName:()=> 'model-thumbnail-renderer.js'},
}});
