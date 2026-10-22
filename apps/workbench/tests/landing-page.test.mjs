import assert from 'node:assert/strict';
import {after, before, test} from 'node:test';
import {fileURLToPath} from 'node:url';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';
import react from '@vitejs/plugin-react';

let vite, LandingPage, PreferencesProvider;
const requests=[];
const fetchDescriptor=Object.getOwnPropertyDescriptor(globalThis,'fetch');

before(async()=>{
  Object.defineProperty(globalThis,'fetch',{configurable:true,value:(...args)=>{
    requests.push(args[0]);throw new Error('The public page must not request remote data while rendering');
  }});
  vite=await createServer({
    root:fileURLToPath(new URL('../',import.meta.url)),configFile:false,plugins:[react()],
    cacheDir:fileURLToPath(new URL('../../../output/login-entry-20261023/_work/landing-ssr-cache',import.meta.url)),
    server:{middlewareMode:true,hmr:false,watch:null},appType:'custom',
  });
  ({LandingPage}=await vite.ssrLoadModule('/src/LandingPage.tsx'));
  ({PreferencesProvider}=await vite.ssrLoadModule('/src/Preferences.tsx'));
});
after(async()=>{
  try{await vite?.close();}finally{
    if(fetchDescriptor)Object.defineProperty(globalThis,'fetch',fetchDescriptor);else delete globalThis.fetch;
  }
});

function renderPage({locale='zh',reduceMotion=false,saveData=false,videoSrc}={}){
  const descriptors=new Map(['matchMedia','localStorage','navigator'].map(key=>[key,Object.getOwnPropertyDescriptor(globalThis,key)]));
  let loginCalls=0;
  try{
    Object.defineProperty(globalThis,'matchMedia',{configurable:true,value:query=>({
      matches:query==='(prefers-reduced-motion: reduce)'&&reduceMotion,
      addEventListener(){},removeEventListener(){},
    })});
    Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{
      getItem:key=>key==='ontovis.locale'?locale:key==='ontovis.theme'?'system':null,
    }});
    Object.defineProperty(globalThis,'navigator',{configurable:true,value:{connection:{saveData}}});
    const html=renderToStaticMarkup(React.createElement(PreferencesProvider,null,
      React.createElement(LandingPage,{onLogin:()=>{loginCalls++;},videoSrc})));
    assert.equal(loginCalls,0,'Rendering the entry must not attempt login');
    assert.equal(requests.length,0,'Loading and rendering the public component must not fetch data');
    return html;
  }finally{
    for(const [key,descriptor] of descriptors){
      if(descriptor)Object.defineProperty(globalThis,key,descriptor);else delete globalThis[key];
    }
  }
}
function tags(html,name){
  return [...html.matchAll(new RegExp(`<${name}\\b([^>]*)>`,'gi'))].map(match=>
    Object.fromEntries([...match[1].matchAll(/([\w:-]+)="([^"]*)"/g)].map(attribute=>[attribute[1].toLowerCase(),attribute[2]])));
}
function text(html){return html.replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').replaceAll('&amp;','&').trim();}
function featureTitles(html){return [...html.matchAll(/<h3\b[^>]*>(.*?)<\/h3>/gs)].map(match=>text(match[1]));}
function assertPoster(html){
  const images=tags(html,'img');
  assert.equal(images.length,2);
  const background=images.find(image=>image.alt==='');
  assert.ok(background,'The decorative background has an empty alternative text');
  assert.match(background.src,/\/assets\/media\/wind-operations-poster\.webp(?:\?|$)/);
  assert.equal(background.fetchpriority,'high');
  const brand=images.find(image=>image.alt==='ONTOVis 本源数智');
  assert.ok(brand);
  assert.match(brand.src,/\/assets\/brand\/ONTOVis\.png(?:\?|$)/);
  return background.src;
}
function assertPublicBoundary(html){
  assert.doesNotMatch(html,/<(?:form|input|textarea|iframe|canvas|table)\b/i);
  assert.doesNotMatch(html,/role="(?:dialog|tree|treeitem|grid)"/i);
  const urls=[...html.matchAll(/\b(?:src|href)="([^"]+)"/g)].map(match=>match[1]);
  for(const url of urls)assert.ok(url.startsWith('#')||url.startsWith('/')&&!url.startsWith('//'),`Unexpected external resource or navigation: ${url}`);
}

test('the Chinese public entry contains the three introductions and local assets without engineering or credential surfaces',()=>{
  const html=renderPage(),visible=text(html);
  assert.match(visible,/从全局， 到每一个构件。/);
  assert.ok(visible.includes('连接场景、设备与工程资料，让现场信息在空间中清晰呈现。'));
  assert.deepEqual(featureTitles(html),['搭建场景，布置模型','找到设备，深入构件','关联资料，查阅图纸']);
  assert.match(html,/<button\b[^>]*>登录<svg\b/);
  assert.match(html,/<nav\b[^>]*aria-label="首页导航"/);
  assertPoster(html);assertPublicBoundary(html);
  assert.equal(tags(html,'video').length,0,'An unconfigured video must leave the poster-only entry usable');
});

test('the English preference renders the actual translated introduction and all three capability descriptions',()=>{
  const html=renderPage({locale:'en'}),visible=text(html);
  assert.ok(visible.includes('From the big picture. To every component.'));
  assert.ok(visible.includes('Connect scenes, equipment and engineering documents. See site information in its spatial context.'));
  assert.deepEqual(featureTitles(html),['Build scenes. Place models.','Find equipment. Explore components.','Connect documents. Read drawings.']);
  for(const description of ['Import terrain and model resources, then arrange equipment instances in a scene.',
    'Browse the equipment hierarchy and locate devices and their components in the model.',
    'Open associated drawings from an object and relate engineering documents to spatial locations.'])assert.ok(visible.includes(description));
  assert.match(html,/<button\b[^>]*>Sign in<svg\b/);
  assert.match(html,/<nav\b[^>]*aria-label="Homepage navigation"/);
  assert.doesNotMatch(visible,/搭建场景，布置模型|找到设备，深入构件|关联资料，查阅图纸/);
  assertPoster(html);assertPublicBoundary(html);
});

test('an optional local video is muted, loops inline and retains the same poster without eager loading',()=>{
  const videoSrc='/assets/wind-ops-loop-test.mp4',html=renderPage({videoSrc});
  const videos=tags(html,'video');assert.equal(videos.length,1);
  const video=videos[0];assert.equal(video.src,videoSrc);assert.equal(video.poster,assertPoster(html));
  for(const attribute of ['muted','loop','playsinline'])assert.ok(Object.hasOwn(video,attribute),`${attribute} is required for the decorative video`);
  assert.equal(video.preload,'none');
  assert.match(html,/aria-label="播放背景视频"/);
  assertPublicBoundary(html);
});

for(const [name,options] of [['reduced motion',{reduceMotion:true}],['data saving',{saveData:true}]]){
  test(`${name} prevents mounting a supplied video and preserves the poster and sign-in entry`,()=>{
    const videoSrc='/assets/wind-ops-loop-test.mp4',html=renderPage({...options,videoSrc});
    assert.equal(tags(html,'video').length,0);
    assert.ok(!html.includes(videoSrc),'The disabled media source must not appear in rendered resource URLs');
    assert.doesNotMatch(html,/aria-label="(?:播放|暂停)背景视频"/);
    assert.match(html,/<button\b[^>]*>登录<svg\b/);
    assertPoster(html);assertPublicBoundary(html);
  });
}
