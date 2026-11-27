import assert from 'node:assert/strict';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';
import {build} from 'vite';

test('production chunks retain the material header design after the canvas base styles',async()=>{
  const bundle=await build({root:fileURLToPath(new URL('../',import.meta.url)),
    configFile:fileURLToPath(new URL('../vite.config.ts',import.meta.url)),logLevel:'silent',publicDir:false,
    build:{write:false,emptyOutDir:false,reportCompressedSize:false}});
  const assets=(Array.isArray(bundle)?bundle:[bundle]).flatMap(result=>result.output)
    .filter(item=>item.type==='asset'&&item.fileName.endsWith('.css'));
  const headers=assets.filter(item=>/\.ad-card\s*>\s*header\s*\{/.test(String(item.source)));
  assert.equal(headers.length,1,'The shared base and material header rules must be ordered in one stylesheet');
  const css=String(headers[0].source),computed={};
  for(const [,body] of css.matchAll(/\.ad-card\s*>\s*header\s*\{([^}]+)\}/g)){
    for(const declaration of body.split(';')){
      const colon=declaration.indexOf(':');
      if(colon>0)computed[declaration.slice(0,colon).trim()]=declaration.slice(colon+1).trim();
    }
  }
  assert.match(computed.background,/color-mix\(in srgb,var\(--card-tint/,'Type color must win over the plain canvas surface');
  assert.equal(computed['min-height'],'54px');
  assert.equal(computed.padding,'11px 13px');
  assert.equal(computed.gap,'9px');
});
