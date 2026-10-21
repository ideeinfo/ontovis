import { useEffect, useRef, useState } from 'react';
import { ChevronDown, FileText, Focus, ZoomIn, ZoomOut } from 'lucide-react';
import { ApiError, cancelled, failureMessage, type WorkbenchApi } from './api';
import type { EngineeringObject, Evidence, EvidenceList, Installation } from './types';
import { Badge, Btn, IconBtn, Modal } from './Primitives';
import { usePreferences } from './Preferences';

export function SourceEvidence({api, object, context, host}: {
  api: WorkbenchApi; object: EngineeringObject; context: Installation; host: string;
}) {
  const {t, locale} = usePreferences();
  const [list, setList] = useState<EvidenceList | null>(null);
  const [error, setError] = useState<unknown>(null);
  const errorText = error ? failureMessage(error, locale) : '';
  const [changed, setChanged] = useState(false);
  const [requestNumber, setRequestNumber] = useState(0);
  const [chosen, setChosen] = useState<Evidence | null>(null);
  const [image, setImage] = useState('');
  const [reading, setReading] = useState(false);
  const [zoom, setZoom] = useState(1);
  const active = useRef(true);
  const documentAbort = useRef<AbortController | null>(null);
  const imageUrl = useRef('');
  const body = {entityUid: object.entityUid, installationContextId: object.installationContextId,
    expectedEntityRevision: object.entityRevision, expectedHierarchyRevision: object.installationContextId ? context.hierarchyRevision : null};

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
    setList(null); setError(null); setChanged(false);
    api.request<EvidenceList>('/api/workbench/evidence/resolve', body, controller.signal)
      .then(value => {if (!controller.signal.aborted) setList(value);})
      .catch(error => {if (!cancelled(error)) {setError(error); setChanged(error instanceof ApiError && error.status === 409);}});
    return () => controller.abort();
  }, [requestNumber]);

  async function open(item: Evidence) {
    close(); setChosen(item); setReading(true); setError(null); setZoom(1);
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
      setError(error);
    } finally {if (active.current && !controller.signal.aborted) setReading(false);}
  }
  return <section className="ov-source-evidence" aria-label={t('evidenceHeading')}>
    <div className="ov-section-head"><h3>{t('evidenceHeading')}</h3><Badge>{t('currentContent')}</Badge></div>
    {changed ? <div className="ov-source-empty" role="alert"><FileText size={20} /><p>{t('changedSource')}</p><span>{t('reselectSource')}</span><Btn onClick={() => {close(); setRequestNumber(v => v + 1);}}>{t('reloadEvidence')}</Btn></div>
      : !list ? <div className="ov-source-empty" role={error ? 'alert' : 'status'}><p>{errorText || t('loadingEvidence')}</p>{!!error && <Btn onClick={() => setRequestNumber(v => v + 1)}>{t('retry')}</Btn>}</div>
      : list.items.length === 0 ? <div className="ov-source-empty" role="status"><FileText size={20} /><p>{t('noEvidence')}</p></div>
      : list.items.map(item => <div className="ov-source-item" key={item.evidenceRef}>
        <div className="ov-evidence-card"><FileText size={17} /><div><strong>{item.title}</strong><small>{item.pageNumber ? t('page', {number:item.pageNumber}) : t('unknownPage')} · {item.sourceRelation === 'template_definition' ? t('templateSource') : t('directSource')}</small></div></div>
        {item.sourceRelation === 'template_definition' && <p className="ov-source-note">{t('sourceNote')}</p>}
        {item.availability === 'missing' ? <p className="ov-source-note">{t('sourceMissing')}</p> : <Btn onClick={() => open(item)}>{t('openDrawing')}</Btn>}
      </div>)}
    {chosen && <Modal title={t('evidenceHeading')} description={t('drawingDescription')} onClose={close}>
      <div className="ov-source-viewer"><div className="ov-source-context"><span>{t('linkedObject')}：<strong>{object.displayName}</strong></span><span>{t('location')}：{host}</span><Badge>{t('wholePage')}</Badge></div>
        <div className="ov-source-page-heading"><strong>{chosen.title}</strong><span>{chosen.pageNumber ? t('page', {number:chosen.pageNumber}) : t('unknownPage')}</span></div>
        {reading ? <div className="ov-source-page-state" role="status">{t('verifying')}</div>
          : image ? <><div className="ov-source-tools" aria-label={t('drawingTools')}>
            <IconBtn label={t('drawingZoomOut')} disabled={zoom <= .5} onClick={() => setZoom(v => Math.max(.5, v - .25))}><ZoomOut size={16} /></IconBtn>
            <IconBtn label={t('drawingZoomIn')} disabled={zoom >= 4} onClick={() => setZoom(v => Math.min(4, v + .25))}><ZoomIn size={16} /></IconBtn>
            <IconBtn label={t('drawingFit')} onClick={() => setZoom(1)}><Focus size={16} /></IconBtn><span aria-live="polite">{Math.round(zoom * 100)}%</span>
          </div><div className="ov-source-page"><img src={image} alt={t('drawingAlt', {title:chosen.title})} style={{width: `${zoom * 100}%`}} onError={() => {if (imageUrl.current) URL.revokeObjectURL(imageUrl.current); imageUrl.current = ''; setImage(''); setError(new ApiError(502, 'IMAGE_INVALID'));}} /></div><p className="ov-source-note">{t('wholePageNote')}</p></>
          : <div className="ov-source-page-state" role="alert"><p>{errorText}</p><Btn onClick={() => open(chosen)}>{t('retry')}</Btn></div>}
        <details className="ov-details"><summary>{t('sourceDetails')} <ChevronDown size={13} /></summary><p>{t('contentDigest')}：{chosen.contentSha256}</p><p>{t('sourceVersionNote')}</p></details>
      </div></Modal>}
  </section>;
}
