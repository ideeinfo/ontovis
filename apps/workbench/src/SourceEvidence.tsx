import { useEffect, useRef, useState } from 'react';
import { ChevronDown, FileText, Focus, ZoomIn, ZoomOut } from 'lucide-react';
import { ApiError, cancelled, failureMessage, type WorkbenchApi } from './api';
import type { EngineeringObject, Evidence, EvidenceList, Installation } from './types';
import { Badge, Btn, IconBtn, Modal } from './Primitives';

export function SourceEvidence({api, object, context, host}: {
  api: WorkbenchApi; object: EngineeringObject; context: Installation; host: string;
}) {
  const [list, setList] = useState<EvidenceList | null>(null);
  const [error, setError] = useState('');
  const [changed, setChanged] = useState(false);
  const [requestNumber, setRequestNumber] = useState(0);
  const [chosen, setChosen] = useState<Evidence | null>(null);
  const [image, setImage] = useState('');
  const [reading, setReading] = useState(false);
  const [zoom, setZoom] = useState(1);
  const active = useRef(true);
  const documentAbort = useRef<AbortController | null>(null);
  const imageUrl = useRef('');
  const body = {entityUid: object.entityUid, installationContextId: context.installationContextId,
    expectedEntityRevision: object.entityRevision, expectedHierarchyRevision: context.hierarchyRevision};

  function close() {
    documentAbort.current?.abort(); documentAbort.current = null;
    if (imageUrl.current) URL.revokeObjectURL(imageUrl.current);
    imageUrl.current = ''; setImage(''); setChosen(null); setReading(false);
  }
  useEffect(() => {
    active.current = true;
    return () => {active.current = false; documentAbort.current?.abort();
      if (imageUrl.current) URL.revokeObjectURL(imageUrl.current);};
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setList(null); setError(''); setChanged(false);
    api.request<EvidenceList>('/api/workbench/evidence/resolve', body, controller.signal)
      .then(value => {if (!controller.signal.aborted) setList(value);})
      .catch(error => {if (!cancelled(error)) {setError(failureMessage(error)); setChanged(error instanceof ApiError && error.status === 409);}});
    return () => controller.abort();
  }, [requestNumber]);

  async function open(item: Evidence) {
    close(); setChosen(item); setReading(true); setError(''); setZoom(1);
    const controller = new AbortController(); documentAbort.current = controller;
    try {
      const blob = await api.request<Blob>('/api/workbench/evidence/content', {...body,
        evidenceRef: item.evidenceRef, expectedSourceRevision: item.sourceRevision,
        expectedContentSha256: item.contentSha256}, controller.signal, true);
      if (!active.current || controller.signal.aborted) return;
      imageUrl.current = URL.createObjectURL(blob); setImage(imageUrl.current);
    } catch (error) {
      if (cancelled(error) || !active.current) return;
      if (error instanceof ApiError && error.status === 409) {
        close(); setList(null); setChanged(true);
      }
      setError(failureMessage(error));
    } finally {if (active.current && !controller.signal.aborted) setReading(false);}
  }
  return <section className="ov-source-evidence" aria-label="所选对象的关联图纸">
    <div className="ov-section-head"><h3>关联图纸</h3><Badge>当前内容</Badge></div>
    {changed ? <div className="ov-source-empty" role="alert"><FileText size={20} /><p>来源版本已变化</p><span>重新读取清单后，请再次选择图纸。</span><Btn onClick={() => {close(); setRequestNumber(v => v + 1);}}>重新读取关联资料</Btn></div>
      : !list ? <div className="ov-source-empty" role={error ? 'alert' : 'status'}><p>{error || '正在读取关联资料…'}</p>{error && <Btn onClick={() => setRequestNumber(v => v + 1)}>重试读取</Btn>}</div>
      : list.items.length === 0 ? <div className="ov-source-empty" role="status"><FileText size={20} /><p>当前对象没有关联图纸</p></div>
      : list.items.map(item => <div className="ov-source-item" key={item.evidenceRef}>
        <div className="ov-evidence-card"><FileText size={17} /><div><strong>{item.title}</strong><small>内容 {item.contentSha256?.slice(0, 8) || '缺失'} · {item.pageNumber ? `第 ${item.pageNumber} 页` : '页码未知'} · {item.sourceRelation === 'template_definition' ? '型号定义来源' : '直接来源'}</small></div></div>
        {item.sourceRelation === 'template_definition' && <p className="ov-source-note">用于同型号参照；现场安装关系仍待核实。</p>}
        {item.availability === 'missing' ? <p className="ov-source-note">原文暂不可用，保留资料引用。</p> : <Btn onClick={() => open(item)}>打开图纸</Btn>}
      </div>)}
    {chosen && <Modal title={`关联图纸 · ${chosen.sourceRelation === 'template_definition' ? '型号来源' : '直接来源'}`} description="受保护的当前图纸预览" onClose={close}>
      <div className="ov-source-viewer"><div className="ov-source-context"><span>分析对象：<strong>{object.displayName}</strong></span><span>空间定位：{host}</span><Badge>整页</Badge></div>
        <div className="ov-source-page-heading"><strong>{chosen.title}</strong><span>{chosen.pageNumber ? `第 ${chosen.pageNumber} 页` : '页码未知'} · 内容 {chosen.contentSha256?.slice(0, 8)}</span></div>
        {reading ? <div className="ov-source-page-state" role="status">正在核验并读取选定内容…</div>
          : image ? <><div className="ov-source-tools" aria-label="图纸查看工具">
            <IconBtn label="缩小图纸" disabled={zoom <= .5} onClick={() => setZoom(v => Math.max(.5, v - .25))}><ZoomOut size={16} /></IconBtn>
            <IconBtn label="放大图纸" disabled={zoom >= 4} onClick={() => setZoom(v => Math.min(4, v + .25))}><ZoomIn size={16} /></IconBtn>
            <IconBtn label="图纸适合窗口" onClick={() => setZoom(1)}><Focus size={16} /></IconBtn><span aria-live="polite">{Math.round(zoom * 100)}%</span>
          </div><div className="ov-source-page"><img src={image} alt={`${chosen.title}，整页预览`} style={{width: `${zoom * 100}%`}} onError={() => {if (imageUrl.current) URL.revokeObjectURL(imageUrl.current); imageUrl.current = ''; setImage(''); setError('图纸预览未完整显示，请重试。');}} /></div><p className="ov-source-note">缺少可核验的区域版本，显示整页。</p></>
          : <div className="ov-source-page-state" role="alert"><p>{error}</p><Btn onClick={() => open(chosen)}>重试读取</Btn></div>}
        <details className="ov-details"><summary>来源与使用范围 <ChevronDown size={13} /></summary><p>当前内容摘要：{chosen.contentSha256}</p><p>文件与引用变化后需要重新选择。当前预览不提供历史归档；资料来源与空间定位分开核验。</p></details>
      </div></Modal>}
  </section>;
}
