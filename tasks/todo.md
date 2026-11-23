# Series Runner + MCP

- Spec: `docs/superpowers/specs/2026-11-23-series-mcp-design.md` (อนุมัติแล้ว 2026-11-23)
- Plan: `docs/superpowers/plans/2026-11-23-series-mcp.md` (รายละเอียดทุก step อยู่ที่นี่)
- Branch: `feature/series-mcp`

## Tasks

- [ ] Task 1 — Models, validation, store (+ ตั้ง pytest)
- [ ] Task 2 — Service mutations (สร้างซีรีย์ ตัวละคร ตอน แก้ฉาก control)
- [ ] Task 3 — Manifest, export, review images
- [ ] Task 4 — Runner: ฉาก ผลลัพธ์งาน รวมตอน
- [ ] Task 5 — Runner: auto-casting + background thread
- [ ] Task 6 — Real gateway, lifespan wiring, REST
- [ ] Task 7 — MCP server (11 tools, guide, prompt `new_series`, `.mcp.json`, README)
- [ ] Task 8 — หน้าเว็บ `/series`

## Final verification

- [ ] pytest ทั้งชุดผ่าน
- [ ] `npm run lint` / `npx tsc --noEmit` / `npm run build` ไม่มีปัญหาใหม่
- [ ] `claude mcp list` เห็น `h3-studio`
- [ ] ทดสอบจริงกับ ComfyUI: 1 ตอน 2 ฉาก × 5 วินาที ที่ 0.1 MP ครบวงจรถึง export
- [ ] รีสตาร์ท backend กลางฉาก แล้วซีรีย์เดินต่อเอง
- [ ] หน้า `/studio` และ `/shortfilm` เดิมยังใช้ได้

## Review

(เติมหลังทำเสร็จ)
