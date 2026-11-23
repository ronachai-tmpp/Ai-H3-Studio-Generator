import { SeriesView } from '@/components/series/series-view'

/**
 * ========================================
 * Series Page
 * ========================================
 * หน้าดูความคืบหน้าซีรีย์ที่ Claude Code สร้างผ่าน MCP
 */
export default function SeriesPage() {
  return (
    <div className="p-4 md:p-6">
      <SeriesView />
    </div>
  )
}
