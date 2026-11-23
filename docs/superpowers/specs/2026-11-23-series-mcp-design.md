# Series Runner + MCP — Design

วันที่: 2026-11-23
สถานะ: รออนุมัติ

## 1. เจตนาและเหตุผล

เจ้าของโปรเจคต้องการผลิต **ซีรีย์แนวตั้ง (9:16)** เป็นตอน ๆ จนจบเรื่อง เพื่อโพสต์ทำรายได้
และในอนาคตอาจทำแอพให้สมาชิกจ่ายเงินเข้ามาดู

วิธีทำงานที่ต้องการ: เปิด Claude Code แล้วบอกไอเดียเรื่อง Claude Code เป็นคนเขียนบท แตกเป็นตอน
แตกตอนเป็นฉาก เขียน prompt ของแต่ละฉาก แล้วส่งให้ H3 Studio gen วิดีโอต่อเนื่องกันไปจนจบเรื่อง
โดยคนไม่ต้องนั่งกดทีละคลิป

ตอนนี้ทำไม่ได้เพราะ:

- backend ไม่มีแนวคิด "เรื่อง / ตอน / ฉาก" — มีแค่คิวงานทีละคลิป
- การต่อฉาก (ดึง last frame ไปเป็น first frame ของคลิปถัดไป) ทำในหน้า Short Film ซึ่งอยู่ใน
  browser + localStorage ทั้งหมด และจำกัด 4 ฉาก
- ไม่มีช่องทางให้ Claude Code สั่งงาน (ไม่มี MCP)

## 2. เป้าหมาย / สิ่งที่ไม่ทำ / สิ่งที่ห้ามเกิด

### เป้าหมาย

1. Claude Code สร้างซีรีย์ เพิ่มตัวละคร เขียนตอน (ฉาก + prompt) และสั่งรันได้ผ่าน MCP tools
2. backend รันซีรีย์เองจนจบ: gen ทีละฉาก ต่อฉาก รวมคลิปเป็นไฟล์ตอน โดย**ไม่ต้องพึ่ง
   Claude Code session หรือ browser ที่เปิดค้าง**
3. รีสตาร์ท backend แล้วซีรีย์เดินต่อจากจุดเดิม
4. ตัวละครหน้าเดิมข้ามฉากและข้ามตอน เท่าที่โมเดลทำได้
5. Claude ตรวจผลด้วยภาพ แล้วแก้ prompt / สั่ง gen ฉากใหม่ได้
6. ได้ชุดไฟล์พร้อมโพสต์: วิดีโอรายตอน + ชื่อตอน + caption + hashtags + `manifest.json`
7. มีหน้าเว็บดูความคืบหน้าและเล่นวิดีโอรายตอน

### สิ่งที่ไม่ทำในรอบนี้

- ซับไตเติลฝังในวิดีโอ
- อัปโหลด/โพสต์ไปแพลตฟอร์มใด ๆ อัตโนมัติ
- แอพสมาชิก ระบบจ่ายเงิน ระบบ login
- ย้ายข้อมูลซีรีย์เข้า Prisma / ผูกกับ Projects และ History
- แก้ไขซีรีย์จากหน้าเว็บ (หน้าเว็บรอบนี้ดูอย่างเดียว + pause/resume/cancel)
- ตรวจคุณภาพเสียงและ lip-sync อัตโนมัติ (Claude ฟังเสียงไม่ได้ ต้องให้คนตรวจ)
- เปลี่ยน workflow ของ ComfyUI หรือพฤติกรรมของ endpoint เดิม

### สิ่งที่ห้ามเกิด

- GPU รันทิ้งหลายชั่วโมงกับงานที่พังซ้ำ ๆ — ฉากที่ล้มเหลวต้อง retry จำกัดครั้ง แล้วหยุดรอคน
- ลบไฟล์ของผู้ใช้ — การ gen ใหม่/รวมใหม่ทิ้งไฟล์เก่าไว้ ไม่ลบ
- คนอื่นในวง LAN ใช้ MCP อ่านไฟล์ในเครื่องได้ (ดูข้อ 4)
- ทำให้หน้า Studio / Short Film / คิวเดิมพังหรือเปลี่ยนพฤติกรรม

## 3. ข้อจำกัดที่มีอยู่

- Windows, backend เป็น FastAPI บน Python venv (เครื่องนี้ Python 3.13), frontend เป็น Next.js 16
- คิว (`queue_service`) อยู่ใน RAM, worker เดียว, FIFO, ใช้ร่วมกับผู้ใช้หน้าเว็บทุกคน
- คลิปหนึ่งยาวได้ 5 / 8 / 10 / 12 / 15 วินาที และ megapixels 0.1 / 0.25 / 0.35 / 0.5 / 0.75 / 1.0
  — รายการนี้มีอยู่แค่ใน dropdown ของ frontend ฝั่ง backend รับ 1–30 วินาที และ 0.1–2.0 MP
  โค้ดซีรีย์จึงต้องประกาศรายการค่าที่อนุญาตของตัวเองและตรวจเอง
- `negative_prompt` ถูกเก็บในงานแต่ไม่ถูกส่งเข้า workflow ใดเลย ซีรีย์จึงไม่มี field นี้
- ต่อ FL2VA ติดกันหลายคลิปแล้วตัวละครเพี้ยนสะสม (README แนะนำกลับ REF2VA ทุก 2–3 ฉาก)
- ไฟล์ผลลัพธ์ของงานตั้งชื่อตาม job id แน่นอน: `outputs/videos/{job_id}.mp4`,
  `outputs/frames/{job_id}_last.jpg`, `outputs/thumbnails/{job_id}.jpg`
- backend bind `0.0.0.0` (ผ่าน `start.bat` / `start-fast.bat`; `backend/run.bat` bind `127.0.0.1` พร้อม `--reload`)
  ไม่มี auth และไม่มี test ใด ๆ ใน repo
- คิวตั้งสถานะ `CANCELLED` ให้งานที่กำลังรันตอน backend ปิดด้วย ไม่ใช่เฉพาะตอนผู้ใช้กดยกเลิก
- History/Media ของหน้าเว็บเติมโดย `QueueHistorySync` ซึ่งเป็น component ใน browser:
  จะบันทึกก็ต่อเมื่อมีแท็บเว็บเปิดอยู่ขณะที่งานยังอยู่ในคิว และปุ่มลบใน History/Media ลบไฟล์วิดีโอจริง
- `outputs/` ถูก gitignore อยู่แล้ว
- ต้องรองรับทั้งโหมด Local และ RunPod (`config.COMFYUI_IS_REMOTE`) และโหมด Low VRAM (GGUF)
- โค้ดเดิม comment เป็นภาษาไทย — โค้ดใหม่ทำตามสไตล์เดิม

## 4. แนวทาง

| | แนวทาง | ข้อดี | ข้อเสีย |
|---|---|---|---|
| **A (เลือก)** | ตัวรันซีรีย์อยู่ใน backend, สถานะเป็น JSON บนดิสก์, MCP ฝังใน FastAPI ที่ `/mcp` (Streamable HTTP) | รันข้ามคืนได้ ไม่พึ่ง session, resume ได้, ไม่มี process เพิ่ม, dependency เพิ่มตัวเดียว (`mcp`) | backend ต้องเปิดก่อน Claude Code จึงจะเห็น tool |
| B | MCP stdio บาง ๆ ให้ Claude Code สั่งทีละคลิปผ่าน REST เดิม | โค้ดน้อยสุด | เรื่องยาวหลายชั่วโมง session หลุดแล้วค้าง ไม่มี resume ไม่ตอบเป้าหมายข้อ 2–3 |
| C | เก็บซีรีย์ใน Prisma, หน้าเว็บเป็นตัวหลัก | DB จริง พร้อมต่อยอดเป็นแอพ | Python เข้า Prisma ไม่ได้ ต้องพึ่ง Next.js เปิดตลอด โค้ดเพิ่มเท่าตัว เกินขอบเขตรอบนี้ |

เจ้าของโปรเจคมอบการตัดสินใจด้าน "วิธีสร้าง" ให้ผู้ออกแบบ ผู้ออกแบบเลือก **A**
`manifest.json` ที่ A สร้าง คือสะพานไปสู่แอพสมาชิกในอนาคตโดยไม่ต้องทำ C ตอนนี้

## 5. การออกแบบ

### 5.1 ภาพรวม

```
Claude Code ──MCP (HTTP, localhost)──┐
                                     ▼
หน้าเว็บ /series ──REST──▶ series_service ──▶ queue_service (เดิม) ──▶ ComfyUI
                               │   ▲
                               ▼   │ อ่านผลจากไฟล์ outputs/
                    outputs/series/<id>/series.json
```

ชิ้นส่วนใหม่:

| ไฟล์ | หน้าที่ |
|---|---|
| `backend/app/services/series_service.py` (แยกเป็น store / runner ได้ตามเห็นควร) | โมเดลข้อมูล, เก็บ/โหลด JSON, ตัวรัน (thread) |
| `backend/app/routers/series.py` | REST สำหรับหน้าเว็บ |
| `backend/app/mcp_server.py` | MCP tools + prompt, mount เข้า FastAPI ที่ `/mcp` |
| `backend/tests/` | pytest ของ state machine |
| `.mcp.json` (root ของ repo) | ลงทะเบียน server ชื่อ `h3-studio` ให้ Claude Code: `{"type":"http","url":"http://127.0.0.1:8000/mcp"}` |
| `app/(studio)/series/page.tsx`, `components/series/series-view.tsx` | หน้าดูความคืบหน้า |

ของเดิมที่แตะ: `backend/app/main.py` (include router, mount MCP, start/stop runner ใน lifespan),
`backend/requirements.txt` (+`mcp`), `lib/backend.ts` (ฟังก์ชันเรียก REST ใหม่),
`components/layout/sidebar.tsx` (เมนู "ซีรีย์"), `README.md` (วิธีใช้)

ตัวรันเรียก `queue_service.create_job / get_job / cancel_job` และฟังก์ชันใน `media_processor`
(`extract_frame`, `concat_videos`, `process_video_outputs`, `extract_video_frames`) โดยตรงใน process เดียวกัน
ไม่ยิง HTTP หาตัวเอง

### 5.2 โมเดลข้อมูล

เก็บที่ `outputs/series/<series_id>/series.json` เขียนแบบ atomic (เขียนไฟล์ temp แล้ว replace)

**Series**

| field | ค่า |
|---|---|
| `id` | slug จากชื่อ + สุ่มสั้น ๆ |
| `title`, `logline`, `style_notes` | ข้อความ (style_notes เป็นบันทึกสำหรับ Claude ไม่ถูกต่อเข้า prompt อัตโนมัติ) |
| `aspect_ratio` | ค่าเริ่มต้น `"9:16 (Portrait Widescreen)"` ต้องอยู่ใน `ALLOWED_ASPECT_RATIOS` |
| `megapixels` | ค่าเริ่มต้น `0.35` |
| `low_vram` | bool ค่าเริ่มต้น `false` — เลือกชนิดงาน `*_LOW` |
| `run_mode` | `"autopilot"` (ค่าเริ่มต้น) หรือ `"review"` |
| `max_attempts` | ค่าเริ่มต้น `2` ต่อฉาก |
| `status` | `DRAFT` → `RUNNING` ⇄ `PAUSED` → `DONE` / `CANCELLED` (`DONE` เปิดกลับเป็น `RUNNING` ได้ ดู 5.5; `CANCELLED` เป็นสถานะสุดท้าย) |
| `pause_reason`, `pause_message` | `user` / `review` / `casting` / `error` |
| `story_complete` | bool — Claude ประกาศว่าเขียนครบทุกตอนแล้ว |
| `characters[]`, `episodes[]` | ดูด้านล่าง |

`DONE` เกิดเมื่อ `story_complete` และทุกตอน `DONE` ถ้า `RUNNING` แต่ไม่มีตอนให้ทำและยังไม่
`story_complete` ซีรีย์ "ว่างรอตอนใหม่" (ยัง `RUNNING`, รายงานเป็น `waiting_for: "episodes"`)
— รองรับทั้งการเขียนทุกตอนล่วงหน้า และการเขียนตอนถัดไปหลังดูผลตอนก่อน

**Character**: `name` (ไม่ซ้ำในซีรีย์), `description`, `reference_images[]`, `casting_prompt` (ไม่บังคับ)

- รูปอ้างอิงถูก**คัดลอกมาเก็บถาวร**ที่ `outputs/series/<id>/refs/` เสมอ
- ชื่อไฟล์ฝั่ง ComfyUI input ถูก cache คู่กับ base URL ของ ComfyUI ถ้า URL เปลี่ยน (สลับ Local/RunPod)
  หรือไฟล์หายจาก input (โหมด local ตรวจได้) ให้ push ใหม่จากสำเนาถาวร
- **Auto-casting**: ตัวละครที่ไม่มีรูปแต่มี `casting_prompt` — ตัวรันจะ gen คลิป T2V 5 วินาทีจาก
  `casting_prompt` ก่อนเริ่มฉากแรก แล้วดึงเฟรมจากคลิปนั้นมาเป็นรูปอ้างอิง
  ทำให้เริ่มเรื่องจากข้อความล้วนแล้วตัวละครยังคงที่ได้
- **หยุดให้ตรวจหลัง cast เสมอ**: เมื่อ cast ครบทุกตัว ซีรีย์เป็น `PAUSED (casting)` ทุก `run_mode`
  เพราะทุกฉาก `ref` ต่อจากนี้สร้างบนหน้านี้ และ retry จับไม่ได้ (งานสำเร็จแต่หน้าไม่ใช่)
  Claude ดูรูปด้วย `series_review` แล้ว `resume` หรือ cast ใหม่
- **Cast ใหม่ / เปลี่ยนรูป**: เรียก `series_add_character` ซ้ำด้วยชื่อเดิม = แทนที่รูปอ้างอิงทั้งชุด
  (ให้ `casting_prompt` ใหม่โดยไม่ให้รูป = cast ใหม่) ฉากที่ `DONE` ไปแล้ว**ไม่ถูกรีเซ็ต**
  ถ้าต้องการให้ใช้หน้าใหม่ ต้องสั่ง regenerate ฉากนั้นเอง

**Episode**: `number` (1..n), `title`, `synopsis`, `caption`, `hashtags[]`, `status`
(`PENDING`/`RUNNING`/`DONE`), `scenes[]` (1–20), `final_video_path`, `thumbnail_path`, `duration`

**Scene**

| field | ค่า |
|---|---|
| `index` | 1..n ในตอน |
| `prompt` | Claude เขียนเต็ม ระบบไม่แต่ง prompt ให้ |
| `beat` | บันทึกสั้น ๆ ว่าฉากนี้เล่าอะไร (ไม่ส่งเข้าโมเดล) |
| `mode` | `text` / `ref` / `chain` (ดู 5.3) |
| `characters[]` | ชื่อตัวละคร ใช้กับ `ref` |
| `duration_seconds` | 5 / 8 / 10 / 12 / 15 |
| `seed` | `-1` = สุ่ม |
| `status` | `PENDING` / `QUEUED` / `RUNNING` / `DONE` / `FAILED` |
| `job_id`, `attempts`, `progress`, `error` | สถานะการรัน |
| `video_path`, `thumbnail_path`, `last_frame_path`, `started_at`, `finished_at` | ผลลัพธ์ |

### 5.3 โหมดความต่อเนื่องของฉาก

| mode | ชนิดงาน | ใช้เมื่อ | input |
|---|---|---|---|
| `text` | T2V | ฉากเปิด ฉากวิว ตัดฉากใหม่ที่ไม่มีตัวละครหลัก | prompt อย่างเดียว |
| `ref` | REF2VA | ตัดฉากใหม่ที่ต้องล็อกหน้าตัวละคร / กลับมา "ยึดตัวตน" หลัง chain 2–3 ฉาก | รูปอ้างอิงของตัวละครใน `characters` เรียงตามลำดับ (รวมไม่เกิน 9 รูป) |
| `chain` | FL2VA | ต่อการเคลื่อนไหวจากฉากก่อนแบบไม่ตัด | first frame = last frame ของฉากก่อนหน้า |

กติกา:

- `chain` ของฉากแรกในตอน = ต่อจากฉากสุดท้ายของตอนก่อนหน้า ฉากแรกของตอนที่ 1 ห้ามเป็น `chain`
- `ref` ต้องมี `characters` อย่างน้อย 1 และตัวละครนั้นต้องมีรูปหรือ `casting_prompt`
- ตรวจกติกาเหล่านี้ตอนเขียนตอน/ตอนสั่ง start แล้วตอบ error ที่อ่านแล้วแก้ได้ทันที
- last frame ใช้ไฟล์ `outputs/frames/{job_id}_last.jpg` ที่ `h3_service` สร้างให้อยู่แล้ว
  ถ้าไม่มีให้ดึงใหม่ด้วย `media_processor.extract_frame`

### 5.4 ตัวรัน (runner)

thread เดียว เริ่ม/หยุดใน lifespan คู่กับ queue worker วนทุก ~1 วินาที สำหรับทุกซีรีย์ที่ `RUNNING`:

1. **Casting** — ถ้ามีตัวละครที่ต้อง cast ให้ทำให้เสร็จก่อน ยังไม่เริ่มฉาก
2. หาตอนแรกที่ยังไม่ `DONE` ถ้าไม่มี: `story_complete` → ซีรีย์ `DONE`, ไม่งั้นว่างรอ
3. หาฉากแรกที่ยังไม่ `DONE` ในตอนนั้น
   - **ไม่มี `job_id`** → เตรียม input ตาม mode → `queue_service.create_job` → `QUEUED`
   - **มี `job_id`** → ดูงานในคิว
     - `PENDING`/`RUNNING` → คัดลอก progress
     - `DONE` → บันทึกผล ฉาก `DONE`
     - `FAILED` → `attempts += 1` ถ้ายังไม่ถึง `max_attempts` ส่งใหม่ ไม่งั้นฉาก `FAILED`
       และซีรีย์ `PAUSED (error)`
     - `CANCELLED` ขณะตัวรันยังไม่ถูกสั่งหยุด (มีคนกดยกเลิกในหน้าคิว) → ซีรีย์ `PAUSED (user)` ไม่ retry
     - **หาไม่เจอในคิว** → ถ้ามีไฟล์ `outputs/videos/{job_id}.*` ถือว่า `DONE`
       (มีคนกด "ล้างงานที่เสร็จ"); ถ้าไม่มีไฟล์ ดูว่างานนี้ส่งโดย process ปัจจุบันหรือไม่
       (ตัวรันจำ job id ที่ส่งเองไว้ใน RAM):
       ส่งโดย process นี้ = มีคนกดลบงานออกจากคิว → `PAUSED (user)`;
       ไม่ใช่ = backend รีสตาร์ท → ส่งใหม่โดยไม่นับ attempt
4. ทุกฉากของตอน `DONE` → ตรวจว่าไฟล์วิดีโอของทุกฉากยังอยู่ (ถ้าหาย เช่นถูกลบจากหน้า History
   ให้รีเซ็ตฉากนั้นตามกติกา 5.5 แล้ว gen ใหม่) → รวมคลิปด้วย `media_processor.concat_videos` (ตอนที่มีฉากเดียวใช้คลิปนั้นเป็นไฟล์ตอนเลย)
   → สร้าง thumbnail + อ่าน duration → ตอน `DONE` → เขียน `manifest.json`
   → ถ้า `run_mode == "review"` ซีรีย์ `PAUSED (review)` รอ resume

หลักการ:

- หนึ่งซีรีย์มีงานค้างในคิวได้ทีละ 1 งาน (ฉากถัดไปต้องรอ last frame อยู่แล้ว)
  หลายซีรีย์รันพร้อมกันได้ คิว FIFO เดิมเป็นตัวจัดลำดับ
- ทุกการเปลี่ยนสถานะบันทึกลงดิสก์ทันที การแก้ข้อมูลจาก MCP/REST กับตัวรันใช้ lock เดียวกัน
  งานที่ใช้เวลานาน (concat) ทำนอก lock
- **ลำดับตอนปิด**: หยุดตัวรันให้เสร็จ**ก่อน**หยุด queue worker เพื่อไม่ให้ตัวรันเห็น `CANCELLED`
  ที่คิวตั้งตอนปิด แล้วบันทึกผิดเป็น `PAUSED (user)`
- **รีสตาร์ท backend**: ซีรีย์ที่ `RUNNING` เดินต่อเองอัตโนมัติ (ตัดสินใจโดยผู้ออกแบบ:
  ผู้ใช้สั่งรันไว้แล้วและไม่ได้สั่งหยุด) ถ้า ComfyUI ยังไม่พร้อม งานจะล้มเหลวจนครบ attempt
  แล้วหยุดที่ `PAUSED (error)` ตามปกติ
- เก็บเวลาเริ่ม/จบของแต่ละฉาก เพื่อรายงานเวลาเฉลี่ยต่อฉากและเวลาที่เหลือโดยประมาณ

### 5.5 การแก้ไขและ gen ใหม่

- แก้ฉากที่ยัง `PENDING` / `FAILED` → แก้ข้อมูลเฉย ๆ
- สั่ง regenerate ฉากที่ `DONE` → รีเซ็ตฉากนั้น **และฉาก `chain` ที่ต่อเนื่องถัดไปทั้งหมด**
  (ข้ามขอบตอนได้ จนกว่าจะเจอฉากที่ไม่ใช่ `chain`) เพราะ first frame ของฉากเหล่านั้นเปลี่ยน
  ตอนที่ถูกกระทบกลับเป็นยังไม่เสร็จและจะถูกรวมใหม่ ไฟล์เก่าไม่ถูกลบ
- แก้/regenerate ฉากที่ `QUEUED` / `RUNNING` → ยกเลิกงานในคิวก่อน แล้วรีเซ็ต
- เขียนทับทั้งตอนได้เฉพาะตอนที่ยังไม่มีฉากใดเริ่มรัน
- ผลต่อสถานะซีรีย์เมื่อแก้/regenerate/เพิ่มตอน:
  - `RUNNING` → เดินต่อเอง
  - `PAUSED` → ยัง `PAUSED` ต้องสั่ง `resume` เอง (ถ้า resume จาก `error` ให้ล้าง attempts ของฉากที่พัง)
  - `DONE` → เปิดกลับเป็น `RUNNING` ทันที เพราะการสั่ง regenerate คือคำสั่งให้ใช้ GPU อยู่แล้ว
    (`story_complete` คงเดิม พอทำเสร็จจะกลับเป็น `DONE` เอง)
  - `CANCELLED` → ปฏิเสธ พร้อมข้อความบอกว่าซีรีย์ถูกยกเลิกแล้ว
  - `DRAFT` → แก้ได้อิสระ

### 5.6 MCP tools

server ชื่อ `h3-studio` ทุก tool คืนข้อความกระชับ (ประหยัด context) ชื่อ tool:

| tool | ทำอะไร |
|---|---|
| `studio_status` | backend/ComfyUI พร้อมไหม, VRAM, โหมด Local/RunPod, จำนวนงานในคิว, ค่าที่อนุญาต (duration / aspect / megapixels), รายการซีรีย์ย่อ |
| `series_guide` | คู่มือสำหรับ Claude: โครงสร้างซีรีย์แนวตั้ง, วิธีเลือก mode, ข้อจำกัดโมเดล, แนวเขียน prompt (ดู 5.7) |
| `series_create` | สร้างซีรีย์ (title, logline, style_notes, aspect_ratio, megapixels, low_vram, run_mode) |
| `series_add_character` | เพิ่ม/แก้ตัวละคร: name, description, `image_paths[]` (path ไฟล์รูปบนเครื่อง backend หรือ path ใต้ `outputs/`) และ/หรือ `casting_prompt` |
| `series_write_episode` | เพิ่มตอนใหม่ หรือเขียนทับตอนที่ยังไม่เริ่ม: title, synopsis, caption, hashtags, scenes[] |
| `series_update_scene` | แก้ฉาก (prompt / mode / duration / characters / seed) และ `regenerate` |
| `series_control` | `start` / `pause` / `resume` / `finish` (ประกาศ story_complete) / `cancel` |
| `series_status` | ความคืบหน้ารายตอน/ฉาก, ฉากที่กำลังรัน + %, error, เวลาที่เหลือโดยประมาณ |
| `series_wait` | รอจนมีเหตุการณ์ถัดไป (ฉากเสร็จ/พัง, ตอนเสร็จ, หยุด, จบ) หรือ timeout แล้วคืนสถานะ |
| `series_review` | คืน**รูปภาพ**ให้ Claude ดู: ระบุฉาก → เฟรมกระจายทั่วคลิป (ค่าเริ่มต้น 4 รูป ย่อขนาดแล้ว) + prompt; ระบุแค่ตอน → last frame ของทุกฉากในตอน; ระบุตัวละคร → รูปอ้างอิงปัจจุบันของตัวละครนั้น |
| `series_export` | คัดลอกไฟล์ตอนที่เสร็จไป `outputs/series/<id>/export/` ตั้งชื่อ `EP01 - <ชื่อตอน>.mp4` + ปก + `manifest.json` |

MCP prompt 1 ตัว: `new_series(idea)` — แสดงใน Claude Code เป็น slash command พา Claude ทำตามลำดับ:
อ่าน guide → วางโครงเรื่อง → สร้างซีรีย์ + ตัวละคร → เขียนตอน → start → wait/review วนจนจบ → export

**ความปลอดภัย**: endpoint `/mcp` รับเฉพาะ client จาก loopback (`127.0.0.1` / `::1`) เป็นค่าเริ่มต้น
เพราะ `series_add_character` อ่านไฟล์ตาม path บนเครื่องได้ และ backend เปิดให้ทั้ง LAN โดยไม่มี auth
มีคีย์ `mcp_allow_lan` ใน `backend/config.json` (ค่าเริ่มต้น `false`) สำหรับคนที่ตั้งใจเปิด
`image_paths` รับเฉพาะนามสกุลรูปใน `allowed_image_extensions` และไม่เกิน `upload_max_file_size_mb`
`series_export` เขียนได้เฉพาะใต้ `outputs/series/<id>/export/`

### 5.7 เนื้อหาของ `series_guide`

ผู้สร้างเรียบเรียงข้อความเอง โดยต้องครอบคลุม:

- ซีรีย์แนวตั้ง: ตอนละ 60–120 วินาที (6–12 ฉาก), 3 วินาทีแรกต้องมี hook, จบตอนด้วย cliffhanger,
  จัดองค์ประกอบให้ตัวละครอยู่กลางเฟรมแนวตั้ง
- เลือก mode: เปิดเรื่อง/วิวใช้ `text`, ฉากที่มีตัวละครหลักเริ่มด้วย `ref`, ต่อการเคลื่อนไหวใช้ `chain`
  และ**กลับไป `ref` ทุก 2–3 ฉาก**เพื่อกันตัวละครเพี้ยนสะสม
- prompt ของ `chain` ขึ้นต้นด้วย `continuing the same motion, ` และคงตัวละคร/ชุด/แสง/กล้องเดิม
  (ตาม template "ต่อฉาก" ใน `prompt_enhance_service.py`)
- รูปแบบ prompt 3 ช่อง (`integrated_multimodal_description` / `overall_soundscape` /
  `non_diegetic_music`) ตาม template `three_field` ในไฟล์เดียวกัน — โมเดลสร้างเสียงมาพร้อมภาพ
- ใน `ref` อ้างรูปด้วยแท็ก `<Picture N>` ได้ โดย N เรียงตามลำดับรูปของตัวละครใน `characters`
- บรรยายตัวละครซ้ำแบบเดิมทุกฉาก (รูปร่าง ชุด ทรงผม) อย่าพึ่งชื่อ
- ข้อจำกัด: duration ที่ใช้ได้, megapixels กับ VRAM (ตาราง README 1.1), Claude ฟังเสียงไม่ได้
- ขั้นตอนตรวจงาน: review ฉากที่เสร็จ ถ้าตัวละครเพี้ยนหรือภาพพังให้แก้ prompt แล้ว regenerate

### 5.8 REST + หน้าเว็บ

REST (prefix `/api/series`) เท่าที่หน้าเว็บใช้: รายการซีรีย์, รายละเอียดซีรีย์,
สั่ง `pause` / `resume` / `cancel` การเขียน/แก้ซีรีย์ทำผ่าน MCP เท่านั้นในรอบนี้

หน้า `/series` (เมนู "ซีรีย์" ใน sidebar) ใช้ component และสไตล์เดิมของโปรเจค:

```
┌ ซีรีย์ ─────────────────────────────────────────────┐
│ ▸ รักข้ามเวลา        RUNNING   ตอน 2/8 · ฉาก 5/9   │
│   เหลือประมาณ 1 ชม. 20 นาที       [หยุดชั่วคราว]   │
│ ┌ EP01 เจอกันครั้งแรก ─ DONE ─ 1:12 ──────────────┐ │
│ │ [▶ วิดีโอ 9:16]  caption… [คัดลอก] [ดาวน์โหลด]  │ │
│ │ ฉาก ●●●●●●●●                                    │ │
│ └─────────────────────────────────────────────────┘ │
│ ┌ EP02 ความลับ ─ RUNNING ───────────────────────────┐ │
│ │ ฉาก ●●●●◐○○○○   ฉาก 5: 43%                      │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

รีเฟรชอัตโนมัติทุก 5 วินาที วิดีโอ/thumbnail ใช้ `getMediaUrl` เดิม
(ไฟล์ตอนที่รวมแล้วอยู่ใน `outputs/videos/` จึงเสิร์ฟผ่าน `/api/media` เดิมได้)

**กดจุดฉากเพื่อเล่นคลิปของฉากนั้นได้** พร้อมแสดง prompt และ error ของฉาก
— คนต้องเป็นผู้ตรวจเสียงและ lip-sync รายฉาก และหน้า `/series` ต้องเป็นที่เดียวที่ดูซีรีย์ได้ครบ
โดยไม่พึ่ง History

**ความสัมพันธ์กับ History/Media (ไม่แก้ของเดิม)**: คลิปรายฉาก คลิป casting และงานที่ล้มเหลว
จะเข้า History/Media ตามกลไก `QueueHistorySync` เดิม ซึ่งทำงานเฉพาะตอนมีแท็บเว็บเปิดอยู่
รันข้ามคืนโดยไม่เปิดเว็บแล้วรีสตาร์ท backend = คลิปรายฉากไม่เข้า History (ยังอยู่ครบในหน้า `/series`)
ไฟล์ตอนที่รวมแล้วไม่ผ่านคิว จึงไม่เข้า History/Media เลย — ดูและดาวน์โหลดได้ที่หน้า `/series`
ถ้าผู้ใช้ลบคลิปรายฉากจาก History ตัวรันจะ gen ฉากนั้นใหม่เมื่อถึงเวลารวมตอน (5.4 ข้อ 4)

### 5.9 การทดสอบ

- เพิ่ม pytest (dev dependency แยกไฟล์ ไม่ปนกับ `requirements.txt`)
- unit test ของตัวรันด้วยคิวปลอมและฟังก์ชัน media ปลอม (ไม่ใช้ GPU): การเตรียม input ของแต่ละ mode,
  chain ข้ามตอน, retry แล้ว pause, งานหายจากคิวแล้วกู้จากไฟล์, regenerate แล้วรีเซ็ตฉาก chain ถัดไป,
  โหมด review, รวมตอน, โหลดสถานะจากดิสก์หลังรีสตาร์ท, auto-casting แล้วหยุดให้ตรวจ, cast ใหม่,
  validation, งานถูกลบจากคิวแล้ว pause, `CANCELLED` ตอนปิด backend ไม่ทำให้ซีรีย์ pause,
  regenerate ตอนซีรีย์ `DONE` / `PAUSED` / `CANCELLED`, ไฟล์ฉากหายตอนรวมตอน
- smoke test ของ MCP: client ต่อ `/mcp` ได้, เห็น tool ครบ, เรียก `studio_status` ได้,
  client ที่ไม่ใช่ loopback ถูกปฏิเสธ
- ทดสอบจริงกับ ComfyUI (ต้องให้เจ้าของเครื่องเปิด ComfyUI): ซีรีย์เล็กสุด 1 ตอน 2 ฉาก × 5 วินาที
  ที่ 0.1 MP ให้ครบวงจร text → chain → รวมตอน → export
- `npm run build` และ `npm run lint` ผ่าน

## 6. สิ่งที่ผู้ออกแบบตัดสินใจเอง (เจ้าของโปรเจคยังไม่ได้ยืนยัน)

1. เลือกแนวทาง A และเก็บสถานะเป็นไฟล์ JSON
2. MCP เป็น Streamable HTTP ฝังใน FastAPI ไม่ใช่ stdio
3. `/mcp` รับเฉพาะ loopback เป็นค่าเริ่มต้น
4. ค่าเริ่มต้น: 9:16, 0.35 MP, `run_mode = autopilot`, retry 2 ครั้งต่อฉาก
5. รีสตาร์ท backend แล้วซีรีย์ที่ `RUNNING` เดินต่อเอง
6. รวมหน้าเว็บ `/series` (ดูอย่างเดียว) ไว้ในรอบนี้
7. รวม auto-casting, `series_review` (Claude ดูภาพ), `series_export` + manifest ไว้ในรอบนี้
8. ไม่ผูกกับ Projects/History ของ Prisma ในรอบนี้ — ไฟล์ตอนที่รวมแล้วดูได้ที่หน้า `/series` เท่านั้น
9. หลัง auto-casting ซีรีย์หยุดให้ตรวจหน้าตัวละครเสมอ แม้อยู่ในโหมด autopilot
10. เปลี่ยนรูปตัวละครทีหลังไม่รีเซ็ตฉากที่เสร็จแล้ว
11. regenerate ฉากตอนซีรีย์ `DONE` = เปิดกลับมารันทันที; ตอน `PAUSED` = รอสั่ง resume;
    `CANCELLED` เป็นสถานะสุดท้าย แก้ไม่ได้
12. ลบงานของซีรีย์ออกจากคิวในหน้าเว็บ = ซีรีย์หยุดชั่วคราว (ไม่ส่งงานซ้ำเอง)
13. หน้า `/series` เล่นคลิปรายฉากได้
14. ไม่มี negative prompt ในซีรีย์ (pipeline ปัจจุบันไม่ได้ใช้ค่านี้)

## 7. สิ่งที่ปล่อยให้ผู้สร้างตัดสินใจ

- เวอร์ชันของแพ็กเกจ `mcp` และวิธี mount เข้า FastAPI: ตอนนี้ PyPI ล่าสุดคือ 2.x ให้ยึด API จาก
  แพ็กเกจที่ติดตั้งจริง ไม่ยึดจากความจำ แล้ว pin major version ที่ทดสอบผ่าน
  (ระวังเรื่อง lifespan ของ session manager, redirect ของ trailing slash, และการตรวจ Host header)
- ค่า timeout เริ่มต้น/สูงสุดของ `series_wait` — ต้องไม่เกิน timeout ของ MCP tool call ใน Claude Code
  ให้ตรวจค่าจริงก่อนกำหนด
- การแบ่งไฟล์ภายใน (store / runner / models), ชื่อ field ปลีกย่อย, รูปแบบข้อความที่ tool คืน
- เฟรมไหนของคลิป casting ที่ใช้เป็นรูปอ้างอิง (แนะนำ last −3 ตามธรรมเนียมของหน้าเฟรม)
- วิธีย่อขนาดรูปใน `series_review`
- จะ reuse `push_image_to_comfyui` เดิม หรือแยก helper ใหม่
- รายละเอียด UI ของหน้า `/series` ภายใต้โครงในข้อ 5.8

## 8. ไอเดียรอบถัดไป (ไม่ทำตอนนี้)

- ซับไตเติลไทยฝังในวิดีโอจากบทพูดรายฉาก
- upscale ไฟล์ตอนอัตโนมัติก่อน export
- คลิป "ความเดิมตอนที่แล้ว" อัตโนมัติ
- ตั้งเวลารันเฉพาะช่วงกลางคืน
- ผูกซีรีย์กับ Projects/History และย้ายเข้า DB
- API สำหรับแอพสมาชิกอ่าน manifest
