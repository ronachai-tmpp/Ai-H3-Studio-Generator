/**
 * ========================================
 * Backend API Helper
 * ========================================
 * Description:
 * รวมฟังก์ชันสำหรับเชื่อมต่อ FastAPI backend จากฝั่ง Next.js
 *
 * Functions:
 * - BACKEND_URL : URL base ของ backend (env override หรือ runtime hostname)
 * - checkBackendHealth() : ตรวจสอบว่า backend รันอยู่หรือไม่
 * - fetchGenerations() : ดึงรายการงานจาก queue
 * - createGeneration() : สร้างงานเข้าคิว
 * - cancelGeneration() : ยกเลิกงาน
 * - deleteGeneration() : ลบงาน
 * - clearFinishedGenerations() : ลบงานที่เสร็จแล้วทั้งหมด
 * - uploadReferenceFiles() : อัปโหลด reference เข้า ComfyUI/input
 * - getMediaUrl() : แปลง video_path/thumbnail_path เป็น URL สำหรับเปิดดู
 */

import type { GenStatus } from '@/types'

/**
 * หา URL ของ FastAPI backend ตอน runtime
 *
 * ลำดับความสำคัญ:
 * 1. NEXT_PUBLIC_BACKEND_URL — ถ้าตั้งไว้ ใช้ค่านั้นเสมอ
 *    (กรณีพิเศษ เช่น reverse proxy / backend คนละเครื่อง)
 * 2. ถ้าเปิดใน browser → ใช้ hostname เดียวกับที่เปิดเว็บ + พอร์ต 8000
 *    เช่น เปิด http://10.1.1.1:3000 → backend = http://10.1.1.1:8000
 *    ทำให้แจก FC ได้โดยไม่ต้องแก้ env / build ใหม่เมื่อ IP เปลี่ยน
 * 3. ถ้ารันฝั่ง server (SSR) → fallback http://127.0.0.1:8000
 *
 * Note:
 * - ค่า env ต้องว่าง/ไม่ตั้ง เพื่อใช้โหมด runtime hostname
 * - backend ต้องเปิด --host 0.0.0.0 และ CORS รับ origin LAN
 */
function resolveBackendUrl(): string {
  const fromEnv = (process.env.NEXT_PUBLIC_BACKEND_URL ?? '').trim()

  if (fromEnv) {
    return fromEnv.replace(/\/+$/, '')
  }

  if (typeof window !== 'undefined') {
    return `${window.location.protocol}//${window.location.hostname}:8000`
  }

  return 'http://127.0.0.1:8000'
}

/**
 * URL ของ FastAPI backend ที่ใช้ทั่วทั้งแอป
 */
export const BACKEND_URL = resolveBackendUrl()

/**
 * โครงสร้างข้อมูลตอบกลับจาก /api/system/health
 */
export interface BackendHealthResponse {
  status: string
  service?: string
}

/**
 * ผลการตรวจสอบ backend ที่ผ่านการจัดการ error แล้ว
 * ใช้แสดงบน UI ได้ทันที
 */
export interface BackendHealthResult {
  ok: boolean
  message: string
  data?: BackendHealthResponse
}

/**
 * โครงสร้างข้อมูลงาน 1 งานจาก backend queue
 */
export interface QueueJobResponse {
  id: string
  prompt: string
  negative_prompt?: string | null
  type: string
  resolution: string
  aspect_ratio?: string | null
  steps: number
  seed: number
  duration_seconds?: number
  task_adapter?: string | null
  lora_used?: string | null
  status: GenStatus
  progress: number
  current_step: number
  total_steps: number
  message: string
  reference_count: number
  reference_names: string[]
  audio_reference_names?: string[]
  error?: string | null
  created_at: string
  updated_at: string
  stage?: string | null
  engine?: string | null
  comfyui_prompt_id?: string | null
  video_path?: string | null
  thumbnail_path?: string | null
  output_filename?: string | null
  duration?: number | null
}

/**
 * Payload สำหรับสร้างงาน generate ใหม่
 */
export interface CreateGenerationPayload {
  prompt: string
  negative_prompt?: string
  type: string
  resolution: string
  aspect_ratio?: string
  steps: number
  seed: number
  duration_seconds?: number
  task_adapter?: string
  lora_used?: string
  reference_names?: string[]
  audio_reference_names?: string[]
  first_frame_name?: string | null
  last_frame_name?: string | null
}

/**
 * helper กลางสำหรับเรียก backend API
 *
 * Description:
 * - เพิ่ม timeout ด้วย AbortController
 * - แปลง error จาก FastAPI detail เป็น message ที่อ่านง่าย
 * - คืน JSON ตาม type ที่กำหนด
 */
async function apiFetch<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 10000
): Promise<T> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const response = await fetch(`${BACKEND_URL}${path}`, {
      ...init,
      signal: controller.signal,
      cache: 'no-store',
    })

    if (!response.ok) {
      let message = `Backend ตอบกลับสถานะ HTTP ${response.status}`

      try {
        const data = (await response.json()) as {
          detail?: string | Array<{ msg?: string }>
        }

        if (typeof data.detail === 'string') {
          message = data.detail
        } else if (Array.isArray(data.detail)) {
          message = data.detail
            .map((item) => item.msg)
            .filter(Boolean)
            .join(', ')
        }
      } catch {
        // ถ้า parse JSON ไม่ได้ ให้ใช้ message เริ่มต้น
      }

      throw new Error(message)
    }

    return (await response.json()) as T
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error(
        `Backend ไม่ตอบสนองภายใน ${Math.round(timeoutMs / 1000)} วินาที`
      )
    }

    if (error instanceof Error) {
      throw error
    }

    throw new Error('ไม่สามารถเชื่อมต่อ FastAPI backend ได้')
  } finally {
    clearTimeout(timeoutId)
  }
}

/**
 * ตรวจสอบสุขภาพของ FastAPI backend
 *
 * @param timeoutMs เวลาสูงสุดก่อน abort request
 * @returns ผลการเชื่อมต่อพร้อมข้อความสำหรับแสดงบน UI
 */
export async function checkBackendHealth(
  timeoutMs = 3000
): Promise<BackendHealthResult> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const response = await fetch(`${BACKEND_URL}/api/system/health`, {
      method: 'GET',
      signal: controller.signal,
      cache: 'no-store',
    })

    if (!response.ok) {
      return {
        ok: false,
        message: `Backend ตอบกลับสถานะ HTTP ${response.status}`,
      }
    }

    const data = (await response.json()) as BackendHealthResponse

    if (data.status === 'ok') {
      return {
        ok: true,
        message: 'เชื่อมต่อ FastAPI backend สำเร็จ',
        data,
      }
    }

    return {
      ok: false,
      message: 'Backend ตอบกลับแต่สถานะไม่ปกติ',
      data,
    }
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      return {
        ok: false,
        message: `Backend ไม่ตอบสนองภายใน ${Math.round(timeoutMs / 1000)} วินาที`,
      }
    }

    return {
      ok: false,
      message: 'ไม่สามารถเชื่อมต่อ FastAPI backend ได้',
    }
  } finally {
    clearTimeout(timeoutId)
  }
}

/**
 * ดึงรายการงานทั้งหมดจาก backend queue
 *
 * @param limit จำนวนงานสูงสุด
 */
export async function fetchGenerations(
  limit = 100
): Promise<QueueJobResponse[]> {
  return apiFetch<QueueJobResponse[]>(`/api/generations?limit=${limit}`, {
    method: 'GET',
  })
}

/**
 * สร้างงานใหม่เข้าคิวใน backend
 *
 * @param payload ข้อมูลงานที่ต้องการสร้าง
 */
export async function createGeneration(
  payload: CreateGenerationPayload
): Promise<QueueJobResponse> {
  return apiFetch<QueueJobResponse>('/api/generations', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
}

/**
 * ยกเลิกงานตาม id
 *
 * @param jobId id ของงาน
 */
export async function cancelGeneration(
  jobId: string
): Promise<QueueJobResponse> {
  return apiFetch<QueueJobResponse>(`/api/generations/${jobId}/cancel`, {
    method: 'POST',
  })
}

/**
 * ลบงานออกจากคิวตาม id
 *
 * @param jobId id ของงาน
 */
export async function deleteGeneration(
  jobId: string
): Promise<{ deleted: boolean }> {
  return apiFetch<{ deleted: boolean }>(`/api/generations/${jobId}`, {
    method: 'DELETE',
  })
}

/**
 * ลบงานที่เสร็จแล้ว/ยกเลิกแล้ว/ล้มเหลวออกจากคิวทั้งหมด
 */
export async function clearFinishedGenerations(): Promise<{ deleted: number }> {
  return apiFetch<{ deleted: number }>('/api/generations/clear-finished', {
    method: 'POST',
  })
}

/**
 * ========================================
 * Upload Reference API
 * ========================================
 * Description:
 * อัปโหลด reference files ไปยัง FastAPI backend
 * เพื่อบันทึกลง ComfyUI/input directory
 *
 * Important:
 * ComfyUI LoadImage มักต้องใช้ filename เท่านั้น ไม่ใช่ absolute path
 * ดังนั้นฟังก์ชันนี้จะคืนค่า stored_filename สำหรับส่งเข้า workflow
 */

/**
 * โครงสร้างข้อมูลไฟล์ reference ที่อัปโหลดสำเร็จ
 */
export interface UploadedReferenceFile {
  original_name: string
  stored_filename: string
  stored_path: string
  type: string
  extension: string
  size_bytes: number
  size_mb: number
}

/**
 * โครงสร้าง response จาก POST /api/uploads/references
 */
export interface UploadReferencesResponse {
  status: string
  input_dir: string
  count: number
  uploaded: UploadedReferenceFile[]
}

/**
 * อัปโหลด reference files หลายไฟล์ไปยัง backend
 *
 * @param files รายการ File จาก browser
 * @param timeoutMs เวลาสูงสุดในการอัปโหลด ค่า default 120 วินาที
 * @returns รายการไฟล์ที่อัปโหลดสำเร็จ พร้อม stored_filename
 *
 * Description:
 * - ใช้ endpoint /api/uploads/references แบบ batch
 * - ไม่ตั้ง Content-Type เอง เพราะ FormData จะจัดการ boundary ให้
 * - ถ้าไฟล์มากกว่า 10 ไฟล์ จะ throw error ก่อนส่ง request
 */
export async function uploadReferenceFiles(
  files: File[],
  timeoutMs = 120000
): Promise<UploadedReferenceFile[]> {
  if (files.length === 0) return []

  if (files.length > 10) {
    throw new Error('อัปโหลด reference ได้สูงสุด 10 ไฟล์ต่อครั้ง')
  }

  const formData = new FormData()

  for (const file of files) {
    formData.append('files', file)
  }

  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const response = await fetch(`${BACKEND_URL}/api/uploads/references`, {
      method: 'POST',
      body: formData,
      signal: controller.signal,
      cache: 'no-store',
    })

    if (!response.ok) {
      let message = `อัปโหลด reference ล้มเหลว HTTP ${response.status}`

      try {
        const data = (await response.json()) as {
          detail?: string | Array<{ msg?: string }>
        }

        if (typeof data.detail === 'string') {
          message = data.detail
        } else if (Array.isArray(data.detail)) {
          message = data.detail
            .map((item) => item.msg)
            .filter(Boolean)
            .join(', ')
        }
      } catch {
        // ถ้า parse JSON ไม่ได้ ให้ใช้ message เริ่มต้น
      }

      throw new Error(message)
    }

    const data = (await response.json()) as UploadReferencesResponse
    return data.uploaded
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error(
        `อัปโหลด reference ใช้เวลานานเกิน ${Math.round(timeoutMs / 1000)} วินาที`
      )
    }

    if (error instanceof Error) {
      throw error
    }

    throw new Error('ไม่สามารถอัปโหลด reference ได้')
  } finally {
    clearTimeout(timeoutId)
  }
}

/**
 * ========================================
 * Media URL Helper
 * ========================================
 * Description:
 * แปลง path จาก backend เช่น "videos/xxxx.mp4"
 * ให้เป็น URL สำหรับเปิดดูผ่าน /api/media/videos/xxxx.mp4
 *
 * Notes:
 * - ถ้า path เป็น http/https อยู่แล้ว ให้คืนค่าเดิม
 * - ใช้กับ video_path / thumbnail_path จาก queue หรือ history
 */
export function getMediaUrl(mediaPath?: string | null): string | null {
  if (!mediaPath) return null

  const value = mediaPath.trim()
  if (!value) return null

  if (/^https?:\/\//i.test(value)) {
    return value
  }

  const normalized = value.replace(/^\/+/, '')

  return `${BACKEND_URL}/api/media/${normalized}`
}

/**
 * ========================================
 * Extract Frame API
 * ========================================
 * Description:
 * ดึงเฟรมแรก/สุดท้ายของวิดีโอแบบ manual
 * พร้อมส่งเข้า ComfyUI input เพื่อใช้ต่อคลิป
 */

export interface ExtractFramePayload {
  path: string
  position: 'first' | 'last'
  offset_from_end?: number
  upload_to_comfyui?: boolean
}

export interface ExtractFrameResponse {
  status: string
  frame_path: string
  position: string
  offset_from_end: number
  stored_filename: string | null
}

export async function extractFrame(
  payload: ExtractFramePayload
): Promise<ExtractFrameResponse> {
  return apiFetch<ExtractFrameResponse>('/api/media/extract-frame', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
}

/**
 * ========================================
 * Concat Videos API
 * ========================================
 * รวมหลายคลิปเป็นไฟล์เดียวด้วย ffmpeg (เรียงตามลำดับที่ส่ง)
 */

export interface ConcatVideosPayload {
  paths: string[]
  title?: string
}

export interface ConcatVideosResponse {
  status: string
  video_path: string
  thumbnail_path: string | null
  duration: number | null
  mode: 'copy' | 'reencode'
}

/**
 * ========================================
 * Delete Media File API
 * ========================================
 * ลบไฟล์วิดีโอ / thumbnail / เฟรม จาก outputs/ ของ backend
 */
export async function deleteMediaFile(
  relativePath: string
): Promise<{ deleted: boolean; path: string; error?: string }> {
  return apiFetch<{ deleted: boolean; path: string; error?: string }>(
    '/api/media/delete',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: relativePath }),
    }
  )
}

export async function concatVideos(
  payload: ConcatVideosPayload,
  timeoutMs = 600000
): Promise<ConcatVideosResponse> {
  return apiFetch<ConcatVideosResponse>(
    '/api/media/concat',
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    },
    timeoutMs
  )
}

/**
 * ========================================
 * Frame Management API
 * ========================================
 */

export interface FrameItem {
  path: string
  filename: string
  source_id: string
  position: 'first' | 'last'
  offset_from_end: number
  size_bytes: number
  size_kb: number
  modified_at: string
}

export interface FramesListResponse {
  count: number
  total_size_mb: number
  frames: FrameItem[]
}

export async function fetchFrames(): Promise<FramesListResponse> {
  return apiFetch<FramesListResponse>('/api/media/frames/list', { method: 'POST' })
}

export async function deleteFramesBatch(
  paths: string[]
): Promise<{ deleted: string[]; failed: string[]; count: number }> {
  return apiFetch('/api/media/frames/delete-batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paths }),
  })
}

export async function sendFrameToComfyUI(
  path: string
): Promise<{ stored_filename: string | null; warning?: string }> {
  return apiFetch('/api/media/frames/send-to-comfyui', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
}

/**
 * ========================================
 * Frame URL Helper
 * ========================================
 * เฟรมเสิร์ฟผ่าน /api/system/frames/file (media router อนุญาตเฉพาะ videos/thumbnails)
 */
export function getFrameUrl(framePath?: string | null): string | null {
  if (!framePath) return null

  const value = framePath.trim()
  if (!value) return null

  if (/^https?:\/\//i.test(value)) return value

  const normalized = value.replace(/^\/+/, '')
  return `${BACKEND_URL}/api/system/frames/file?path=${encodeURIComponent(normalized)}`
}

/**
 * ========================================
 * Projects API
 * ========================================
 */

export interface ProjectSummary {
  id: string
  name: string
  description: string | null
  createdAt: string
  updatedAt: string
  _count: { generations: number }
}

export async function fetchProjects(): Promise<ProjectSummary[]> {
  const response = await fetch('/api/projects', { method: 'GET', cache: 'no-store' })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json() as Promise<ProjectSummary[]>
}

export async function createProject(
  name: string,
  description: string | null
): Promise<ProjectSummary> {
  const response = await fetch('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json() as Promise<ProjectSummary>
}

/**
 * ========================================
 * Bulk Move History to Project
 * ========================================
 * ย้ายหลาย generation ไปยังโปรเจคเดียวกัน (หรือ null = นำออก)
 */

export async function bulkMoveToProject(
  ids: string[],
  projectId: string | null
): Promise<{ moved: number }> {
  const response = await fetch('/api/history/bulk-move', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids, projectId }),
  })
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new Error(text || `HTTP ${response.status}`)
  }
  return response.json() as Promise<{ moved: number }>
}

/**
 * ========================================
 * Storage Stats API
 * ========================================
 */
export interface StorageDirStats {
  count: number
  bytes: number
}

export interface StorageStats {
  videos: StorageDirStats
  thumbnails: StorageDirStats
  frames: StorageDirStats
  total_bytes: number
  total_mb: number
  total_gb: number
}

export async function fetchStorageStats(): Promise<StorageStats> {
  return apiFetch<StorageStats>('/api/system/storage-stats')
}

/**
 * ========================================
 * Prompt Enhance API (Gemma VLM บน ComfyUI)
 * ========================================
 */

export const PROMPT_TEMPLATES = [
  { id: 'cinematic_fl2v', label: 'Cinematic H3 FL2V (ค่าเริ่มต้น)' },
  { id: 'three_field', label: '3-field cinematic (description/soundscape/music)' },
  { id: 'describe_only', label: 'บรรยายภาพละเอียด (ไม่ใส่ story)' },
  { id: 'continuation', label: 'ต่อฉาก (continuing motion)' },
] as const

export interface PromptEnhancePayload {
  story?: string
  template_id?: string
  custom_instruction?: string | null
  image_names?: string[]
  video_path?: string | null
  max_frames?: number
  max_length?: number
  temperature?: number
  seed?: number
}

export interface PromptEnhanceResponse {
  status: string
  prompt: string
  prompt_id: string
  images_used: number
  instruction: string
}

export async function enhancePrompt(
  payload: PromptEnhancePayload,
  timeoutMs = 300000
): Promise<PromptEnhanceResponse> {
  return apiFetch<PromptEnhanceResponse>(
    '/api/system/prompt-enhance',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    timeoutMs
  )
}
/**
 * ========================================
 * Series API
 * ========================================
 * หน้าเว็บ /series ใช้ดูความคืบหน้าและสั่งหยุด/รันต่อ/ยกเลิกเท่านั้น
 * (การสร้างเนื้อหาทำผ่าน MCP) path ในผลลัพธ์เป็น relative ใต้ outputs
 * เปิดดูได้ด้วย getMediaUrl() / getFrameUrl()
 */

export type SeriesStatus = 'DRAFT' | 'RUNNING' | 'PAUSED' | 'DONE' | 'CANCELLED'
export type SceneStatus = 'PENDING' | 'QUEUED' | 'RUNNING' | 'DONE' | 'FAILED'

export interface SeriesProgress {
  scenes_done: number
  scenes_total: number
  avg_scene_seconds: number | null
  eta_seconds: number | null
}

export interface SeriesOverview {
  id: string
  title: string
  status: SeriesStatus
  pause_reason: string | null
  waiting_for: string | null
  episodes_done: number
  episodes_total: number
  progress: SeriesProgress
}

export interface SeriesScene {
  index: number
  prompt: string
  beat: string
  mode: 'text' | 'ref' | 'chain'
  characters: string[]
  duration_seconds: number
  status: SceneStatus
  progress: number
  attempts: number
  error: string | null
  video_path: string | null
  thumbnail_path: string | null
  last_frame_path: string | null
}

export interface SeriesEpisode {
  number: number
  title: string
  synopsis: string
  caption: string
  hashtags: string[]
  status: 'PENDING' | 'RUNNING' | 'DONE'
  scenes: SeriesScene[]
  final_video_path: string | null
  thumbnail_path: string | null
  duration: number | null
}

export interface SeriesDetail
  extends Omit<SeriesOverview, 'episodes_done' | 'episodes_total'> {
  logline: string
  run_mode: string
  pause_message: string | null
  story_complete: boolean
  episodes: SeriesEpisode[]
}

/** route ลงทะเบียนแบบมี trailing slash จึงต้องเรียก /api/series/ */
export async function fetchSeriesList(): Promise<SeriesOverview[]> {
  return apiFetch<SeriesOverview[]>('/api/series/', { method: 'GET' })
}

export async function fetchSeries(id: string): Promise<SeriesDetail> {
  return apiFetch<SeriesDetail>(`/api/series/${encodeURIComponent(id)}`, {
    method: 'GET',
  })
}

export async function controlSeries(
  id: string,
  action: 'pause' | 'resume' | 'cancel'
): Promise<SeriesDetail> {
  return apiFetch<SeriesDetail>(`/api/series/${encodeURIComponent(id)}/control`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action }),
  })
}
