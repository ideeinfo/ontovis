import {useEffect, useRef, useState, type ReactNode} from 'react';
import {Image as ImageIcon, Upload} from 'lucide-react';
import {ApiError, cancelled} from './api.ts';
import {Btn} from './Primitives.tsx';
import type {SceneApi} from './sceneApi.ts';
import type {SceneThumbnailInfo} from './sceneTypes.ts';

function cacheKey(sceneId: string, thumbnail: SceneThumbnailInfo) {
  return `${sceneId}:${thumbnail.thumbnailRevision}:${thumbnail.sha256}`;
}

export function SceneThumbnail({
  client,
  sceneId,
  name,
  thumbnail,
  fallback,
}: {
  client: SceneApi;
  sceneId: string;
  name: string;
  thumbnail?: SceneThumbnailInfo | null;
  fallback: ReactNode;
}) {
  const [loaded, setLoaded] = useState<{client: SceneApi; scope: string; key: string; url: string} | null>(null);
  const [failed, setFailed] = useState(false);
  const denied = useRef<{client:SceneApi; scope:string} | null>(null);
  const key = thumbnail ? cacheKey(sceneId, thumbnail) : '';
  const scope = client.sessionScope;
  const url = loaded?.client === client && loaded.scope === scope && loaded.key === key ? loaded.url : null;

  useEffect(() => {
    setLoaded(null);
    setFailed(false);
    if (!thumbnail || !key) return;
    if (denied.current?.client === client && denied.current.scope === client.authorizationScope) return;
    let owned: string | null = null;
    const abort = new AbortController();
    void client
      .sceneThumbnailContent(sceneId, thumbnail, abort.signal)
      .then(blob => {
        if (abort.signal.aborted) return;
        if (typeof URL.createObjectURL === 'function') {
          owned = URL.createObjectURL(blob);
          setLoaded({client, scope, key, url: owned});
        }
      })
      .catch(error => {
        if (!abort.signal.aborted && !cancelled(error)) {
          if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
            denied.current = {client, scope:client.authorizationScope};
          }
          setFailed(true);
        }
      });
    return () => {
      abort.abort();
      if (owned && typeof URL.revokeObjectURL === 'function') URL.revokeObjectURL(owned);
    };
  }, [client, scope, sceneId, key]);

  if (url && !failed) {
    return (
      <img
        className="pc-card-thumb"
        src={url}
        alt={name}
        decoding="async"
        draggable={false}
        onError={() => {
          setFailed(true);
          setLoaded(null);
        }}
      />
    );
  }
  return <>{fallback}</>;
}

export function SceneThumbnailField({
  client,
  sceneId,
  name,
  thumbnail,
  pendingFile,
  disabled,
  locale,
  onSelectFile,
  onError,
}: {
  client: SceneApi;
  sceneId: string;
  name: string;
  thumbnail?: SceneThumbnailInfo | null;
  pendingFile: File | null;
  disabled: boolean;
  locale: string;
  onSelectFile: (file: File | null) => void;
  onError?: (error: unknown) => void;
}) {
  const t = (zh: string, en: string) => (locale === 'en' ? en : zh);
  const inputRef = useRef<HTMLInputElement>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!pendingFile || typeof URL.createObjectURL !== 'function') {
      setPreviewUrl(null);
      return;
    }
    const owned = URL.createObjectURL(pendingFile);
    setPreviewUrl(owned);
    return () => {
      if (typeof URL.revokeObjectURL === 'function') URL.revokeObjectURL(owned);
    };
  }, [pendingFile]);

  return (
    <div className="sw-thumb-field">
      <span>{t('场景缩略图', 'Scene thumbnail')}</span>
      <div className="sw-thumb-row">
        <span className="pc-card-visual sw-thumb-preview">
          {previewUrl ? (
            <img className="pc-card-thumb" src={previewUrl} alt={name} decoding="async" draggable={false} />
          ) : (
            <SceneThumbnail
              client={client}
              sceneId={sceneId}
              name={name}
              thumbnail={thumbnail}
              fallback={<ImageIcon size={22} />}
            />
          )}
        </span>
        <div className="sw-thumb-actions">
          <input
            ref={inputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            hidden
            disabled={disabled}
            aria-label={t('选择场景缩略图文件', 'Choose scene thumbnail file')}
            onChange={event => {
              const file = event.target.files?.[0] || null;
              event.target.value = '';
              if (!file) return;
              if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
                onError?.(new ApiError(422, 'THUMBNAIL_INVALID_IMAGE'));
                return;
              }
              if (file.size < 16 || file.size > 5 * 1024 * 1024) {
                onError?.(new ApiError(413, 'THUMBNAIL_LIMIT_EXCEEDED'));
                return;
              }
              onSelectFile(file);
            }}
          />
          <div className="sw-actions">
            <Btn disabled={disabled} onClick={() => inputRef.current?.click()}>
              <Upload size={14} />
              {thumbnail || pendingFile ? t('更新缩略图', 'Update thumbnail') : t('上传缩略图', 'Upload thumbnail')}
            </Btn>
            {pendingFile && (
              <Btn disabled={disabled} onClick={() => onSelectFile(null)}>
                {t('取消选择', 'Clear')}
              </Btn>
            )}
          </div>
          <small className="se-note">
            {pendingFile
              ? `${t('待保存新缩略图：', 'Pending thumbnail: ')}${pendingFile.name}`
              : thumbnail
                ? t('已设置场景缩略图，可上传新图片替换。', 'Thumbnail configured. Upload a new image to replace it.')
                : t('暂未设置缩略图（支持 PNG / JPEG / WebP，最大 5 MB）。', 'No thumbnail set (PNG, JPEG or WebP up to 5 MB).')}
          </small>
        </div>
      </div>
    </div>
  );
}
