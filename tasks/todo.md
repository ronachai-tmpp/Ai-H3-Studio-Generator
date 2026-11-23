# Series Runner + MCP

- Spec: `docs/superpowers/specs/2026-11-23-series-mcp-design.md` (อนุมัติแล้ว 2026-11-23)
- Plan: `docs/superpowers/plans/2026-11-23-series-mcp.md` (รายละเอียดทุก step อยู่ที่นี่)
- Branch: `feature/series-mcp`

## Tasks

- [x] Task 1 — Models, validation, store (+ ตั้ง pytest)
- [x] Task 2 — Service mutations (สร้างซีรีย์ ตัวละคร ตอน แก้ฉาก control)
- [x] Task 3 — Manifest, export, review images
- [x] Task 4 — Runner: ฉาก ผลลัพธ์งาน รวมตอน
- [x] Task 5 — Runner: auto-casting + background thread
- [x] Task 6 — Real gateway, lifespan wiring, REST
- [x] Task 7 — MCP server (11 tools, guide, prompt `new_series`, `.mcp.json`, README)
- [x] Task 8 — หน้าเว็บ `/series`

## Final verification

- [x] pytest ทั้งชุดผ่าน (155 tests)
- [x] `npx tsc --noEmit` ผ่าน, `npm run lint` ไม่มีปัญหาใหม่ (21 ข้อเดิมของโปรเจค)
- [ ] `npm run build` — ผ่านตอนจบ Task 8 แต่**ยังไม่ได้รันซ้ำ**หลังรอบแก้สุดท้าย (เว็บของเจ้าของเปิดใช้ `.next` อยู่) `start.bat` จะ build ให้เอง
- [ ] `claude mcp list` เห็น `h3-studio` — ยังไม่ได้ตรวจ ต้องรีสตาร์ท backend ที่พอร์ต 8000 ให้เป็นโค้ดใหม่ก่อน (ตรวจผ่าน JSON-RPC ตรง ๆ ที่พอร์ตทดสอบแล้ว: tool ครบ 11 ตัว + prompt `new_series`)
- [x] ทดสอบจริงกับ ComfyUI ผ่าน MCP: cast → หยุดให้ตรวจ → text / ref / chain → รวมตอน → export; เพิ่มตอนที่ 2 (chain ข้ามตอน) บนโค้ดล่าสุด
- [x] รีสตาร์ท backend กลางฉาก แล้วซีรีย์เดินต่อเอง
- [x] หน้า `/studio` และ `/shortfilm` เดิมยังใช้ได้ (เปิดดูใน browser ไม่มี console error; `/api/generations` แบบไม่มี `/` ท้ายยัง redirect ตามเดิม)

## Review

### สิ่งที่ได้
- ตัวรันซีรีย์ใน backend + MCP ที่ `/mcp` (11 tools, prompt `new_series`) + REST + หน้า `/series`
- 16 commits บน `feature/series-mcp`, backend test 155 ตัว (ก่อนหน้านี้ repo ไม่มี test)

### บั๊กที่กระบวนการจับได้ก่อนถึงมือผู้ใช้
- แผนสั่งต่อ MCP แบบครอบทุก path → หน้าเว็บเดิมเรียก `/api/generations` ไม่ได้ (404) — reviewer ของ Task 7 เจอ
- โหมด LAN ไม่เช็ค Origin → หน้าเว็บใดก็เรียก MCP ผ่าน browser ได้
- Casting ล้มทุกครั้งบนเครื่องนี้ เพราะ `extract_frame` แบบถอยหลังใช้ `-vsync` ที่ ffmpeg รุ่นใหม่ไม่รับ — เจอจากการรันจริงเท่านั้น
- `series_wait` ถือ lock บน event loop → backend ค้างทั้งตัวได้
- รอบแก้เรื่อง lock สร้าง race ใหม่ (เปลี่ยนรูปตัวละครระหว่างอัปโหลด) — re-review เจอ แก้ด้วย revision counter

### บทเรียน
- อย่าเชื่อ test ที่เช็คแค่ path ตรงเป๊ะ เมื่อแตะ routing ของแอปเดิม: ต้องมี test ของ redirect/405/404
- การรันจริงกับเครื่องจริงเจอบั๊กที่ test ปลอมไม่มีทางเจอ (เวอร์ชัน ffmpeg) — ทำก่อน review รอบสุดท้าย
- เช็คว่าโปรแกรมของเจ้าของเปิดอยู่ไหมก่อนสั่ง `npm run build`
- ข้อความสั่งงานเรื่องความปลอดภัยต้องไม่กำกวม ("ห้ามตั้ง X" ไม่ใช่ "หรือตั้ง X")

### ยังค้าง (ไม่ได้ทำรอบนี้)
- Bearer token สำหรับ `/mcp` โหมด LAN — รอเจ้าของตัดสิน
- `media_processor.extract_frame` (`-vsync`) และ `print` ภาษาไทยเมื่อ stdout ไม่ใช่ UTF-8 — บั๊กในโค้ดเดิม ไม่ได้แตะ
- รูปอ้างอิงตัวละครส่งให้ Claude ขนาดเต็ม, Ctrl+C อาจรอ `series_wait` นานถึง 5 นาที, ไม่มี retry ตอนเขียนไฟล์สถานะชนกับโปรแกรมอื่น
- ซับไตเติลฝังในวิดีโอ, ผูกกับ Projects/History (ตาม spec ข้อ 8)
