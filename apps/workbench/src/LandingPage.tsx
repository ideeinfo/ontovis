import {useEffect, useRef, useState, type Ref} from 'react';
import {ArrowDown, ArrowUpRight, Boxes, FileText, Focus, Languages, Monitor, Moon, Pause, Play, Sun} from 'lucide-react';
import logo from '../../../assets/brand/ONTOVis.png';
import poster from '../../../assets/media/wind-operations-poster.webp';
import {usePreferences} from './Preferences';
import './landing.css';

const copy = {
  zh: {
    navigation:'首页导航', overview:'应用价值', signIn:'登录', language:'切换为 English', theme:'主题',
    light:'浅色', dark:'深色', system:'跟随系统', eyebrow:'工业资产可视化',
    title:<>看清现场，<br/>让协作更有依据。</>,
    intro:'将工业资产放回真实空间，让团队更快理解现场、找到问题所在，并从同一份工程依据开始协作。',
    discover:'了解 ONTOVis', scene:'风电运维场景',
    sectionTitle:<>减少信息断点，<br/>缩短理解与响应的距离。</>,
    sectionIntro:'为规划、运维与工程协同提供共同的现场语境，让分散在不同人员和资料中的信息更容易被理解和核对。',
    features:[
      {title:'更快理解现场', description:'把地形、设备位置与空间关系放在一起，帮助远程团队形成一致的现场认知。'},
      {title:'减少查找与沟通', description:'从场站走到设备、从设备深入构件，减少在目录、模型和资料之间反复寻找与解释。'},
      {title:'让判断有据可查', description:'围绕同一工程对象核对图纸与来源，把空间观察与工程依据联系起来，让协作过程更清晰。'},
    ],
    footer:'工业资产可视化与工程协同', top:'返回顶部', pause:'暂停背景视频', play:'播放背景视频',
  },
  en: {
    navigation:'Homepage navigation', overview:'Value', signIn:'Sign in', language:'切换为简体中文', theme:'Theme',
    light:'Light', dark:'Dark', system:'System', eyebrow:'Industrial asset visualization',
    title:<>See the site clearly.<br/>Collaborate with context.</>,
    intro:'Put industrial assets in their spatial context so teams can understand the site, locate issues and work from shared engineering evidence.',
    discover:'Explore ONTOVis', scene:'Wind operations',
    sectionTitle:<>Close information gaps.<br/>Bring understanding closer to action.</>,
    sectionIntro:'Give planning, operations and engineering teams shared site context, making scattered knowledge easier to understand and verify.',
    features:[
      {title:'Understand the site sooner', description:'See terrain, asset locations and spatial relationships together so remote teams can build a shared understanding.'},
      {title:'Spend less time searching and explaining', description:'Move from the site to equipment and components, reducing repeated searches across catalogs, models and documents.'},
      {title:'Keep decisions connected to evidence', description:'Check drawings and sources around the same engineering object, connecting spatial observations with the evidence behind them.'},
    ],
    footer:'Industrial asset visualization & engineering collaboration', top:'Back to top', pause:'Pause background video', play:'Play background video',
  },
};

export function LandingPage({onLogin, videoSrc, posterSrc=poster, suspended=false, loginButtonRef}: {onLogin:()=>void; videoSrc?:string; posterSrc?:string; suspended?:boolean; loginButtonRef?:Ref<HTMLButtonElement>}) {
  const {locale,theme,setLocale,setTheme} = usePreferences();
  const c = copy[locale];
  const video = useRef<HTMLVideoElement>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const [reduceMotion,setReduceMotion] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [paused,setPaused] = useState(false);
  const [playing,setPlaying] = useState(false);
  const [videoReady,setVideoReady] = useState(false);
  const [videoFailed,setVideoFailed] = useState(false);
  const saveData = (navigator as Navigator & {connection?:{saveData?:boolean}}).connection?.saveData;
  const showVideo = !!videoSrc && !reduceMotion && !saveData && !videoFailed;
  useEffect(() => {
    const media=matchMedia('(prefers-reduced-motion: reduce)');
    const update=()=>setReduceMotion(media.matches);
    media.addEventListener('change',update);
    return ()=>media.removeEventListener('change',update);
  },[]);
  useEffect(() => {setVideoFailed(false);setVideoReady(false);},[videoSrc]);
  useEffect(() => {
    const element=video.current;
    if(!showVideo || !element)return;
    const update=()=>{
      if(document.hidden || paused || suspended)element.pause();
      else void element.play().catch(()=>setPlaying(false));
    };
    update(); document.addEventListener('visibilitychange',update);
    return ()=>{document.removeEventListener('visibilitychange',update);element.pause();};
  },[showVideo,paused,videoSrc,suspended]);
  function goTo(id:string) {
    const container=scroll.current, target=container?.querySelector<HTMLElement>(`#${id}`);
    if(!container || !target)return;
    container.scrollTo({top:id==='ov-entry-top' ? 0 : target.offsetTop-88,behavior:reduceMotion ? 'instant' : 'smooth'});
    target.focus({preventScroll:true});
  }
  const icons=[Boxes,Focus,FileText];
  return <div className="ov-app ov-entry" ref={scroll}>
    <div className="ov-entry-backdrop" aria-hidden="true">
      <img src={posterSrc} alt="" fetchPriority="high"/>
      {showVideo && <video ref={video} src={videoSrc} poster={posterSrc} muted loop playsInline preload="none"
        onPlaying={()=>{setPlaying(true);setVideoReady(true);}} onPause={()=>setPlaying(false)} onError={()=>{setVideoFailed(true);setPlaying(false);}} data-ready={videoReady}/>}
    </div>
    <a className="ov-entry-skip" href="#ov-entry-features" onClick={event=>{event.preventDefault();goTo('ov-entry-features');}}>{c.overview}</a>
    <header className="ov-entry-header">
      <a className="ov-entry-brand" href="#ov-entry-top" aria-label="ONTOVis" onClick={event=>{event.preventDefault();goTo('ov-entry-top');}}><img src={logo} alt="ONTOVis 本源数智"/></a>
      <nav aria-label={c.navigation}>
        <button type="button" className="ov-entry-overview" onClick={()=>goTo('ov-entry-features')}>{c.overview}</button>
        <button type="button" className="ov-entry-language" aria-label={c.language} onClick={()=>setLocale(locale==='zh' ? 'en' : 'zh')}><Languages size={16}/><span>{locale==='zh' ? 'EN' : '中文'}</span></button>
        <label className="ov-entry-theme">{theme==='dark' ? <Moon size={16}/> : theme==='light' ? <Sun size={16}/> : <Monitor size={16}/>}<select aria-label={c.theme} value={theme} onChange={event=>setTheme(event.target.value as 'light'|'dark'|'system')}><option value="system">{c.system}</option><option value="light">{c.light}</option><option value="dark">{c.dark}</option></select></label>
        <button type="button" ref={loginButtonRef} className="ov-entry-login" onClick={onLogin}>{c.signIn}<ArrowUpRight size={16}/></button>
      </nav>
    </header>
    <main>
      <section className="ov-entry-hero" aria-labelledby="ov-entry-title">
        <div className="ov-entry-hero-copy" id="ov-entry-top" tabIndex={-1}>
          <p className="ov-entry-eyebrow"><span/>{c.eyebrow}</p>
          <h1 id="ov-entry-title">{c.title}</h1>
          <p className="ov-entry-intro">{c.intro}</p>
          <button type="button" className="ov-entry-discover" onClick={()=>goTo('ov-entry-features')}>{c.discover}<ArrowDown size={16}/></button>
        </div>
        <div className="ov-entry-hero-foot"><span>{c.scene}</span><span className="ov-entry-rule"/>{showVideo && <button type="button" aria-label={playing ? c.pause : c.play} onClick={()=>{if(playing)setPaused(true);else {setPaused(false);void video.current?.play().catch(()=>setPlaying(false));}}}>{playing ? <Pause size={16}/> : <Play size={16}/>}</button>}</div>
      </section>
      <section id="ov-entry-features" className="ov-entry-features" tabIndex={-1} aria-labelledby="ov-entry-feature-title">
        <div className="ov-entry-feature-heading"><p className="ov-entry-eyebrow">ONTOVis</p><h2 id="ov-entry-feature-title">{c.sectionTitle}</h2><p>{c.sectionIntro}</p></div>
        <div className="ov-entry-feature-list">{c.features.map((feature,index)=>{
          const Icon=icons[index];
          return <article key={index}><div className="ov-entry-feature-icon"><Icon size={22} strokeWidth={1.5}/></div><div><span className="ov-entry-number">0{index+1}</span><h3>{feature.title}</h3><p>{feature.description}</p></div></article>;
        })}</div>
      </section>
    </main>
    <footer className="ov-entry-footer"><span>ONTOVis · {c.footer}</span><button type="button" onClick={()=>goTo('ov-entry-top')}>{c.top}<ArrowUpRight size={14}/></button></footer>
  </div>;
}
