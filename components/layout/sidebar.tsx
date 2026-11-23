'use client'

/**
 * ========================================
 * Sidebar
 * ========================================
 * เมนูหลักด้านซ้ายของ Studio
 * - เมนูนำทาง 5 หน้า (Studio / Projects / History / Media / Settings)
 * - ไฮไลท์เมนูของหน้าปัจจุบันอัตโนมัติ
 * - แสดง brand ด้านบน และเวอร์ชันด้านล่าง
 * - รองรับโหมด drawer บนมือถือผ่าน props onClose / onNavigate
 */

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  Clapperboard,
  FolderOpen,
  History,
  Film,
  Image as ImageIcon,
  Images,
  LayoutDashboard,
  Settings,
  Tv,
  X,
} from 'lucide-react'

import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { href: '/', label: 'แดชบอร์ด', icon: LayoutDashboard },
  { href: '/studio', label: 'สร้างคลิปสั้น', icon: Clapperboard },
  { href: '/shortfilm', label: 'สร้างหนังสั้น', icon: Film },
  { href: '/series', label: 'ซีรีย์', icon: Tv },
  { href: '/projects', label: 'โปรเจค', icon: FolderOpen },
  { href: '/history', label: 'ประวัติ', icon: History },
  { href: '/media', label: 'มีเดีย', icon: ImageIcon },
  { href: '/frames', label: 'เฟรม', icon: Images },
  { href: '/settings', label: 'ตั้งค่า', icon: Settings },
] as const

function isActive(href: string, pathname: string): boolean {
  if (href === '/') return pathname === '/'
  return pathname.startsWith(href)
}

interface SidebarProps {
  /** ถ้าส่งมา = โหมด drawer มือถือ จะแสดงปุ่มปิด */
  onClose?: () => void
  /** เรียกเมื่อเลือกเมนู (ใช้ปิด drawer) */
  onNavigate?: () => void
}

export function Sidebar({ onClose, onNavigate }: SidebarProps) {
  const pathname = usePathname()

  return (
    <aside className="flex h-full w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
      {/* Brand */}
      <div className="flex items-center gap-2.5 px-4 py-4">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-md">
          <Clapperboard className="h-5 w-5" />
        </div>

        <div className="flex min-w-0 flex-col leading-tight">
          <span className="truncate text-sm font-bold tracking-tight">
            Ai-H3-Studio-Generator
          </span>
          <span className="text-[11px] text-muted-foreground">
            AI Video Generation
          </span>
        </div>

        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="ปิดเมนู"
            className="ml-auto flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* เมนูนำทาง */}
      <nav
        className={cn(
          'flex-1 space-y-1 overflow-y-auto px-2 py-2',
          '[scrollbar-width:thin] [scrollbar-color:var(--sidebar-border)_transparent]'
        )}
      >
        {NAV_ITEMS.map((item) => {
          const active = isActive(item.href, pathname)
          const Icon = item.icon

          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              className={cn(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                active
                  ? 'bg-sidebar-accent text-sidebar-accent-foreground shadow-sm'
                  : 'text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground'
              )}
            >
              <Icon className={cn('h-4 w-4 shrink-0', active && 'text-primary')} />
              <span className="truncate">{item.label}</span>
            </Link>
          )
        })}
      </nav>

      {/* เวอร์ชัน */}
      <div className="border-t border-sidebar-border px-4 py-3">
        <p className="text-[11px] text-muted-foreground">
          Dev. By{" "}
          <a
            href="https://www.facebook.com/tonlikeit"
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-foreground transition-colors"
          >
            Ton Like IT
          </a>{" "}
          ❤️
        </p>
      </div>
    </aside>
  )
}