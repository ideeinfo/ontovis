import assert from 'node:assert/strict';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';
import {build} from 'vite';

test('the assistant retains captions and actions without opening the policy page first',async()=>{
 const bundle=await build({root:fileURLToPath(new URL('../',import.meta.url)),configFile:fileURLToPath(new URL('../vite.config.ts',import.meta.url)),logLevel:'silent',publicDir:false,build:{write:false,emptyOutDir:false,reportCompressedSize:false}});
 const assets=(Array.isArray(bundle)?bundle:[bundle]).flatMap(result=>result.output).filter(item=>item.type==='asset'&&item.fileName.endsWith('.css'));
 const assistant=assets.filter(item=>/\.as-panel\s*\{/.test(String(item.source)));
 assert.ok(assistant.length,'The assistant must have its own styles');
 const css=assistant.map(item=>String(item.source)).join('\n');
 assert.match(css,/(?:^|\})\.ap-caption\s*\{[^}]*font-size:11px/,'Assistant captions must not depend on loading the policy stylesheet');
 assert.match(css,/(?:^|\})\.ap-actions\s*\{[^}]*display:flex/,'Assistant actions must retain their shared layout');
 assert.doesNotMatch(css,/\.ap-page\s*\{/,'Policy page layout must not leak through the assistant stylesheet');
});
