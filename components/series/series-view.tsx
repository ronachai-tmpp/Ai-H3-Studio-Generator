'use client'

/**
 * SeriesView
 * - หน้าดูความคืบหน้าซีรีย์ (อ่านอย่างเดียว) ที่ Claude Code สร้างผ่าน MCP
 * - poll รายการซีรีย์ + รายละเอียดของซีรีย์ที่เลือกทุก 5 วินาที
 * - เล่นตอนที่เสร็จแล้วและคลิปของแต่ละฉากเพื่อตรวจเสียง/ลิปซิงค์
 * - ปุ่มควบคุมมีแค่ หยุดชั่วคราว / รันต่อ / ยกเลิก
 */

import * as React from 'react'
import {
  AlertCircle,
  Check,
  Copy,
  Download,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Tv,
  X,
} from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import {
  controlSeries,
  fetchSeries,
  fetchSeriesList,
  getMediaUrl,
  type SceneStatus,
  type SeriesDetail,
  type SeriesEpisode,
  type SeriesOverview,
  type SeriesScene,
  type SeriesStatus,
} from '@/lib/backend'
import { cn } from '@/lib/utils'

const POLL_MS = 5000

const PAUSE_REASON_TH: Record<string, string> = {
  user: 'หยุดโดยผู้ใช้',
  review: 'รอตรวจตอน',
  casting: 'รอตรวจตัวละคร',
  error: 'เกิดข้อผิดพลาด',
}

const STATUS_BADGE: Record<SeriesStatus, string> = {
  DRAFT: 'bg-muted text-muted-foreground',
  RUNNING: 'bg-blue-500/15 text-blue-600 dark:text-blue-400',
  PAUSED: 'bg-amber-500/15 text-amber-600 dark:text-amber-400',
  DONE: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
  CANCELLED: 'bg-destructive/10 text-destructive',
}

const DOT_COLOR: Record<SceneStatus, string> = {
  PENDING: 'bg-muted-foreground/30',
  QUEUED: 'bg-amber-400',
  RUNNING: 'bg-blue-500 animate-pulse',
  DONE: 'bg-emerald-500',
  FAILED: 'bg-destructive',
}

const MODE_TH: Record<SeriesScene['mode'], string> = {
  text: 'text (จากข้อความ)',
  ref: 'ref (ใช้รูปอ้างอิง)',
  chain: 'chain (ต่อจากเฟรมสุดท้าย)',
}

/** คัดลอกข้อความ: ใช้ Clipboard API ถ้าได้ ไม่ได้ (HTTP LAN) ใช้ textarea + execCommand */
async function copyTextToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {}
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.top = '-9999px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

function formatClock(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '-'
  const total = Math.round(seconds)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

function formatEta(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60))
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h === 0) return `${m} นาที`
  return m === 0 ? `${h} ชั่วโมง` : `${h} ชั่วโมง ${m} นาที`
}

function errorText(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback
}

function StatusBadge({ status }: { status: SeriesStatus }) {
  return (
    <Badge variant="secondary" className={cn('shrink-0', STATUS_BADGE[status])}>
      {status}
    </Badge>
  )
}

/** ข้อความสถานะเสริมใต้ชื่อซีรีย์ (เหตุผลที่หยุด / รอตอนถัดไป) */
function statusNote(
  s: Pick<SeriesOverview, 'status' | 'pause_reason' | 'waiting_for'>,
  pauseMessage?: string | null
): string | null {
  if (s.status === 'PAUSED') {
    const reason = s.pause_reason ? PAUSE_REASON_TH[s.pause_reason] ?? s.pause_reason : null
    return [reason, pauseMessage].filter(Boolean).join(' · ') || null
  }
  if (s.waiting_for === 'episodes') return 'รอตอนถัดไปจาก Claude Code'
  return null
}

/* ------------------------------------------------------------------ */
/* รายการซีรีย์                                                        */
/* ------------------------------------------------------------------ */

function SeriesRow({
  series,
  selected,
  onSelect,
}: {
  series: SeriesOverview
  selected: boolean
  onSelect: () => void
}) {
  const { progress } = series
  const note = statusNote(series)
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        'w-full rounded-xl border p-3 text-left transition-colors',
        selected
          ? 'border-primary bg-primary/5'
          : 'border-border bg-muted/20 hover:bg-muted/40'
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0 break-words text-sm font-medium text-foreground">
          {series.title}
        </span>
        <StatusBadge status={series.status} />
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        ตอน {series.episodes_done}/{series.episodes_total} · ฉาก {progress.scenes_done}/
        {progress.scenes_total}
        {progress.eta_seconds !== null && ` · เหลือประมาณ ${formatEta(progress.eta_seconds)}`}
      </p>
      {note && <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">{note}</p>}
    </button>
  )
}

/* ------------------------------------------------------------------ */
/* ตอน                                                                 */
/* ------------------------------------------------------------------ */

function SceneDetail({ scene }: { scene: SeriesScene }) {
  const videoUrl = getMediaUrl(scene.video_path)
  const posterUrl = getMediaUrl(scene.thumbnail_path) ?? undefined
  return (
    <div className="mt-3 grid gap-3 rounded-xl border border-border bg-muted/20 p-3 sm:grid-cols-[minmax(0,200px)_1fr]">
      {videoUrl && (
        <div className="aspect-[9/16] w-full max-w-[200px] overflow-hidden rounded-lg bg-black">
          <video
            key={videoUrl}
            src={videoUrl}
            poster={posterUrl}
            controls
            preload="metadata"
            playsInline
            className="h-full w-full object-contain"
          />
        </div>
      )}
      <div className={cn('min-w-0 space-y-2 text-sm', !videoUrl && 'sm:col-span-2')}>
        <p className="text-xs text-muted-foreground">
          ฉาก {scene.index} · {MODE_TH[scene.mode]} · {scene.duration_seconds} วินาที ·{' '}
          {scene.status}
          {scene.attempts > 0 && ` · ลองแล้ว ${scene.attempts} ครั้ง`}
        </p>
        {scene.characters.length > 0 && (
          <p className="text-xs text-muted-foreground">
            ตัวละคร: {scene.characters.join(', ')}
          </p>
        )}
        <p className="whitespace-pre-wrap break-words text-foreground">{scene.prompt}</p>
        {scene.beat && (
          <p className="break-words text-xs text-muted-foreground">Beat: {scene.beat}</p>
        )}
        {scene.error && (
          <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 p-2 text-xs text-destructive">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="break-words">{scene.error}</span>
          </div>
        )}
      </div>
    </div>
  )
}

function CaptionBlock({ episode }: { episode: SeriesEpisode }) {
  const [copied, setCopied] = React.useState(false)
  const text = [episode.caption, episode.hashtags.join(' ')].filter(Boolean).join('\n\n')
  if (!text) return null

  const handleCopy = async () => {
    const ok = await copyTextToClipboard(text)
    if (ok) {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } else {
      toast.error('คัดลอกไม่สำเร็จ')
    }
  }

  return (
    <div className="min-w-0 space-y-2">
      <p className="whitespace-pre-wrap break-words text-sm text-foreground">{episode.caption}</p>
      {episode.hashtags.length > 0 && (
        <p className="break-words text-xs text-primary">{episode.hashtags.join(' ')}</p>
      )}
      <Button variant="outline" size="sm" onClick={() => void handleCopy()}>
        {copied ? <Check className="mr-2 h-4 w-4" /> : <Copy className="mr-2 h-4 w-4" />}
        {copied ? 'คัดลอกแล้ว' : 'คัดลอก'}
      </Button>
    </div>
  )
}

function EpisodeCard({ episode }: { episode: SeriesEpisode }) {
  const [openScene, setOpenScene] = React.useState<number | null>(null)
  const videoUrl = episode.status === 'DONE' ? getMediaUrl(episode.final_video_path) : null
  const posterUrl = getMediaUrl(episode.thumbnail_path) ?? undefined
  const runningScene = episode.scenes.find((s) => s.status === 'RUNNING')
  const selected = episode.scenes.find((s) => s.index === openScene)

  return (
    <div className="rounded-xl border border-border bg-muted/20 p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="min-w-0 break-words text-sm font-semibold text-foreground">
          EP{String(episode.number).padStart(2, '0')} {episode.title}
        </h3>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>{episode.status}</span>
          {episode.duration !== null && <span>{formatClock(episode.duration)}</span>}
        </div>
      </div>

      {videoUrl && (
        <div className="mt-3 grid gap-4 sm:grid-cols-[minmax(0,280px)_1fr]">
          <div className="aspect-[9/16] w-full max-w-[280px] overflow-hidden rounded-lg bg-black">
            <video
              key={videoUrl}
              src={videoUrl}
              poster={posterUrl}
              controls
              preload="metadata"
              playsInline
              className="h-full w-full object-contain"
            />
          </div>
          <div className="min-w-0 space-y-3">
            <a
              href={videoUrl}
              download
              className="inline-flex h-8 items-center gap-2 rounded-md border border-border px-3 text-sm text-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
            >
              <Download className="h-4 w-4" /> ดาวน์โหลด
            </a>
            <CaptionBlock episode={episode} />
          </div>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {episode.scenes.map((scene) => (
          <button
            key={scene.index}
            type="button"
            onClick={() => setOpenScene(openScene === scene.index ? null : scene.index)}
            aria-label={`ฉาก ${scene.index}: ${scene.status}`}
            title={`ฉาก ${scene.index}: ${scene.status}`}
            className={cn(
              'h-5 w-5 rounded-full transition-transform hover:scale-110',
              DOT_COLOR[scene.status],
              openScene === scene.index && 'ring-2 ring-primary ring-offset-2 ring-offset-background'
            )}
          />
        ))}
        {runningScene && (
          <span className="ml-1 text-xs text-muted-foreground">
            ฉาก {runningScene.index}: {Math.round(runningScene.progress)}%
          </span>
        )}
      </div>

      {selected && <SceneDetail key={selected.index} scene={selected} />}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* รายละเอียดซีรีย์ + ปุ่มควบคุม                                         */
/* ------------------------------------------------------------------ */

function SeriesDetailPanel({
  detail,
  overview,
  onChanged,
}: {
  detail: SeriesDetail
  overview: SeriesOverview | undefined
  onChanged: (detail: SeriesDetail) => void
}) {
  const [busy, setBusy] = React.useState(false)
  const [confirmCancel, setConfirmCancel] = React.useState(false)
  const progress = overview?.progress ?? detail.progress
  const pct =
    progress.scenes_total > 0
      ? Math.round((progress.scenes_done / progress.scenes_total) * 100)
      : 0
  const note = statusNote(detail, detail.pause_message)

  const run = async (action: 'pause' | 'resume' | 'cancel') => {
    setBusy(true)
    try {
      onChanged(await controlSeries(detail.id, action))
      setConfirmCancel(false)
    } catch (err) {
      toast.error(errorText(err, 'สั่งงานไม่สำเร็จ'))
    } finally {
      setBusy(false)
    }
  }

  const canCancel =
    detail.status === 'RUNNING' || detail.status === 'PAUSED' || detail.status === 'DRAFT'

  return (
    <div className="grid gap-4">
      <div className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="break-words text-lg font-semibold text-foreground">{detail.title}</h2>
            {detail.logline && (
              <p className="mt-1 break-words text-sm text-muted-foreground">{detail.logline}</p>
            )}
          </div>
          <StatusBadge status={detail.status} />
        </div>
        {note && <p className="text-sm text-amber-600 dark:text-amber-400">{note}</p>}

        <div className="flex flex-wrap items-center gap-2">
          {detail.status === 'RUNNING' && (
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => void run('pause')}
            >
              <Pause className="mr-2 h-4 w-4" /> หยุดชั่วคราว
            </Button>
          )}
          {detail.status === 'PAUSED' && (
            <Button size="sm" disabled={busy} onClick={() => void run('resume')}>
              <Play className="mr-2 h-4 w-4" /> รันต่อ
            </Button>
          )}
          {canCancel &&
            (confirmCancel ? (
              <>
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={busy}
                  onClick={() => void run('cancel')}
                >
                  {busy ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <X className="mr-2 h-4 w-4" />
                  )}
                  ยืนยันยกเลิก
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => setConfirmCancel(false)}
                >
                  ไม่ยกเลิก
                </Button>
              </>
            ) : (
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                className="text-destructive hover:text-destructive"
                onClick={() => setConfirmCancel(true)}
              >
                ยกเลิกซีรีย์
              </Button>
            ))}
        </div>

        <div className="space-y-1">
          <Progress value={pct} />
          <p className="text-xs text-muted-foreground">
            ฉาก {progress.scenes_done}/{progress.scenes_total}
            {progress.eta_seconds !== null && ` · เหลือประมาณ ${formatEta(progress.eta_seconds)}`}
          </p>
        </div>
      </div>

      {detail.episodes.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
          ยังไม่มีตอน
        </p>
      ) : (
        detail.episodes.map((episode) => <EpisodeCard key={episode.number} episode={episode} />)
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* หน้าหลัก                                                            */
/* ------------------------------------------------------------------ */

export function SeriesView() {
  const [list, setList] = React.useState<SeriesOverview[] | null>(null)
  const [listError, setListError] = React.useState<string | null>(null)
  const [selectedId, setSelectedId] = React.useState<string | null>(null)
  // เก็บ id คู่กับ detail เพื่อไม่ให้ข้อมูลของซีรีย์ก่อนหน้ามาแสดงทับ
  const [detailState, setDetailState] = React.useState<{
    id: string
    data: SeriesDetail
  } | null>(null)
  const [detailErrorState, setDetailErrorState] = React.useState<{
    id: string
    message: string
  } | null>(null)
  const [reloadKey, setReloadKey] = React.useState(0)

  // ซีรีย์ที่เลือกอยู่ (ถ้ายังไม่ได้เลือก หรือหายไปจากรายการ ใช้ตัวแรก)
  const activeId =
    list?.find((s) => s.id === selectedId)?.id ?? list?.[0]?.id ?? null
  const activeIdRef = React.useRef(activeId)
  React.useEffect(() => {
    activeIdRef.current = activeId
  }, [activeId])

  // poll รายการซีรีย์ (reloadKey เปลี่ยน = เริ่มรอบใหม่ทันที เช่น กดลองใหม่)
  React.useEffect(() => {
    let cancelled = false
    let timer: number | undefined
    const tick = async () => {
      try {
        const data = await fetchSeriesList()
        if (cancelled) return
        setList(data)
        setListError(null)
      } catch (err) {
        if (cancelled) return
        setListError(errorText(err, 'เชื่อมต่อ backend ไม่ได้'))
      }
      if (!cancelled) timer = window.setTimeout(() => void tick(), POLL_MS)
    }
    void tick()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [reloadKey])

  // poll รายละเอียดของซีรีย์ที่เลือก (เปลี่ยนซีรีย์ = ยกเลิกรอบเก่า ทิ้งผลที่ตอบกลับมาช้า)
  React.useEffect(() => {
    if (!activeId) return
    let cancelled = false
    let timer: number | undefined
    const tick = async () => {
      try {
        const data = await fetchSeries(activeId)
        if (cancelled) return
        setDetailState({ id: activeId, data })
        setDetailErrorState(null)
      } catch (err) {
        if (cancelled) return
        setDetailErrorState({ id: activeId, message: errorText(err, 'โหลดรายละเอียดไม่สำเร็จ') })
      }
      if (!cancelled) timer = window.setTimeout(() => void tick(), POLL_MS)
    }
    void tick()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [activeId, reloadKey])

  const handleControlled = React.useCallback((data: SeriesDetail) => {
    // ผลของการสั่งที่ตอบกลับหลังผู้ใช้เปลี่ยนซีรีย์แล้ว ไม่เอามาแสดง
    if (activeIdRef.current === data.id) setDetailState({ id: data.id, data })
    setReloadKey((k) => k + 1)
  }, [])

  const detail = detailState && detailState.id === activeId ? detailState.data : null
  const detailError =
    detailErrorState && detailErrorState.id === activeId ? detailErrorState.message : null
  const activeOverview = list?.find((s) => s.id === activeId)

  return (
    <Card className="shadow-lg">
      <CardHeader className="border-b border-border bg-card/60 backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-3 text-xl">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Tv className="h-5 w-5" />
            </span>
            ซีรีย์
          </CardTitle>
          <Button variant="outline" size="sm" onClick={() => setReloadKey((k) => k + 1)}>
            <RefreshCw className="mr-2 h-4 w-4" /> รีเฟรช
          </Button>
        </div>
      </CardHeader>

      <CardContent className="p-5">
        {listError && (
          <div className="mb-4 flex flex-wrap items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="font-medium">เชื่อมต่อ backend ไม่ได้</p>
              <p className="break-words text-xs opacity-80">{listError}</p>
            </div>
            <Button variant="outline" size="sm" onClick={() => setReloadKey((k) => k + 1)}>
              <RefreshCw className="mr-2 h-4 w-4" /> ลองใหม่
            </Button>
          </div>
        )}

        {list === null ? (
          !listError && (
            <div className="flex min-h-64 flex-col items-center justify-center gap-3 text-muted-foreground">
              <Loader2 className="h-8 w-8 animate-spin" />
              <p className="text-sm">กำลังโหลดซีรีย์...</p>
            </div>
          )
        ) : list.length === 0 ? (
          <div className="flex min-h-64 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border bg-muted/20 p-8 text-center">
            <Tv className="h-10 w-10 text-muted-foreground" />
            <p className="text-sm font-medium text-foreground">
              ยังไม่มีซีรีย์ — เปิด Claude Code แล้วใช้ prompt new_series ของ h3-studio
            </p>
          </div>
        ) : (
          <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
            <div className="grid content-start gap-2">
              {list.map((s) => (
                <SeriesRow
                  key={s.id}
                  series={s}
                  selected={s.id === activeId}
                  onSelect={() => setSelectedId(s.id)}
                />
              ))}
            </div>

            <div className="min-w-0">
              {detail ? (
                <>
                  {detailError && (
                    <p className="mb-3 break-words text-xs text-destructive">{detailError}</p>
                  )}
                  <SeriesDetailPanel
                    key={detail.id}
                    detail={detail}
                    overview={activeOverview}
                    onChanged={handleControlled}
                  />
                </>
              ) : detailError ? (
                <div className="flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span className="break-words">{detailError}</span>
                </div>
              ) : (
                <div className="flex min-h-64 items-center justify-center text-muted-foreground">
                  <Loader2 className="h-8 w-8 animate-spin" />
                </div>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
