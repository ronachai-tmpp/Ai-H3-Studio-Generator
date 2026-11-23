# 🎬 Ai-H3-Studio-Generator

> สตูดิโอสร้างวิดีโอ AI บนเครื่องคุณเอง — รัน MiniMax H3 ผ่าน ComfyUI พร้อมคิวงาน, คลังมีเดีย, ต่อคลิปต่อเนื่อง, รวมคลิป และผู้ช่วยเขียน prompt ด้วย Gemma VLM

ใช้งานผ่านเว็บเบราว์เซอร์ รองรับทั้ง **เครื่องเดียว**, **หลายเครื่องในวง LAN**, **มือถือ/แท็บเล็ต** และสลับไปใช้ **GPU บน RunPod** ได้จากหน้า Settings


---

## สารบัญ

- [1. System Requirements](#1-system-requirements)
- [2. ขั้นตอนการติดตั้ง (Windows)](#2-ขั้นตอนการติดตั้ง-windows)
- [3. การรันโปรแกรม](#3-การรันโปรแกรม)
- [4. Feature ที่มีตอนนี้](#4-feature-ที่มีตอนนี้)
- [โครงสร้างโปรเจค](#โครงสร้างโปรเจค)
- [แก้ปัญหาเบื้องต้น](#แก้ปัญหาเบื้องต้น)
- [ข้อจำกัดที่ทราบ](#ข้อจำกัดที่ทราบ)
- [แผนพัฒนาต่อ](#แผนพัฒนาต่อ)

---

## 1. System Requirements

### 1.1 ฮาร์ดแวร์

| รายการ | ต่ำสุด | แนะนำ | หมายเหตุ |
|---|---|---|---|
| **GPU** | NVIDIA 8 GB VRAM | **NVIDIA 12 GB ขึ้นไป** (เช่น RTX 4070 Super / 3060 12G / 4070 Ti Super) | 8 GB ใช้ได้เฉพาะ 0.1–0.35 MP |
| **VRAM (Cloud)** | — | 24 GB ขึ้นไป (RunPod A5000 / 4090 / L40S) | เรนเดอร์ 15 MP·15s ได้สบาย |
| **CPU** | 4 cores | 8 cores ขึ้นไป (เช่น i5-14400F) | ใช้ตอน encode วิดีโอ / ffmpeg |
| **RAM** | 16 GB | **32 GB** | text encoder ขนาดใหญ่มีการ offload ลง RAM |
| **ดิสก์** | 60 GB ว่าง | **100 GB+ SSD/NVMe** | โมเดลรวมหลายสิบ GB + ผลลัพธ์โตขึ้นเรื่อย ๆ |
| **ระบบ** | Windows 10/11 64-bit | Windows 11 | ทดสอบบน Windows เป็นหลัก |

**แนวทางเลือกความละเอียดตาม VRAM (12 GB)**

| Resolution | 5 วินาที | 10 วินาที | 15 วินาที |
|---|---|---|---|
| 0.25 MP | ✅ | ✅ | ✅ |
| 0.35 MP | ✅ | ✅ | ✅ |
| 0.5 MP | ✅ | ✅ | ⚠️ เสี่ยง OOM |
| 0.75 MP | ✅ | ⚠️ | ❌ |
| 1.0 MP | ⚠️ | ❌ | ❌ |

> ถ้าเจอ CUDA out of memory → **ลด MP ก่อนลดความยาว** (MP มีผลต่อ VRAM มากกว่า)

### 1.2 ซอฟต์แวร์ที่ต้องมี

| ซอฟต์แวร์ | เวอร์ชัน | ใช้ทำอะไร | ดาวน์โหลด |
|---|---|---|---|
| **Node.js** | 20 LTS ขึ้นไป (แนะนำ 22 LTS) | รันหน้าเว็บ Next.js | https://nodejs.org |
| **Python** | **3.11** | รัน FastAPI backend | https://www.python.org/downloads/release/python-3119/ |
| **Git** | ล่าสุด | clone / อัปเดตโค้ด | https://git-scm.com |
| **FFmpeg + FFprobe** | 6.x ขึ้นไป | สร้าง thumbnail, อ่านความยาว, ดึงเฟรม, รวมคลิป | https://www.gyan.dev/ffmpeg/builds/ |
| **ComfyUI** | **0.45 ขึ้นไป** | เครื่องสร้างวิดีโอ + VLM | https://github.com/comfyanonymous/ComfyUI |
| **NVIDIA Driver** | ล่าสุด | CUDA | https://nvidia.com/drivers |

> ⚠️ ตอนติดตั้ง Python **ต้องติ๊ก `Add python.exe to PATH`**
> ⚠️ ComfyUI ต้องเป็น 0.45+ เพราะฟีเจอร์สร้าง prompt ใช้ node `TextGenerateV2` และ `PreviewAny`

### 1.3 โมเดลที่ต้องมีใน ComfyUI

| ไฟล์ | วางไว้ที่ | ใช้กับ |
|---|---|---|
|[minimax_h3_fl2va_pruned_int8_convrot.safetensors](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors) | `models/diffusion_models/` | T2V + FL2VA |
|[minimax_h3_ref2va_pruned_int8_convrot.safetensors](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors) | `models/diffusion_models/` | REF2VA |
|[qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors) | `models/text_encoders/` | CLIP ของ H3 |
|[minimax_h3_video_vae_int8_convrot.safetensors](https://huggingface.co/Kijai/MiniMax-H3-experimental/blob/main/minimax_h3_video_vae_int8_convrot.safetensors) | `models/vae/` | ถอดรหัสภาพ |
|[minimax_h3_audio_vae_fp32.safetensors](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/vae/minimax_h3_audio_vae_fp32.safetensors) | `models/vae/` | ถอดรหัสเสียง |
|[pika_h3_flex_fl2va_v1_bf16.safetensors](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/loras/pika_h3_flex_fl2va_v1_bf16.safetensors) | `models/loras/` | LoRA เร่งความเร็ว (FL2VA) |
|[pika_h3_flex_ref2va_v1_bf16.safetensors](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/loras/pika_h3_flex_ref2va_v1_bf16.safetensors)| `models/loras/` | LoRA เร่งความเร็ว (REF2VA) |
|[gemma4_e4b_it_fp8_scaled.safetensors](https://huggingface.co/Comfy-Org/gemma-4/blob/main/text_encoders/gemma4_e4b_it_fp8_scaled.safetensors) | `models/text_encoders/` | สร้าง prompt จากรูป (VLM) |
|[MiniMax-H3-FL2VA-Pruned-Q3_K_M.gguf](https://huggingface.co/Abiray/MiniMax-H3-Pruned-GGUF/blob/main/MiniMax-H3-FL2VA-Pruned-Q3_K_M.gguf) | `models/unet/` | T2V + FL2V (Low VRAM) |
|[MiniMax-H3-Ref2VA-Pruned-Q3_K_M.gguf](https://huggingface.co/Abiray/MiniMax-H3-Pruned-GGUF/blob/main/MiniMax-H3-Ref2VA-Pruned-Q3_K_M.gguf) | `models/unet/` | REF2V (Low VRAM) |
|[qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf](https://huggingface.co/realrebelai/MiniMax-H3_GGUFs/blob/main/qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf)| `models/text_encoders/` | CLIP (Low VRAM) |
|[relayvsr_x2_lightx2v_int8_convrot.safetensors](https://huggingface.co/Comfy-Org/RelayVSR/blob/main/diffusion_models/relayvsr_x2_lightx2v_int8_convrot.safetensors) | `models/diffusion_models/` | UpScale Model |
|[relayvsr_flash_vae_x2_fp32.safetensors](https://huggingface.co/Comfy-Org/RelayVSR/blob/main/vae/relayvsr_flash_vae_x2_fp32.safetensors) | `models/vae` | UpScale Model |

### 1.4 พอร์ตที่ใช้

| พอร์ต | บริการ | เปิดให้ LAN |
|---|---|---|
| `3000` | หน้าเว็บ (Next.js) | ✅ |
| `8000` | API (FastAPI) | ✅ |
| `8188` | ComfyUI | เฉพาะเครื่องที่รัน (หรือ RunPod) |

---

## 2. ขั้นตอนการติดตั้ง (Windows)

### ขั้นที่ 1 — ติดตั้งซอฟต์แวร์พื้นฐาน

ติดตั้ง Node.js, Python 3.11 (ติ๊ก Add to PATH), Git แล้วเปิด **Command Prompt** ใหม่เพื่อเช็ก:

```bat
node -v
python --version
git --version
```

ต้องขึ้นเวอร์ชันครบทั้ง 3 ตัว

### ขั้นที่ 2 — ติดตั้ง FFmpeg

1. ดาวน์โหลด `ffmpeg-release-full.7z` จาก https://www.gyan.dev/ffmpeg/builds/
2. แตกไปที่ `C:\ffmpeg`
3. เพิ่ม `C:\ffmpeg\bin` เข้า **PATH**
   - Start → ค้นหา "environment variables" → Environment Variables
   - ที่ `Path` → Edit → New → `C:\ffmpeg\bin`
4. เปิด CMD ใหม่ laluเช็ก:

```bat
ffmpeg -version
ffprobe -version
```

> ถ้าไม่อยากแก้ PATH → ตั้งค่า `ffmpeg_path` ใน `backend\config.json` แทนได้

### ขั้นที่ 3 — ติดตั้ง ComfyUI + โมเดล

1. ติดตั้ง ComfyUI (แนะนำแบบ portable สำหรับ Windows)
2. วางโมเดลทุกไฟล์ตามตารางในข้อ 1.3
3. ติดตั้ง custom nodes ที่ workflow ใช้ (ถ้ามี)
4. เปิด ComfyUI แล้วเช็กว่าเข้า `http://127.0.0.1:8188` ได้

### ขั้นที่ 4 — วางโปรเจคไว้ที่ path ที่ต้องการ

ตัวอย่างในเอกสารนี้ใช้:

```
D:\minimax-h3-studio
```

> หลีกเลี่ยง path ที่มีภาษาไทยหรือช่องว่าง จะลดปัญหาตอน build

### ขั้นที่ 5 — รันตัวติดตั้ง

ดับเบิลคลิก:

```
install.bat
```

สคริปต์จะทำตามลำดับ:

```
[1/4] npm install                 ติดตั้ง dependencies หน้าเว็บ
[2/4] prisma generate + db push   สร้างฐานข้อมูล SQLite
[3/4] npm run build               build หน้าเว็บโหมด production
[4/4] python venv + pip install   สร้าง venv + ติดตั้ง dependencies backend
```

ระหว่างทางจะสร้าง `backend\config.json` จาก `config.example.json` ให้อัตโนมัติ

### ขั้นที่ 6 — แก้ค่า config

เปิด `backend\config.json` แล้วแก้ path ให้ตรงกับเครื่องคุณ:

```json
{
  "comfyui_root": "D:\\ComfyUI_windows_portable\\ComfyUI",
  "comfyui_input_dir": "D:\\ComfyUI_windows_portable\\ComfyUI\\input",
  "ffmpeg_path": "C:\\ffmpeg\\bin\\ffmpeg.exe"
}
```

> ใช้ `\\` (backslash คู่) ใน JSON เสมอ
> คีย์อื่น ๆ ดูได้จาก `backend\config.example.json`
> `mcp_allow_lan` (ค่าเริ่มต้น `false`) — ตั้งเป็น `true` เพื่อให้เครื่องอื่นใน LAN เรียก MCP (`/mcp`) ได้ ดู [สร้างซีรีย์ด้วย Claude Code](#-สร้างซีรีย์ด้วย-claude-code-mcp)

### ขั้นที่ 7 — เปิด Firewall (ครั้งแรกเท่านั้น)

ตอนรันครั้งแรก Windows จะถาม_ALLOW_ → เลือก **Private networks** แล้วกด Allow ทั้ง **Node.js** และ **Python**

ถ้าเผลอกด Cancel ไป ให้เปิด CMD แบบ **Run as administrator** แล้วรัน:

```bat
netsh advfirewall firewall add rule name="H3 Studio Web" dir=in action=allow protocol=TCP localport=3000
netsh advfirewall firewall add rule name="H3 Studio API" dir=in action=allow protocol=TCP localport=8000
```

✅ ติดตั้งเสร็จแล้ว

---

## 3. การรันโปรแกรม

### 3.1 ลำดับการเปิด

```
1. เปิด ComfyUI            → http://127.0.0.1:8188  (ต้องเปิดค้างไว้)
2. ดับเบิลคลิก start.bat    → เปิด backend + frontend ให้อัตโนมัติ
3. เปิดเบราว์เซอร์          → http://localhost:3000
```

### 3.2 เลือกสคริปต์ให้เหมาะกับสถานการณ์

| สคริปต์ | ทำอะไร | ใช้เมื่อ | เวลาบูต |
|---|---|---|---|
| **`start.bat`** | build หน้าเว็บใหม่ทุกครั้ง แล้วรัน production | หลังแก้โค้ด / `git pull` / ไม่มั่นใจว่าโค้ดล่าสุด | ~1 นาที |
| **`start-fast.bat`** | ข้าม build ใช้ของเดิมที่ build ไว้ | เปิดใช้งานประจำวัน ไม่ได้แก้โค้ด | ~5 วินาที |

> **ขี้เกียจคิด ใช้ `start.bat` เสมอได้** — ปลอดภัยสุด แค่รอ build นานขึ้นหน่อย

ทั้งสองสคริปต์จะเปิด 2 หน้าต่างค้างไว้:

```
[H3 Backend]   ← log ของ API, คิวงาน, ComfyUI
[H3 Frontend]  ← log ของหน้าเว็บ
```

### 3.3 เข้าใช้งาน

| จากที่ไหน | URL |
|---|---|
| เครื่องที่รัน | `http://localhost:3000` |
| เครื่องอื่นใน LAN | `http://<IP เครื่องที่รัน>:3000` เช่น `http://10.1.1.5:3000` |
| มือถือ/แท็บเล็ต (Wi-Fi เดียวกัน) | `http://<IP เครื่องที่รัน>:3000` |
| API docs (Swagger) | `http://<IP>:8000/docs` |

`start.bat` จะพิมพ์ IP ของเครื่องให้ตอนรัน — ใช้ค่านั้นแจกทีมได้เลย

> **ไม่ต้อง设 env หรือ build ใหม่เมื่อ IP เปลี่ยน** — หน้าเว็บหา backend จาก hostname ที่เปิดใช้อัตโนมัติ

### 3.4 หยุดระบบ

ปิดหน้าต่าง `[H3 Backend]` และ `[H3 Frontend]`
(ComfyUI ปิดแยกต่างหาก — ถ้าปิดตอนมีงานรัน งานนั้นจะถูกยกเลิก)

### 3.5 อัปเดตโค้ด

```bat
git pull
start.bat
```

ถ้า `package.json` หรือ `requirements.txt` เปลี่ยน → รัน `install.bat` ก่อน

### 3.6 ใช้ GPU บน Cloud (RunPod)

1. เปิด pod ที่ลง ComfyUI + โมเดลครบแล้ว
2. เข้าหน้า **ตั้งค่า** → เลือก **RunPod**
3. ใส่ URL dạng `https://<pod-id>-8188.proxy.runpod.net` → Save
4. กดทดสอบการเชื่อมต่อ → เริ่มสร้างวิดีโอได้ทันที

ไฟล์วิดีโอ/thumbnail/เฟรม ยังถูกเก็บในเครื่องคุณเหมือนเดิม (backend เป็นคนดาวน์โหลดกลับมา)

---

## 4. Feature ที่มีตอนนี้

### 📊 แดชบอร์ด (หน้าแรก)

- การ์ดสถิติ: จำนวนวิดีโอ · โปรเจค · เฟรม · พื้นที่ดิสก์ที่ใช้จริง
- สถานะคิวสด: งาน RUNNING พร้อมแถบ progress % + งาน PENDING
- Timeline กิจกรรมล่าสุด 8 รายการ
- ปุ่มทางลัดไปหน้าสร้าง/คลัง/โปรเจค
- รีเฟรชอัตโนมัติทุก 5 วินาที

### 🎬 สร้างคลิปสั้น (Studio)

**3 โหมดสร้างวิดีโอ**

| โหมด | คืออะไร | ต้องใส่อะไร |
|---|---|---|
| **T2V** | ข้อความ → วิดีโอ | prompt อย่างเดียว |
| **REF2VA** | รูปอ้างอิงล็อกตัวตนตัวละคร → วิดีโอ | รูปอ้างอิง 1–2 รูป + prompt |
| **FL2VA** | ภาพตั้งต้น → วิดีโอ | First frame และ/หรือ Last frame |

**FL2VA รองรับ 3 ลักษณะงาน**

| First | Last | ผลลัพธ์ |
|:---:|:---:|---|
| ✅ | — | เริ่มคลิปจากภาพนี้ (ใช้ต่อคลิป) |
| — | ✅ | คลิปจบที่ภาพนี้พอดี |
| ✅ | ✅ | **Interpolation A→B** — สร้าง transition เนียนระหว่าง 2 ฉาก |

**ตัวเลือกที่ปรับได้**

- Resolution: 0.1 / 0.25 / 0.35 / 0.5 / 0.75 / 1.0 MP
- Aspect ratio: 16:9, 9:16, 1:1, 2:3, 3:2, 3:4, 4:3, 21:9
- **Duration: 5 / 8 / 10 / 12 / 15 วินาที**
- Steps, Seed (-1 = สุ่ม), Task adapter, LoRA
- Negative prompt (เฉพาะ REF2VA)

**Low VRAM Mode (GGUF)**
- รองรับ GPU VRAM 8-12 GB
- ใช้โมเดล quantized (Q3_K_M / Q4_K_M) ลด VRAM 40-50%
- 3 โหมด: T2V / FL2VA / REF2VA (Low VRAM)
- คุณภาพใกล้เคียง bf16 แต่ใช้ VRAM น้อยกว่ามาก

**อื่น ๆ**

- ลาก-วางรูปเพื่ออัปโหลด (Drag & Drop) หรือคลิกเลือก
- ปุ่ม ✨ **สร้าง prompt จากรูป** ด้วย Gemma VLM
- คิวงานแสดง progress % จริงจาก ComfyUI WebSocket
- **ยกเลิกงานแล้ว GPU หยุดจริง** (ส่ง `/interrupt` + ลบคิวใน ComfyUI)
- งานเสร็จ: เห็น thumbnail → กดเพื่อเล่นในกล่องเดิม · ดาวน์โหลด · เปิดแท็บใหม่
- บันทึกเข้าประวัติอัตโนมัติ

### 🎥 สร้างหนังสั้น (Short Film)

- **4 การ์ดฉาก** ในหน้าเดียว — แต่ละฉากตั้ง type / prompt / duration / รูป แยกกันได้
- Resolution + Aspect ร่วมทั้งเรื่อง หรือ override รายฉาก
- อัปโหลดรูปเองได้ทุกฉาก (ลาก-วางได้)
- ปุ่ม **"ดึง last frame จากฉากก่อนหน้า"** → ต่อฉากเนียนในคลิกเดียว
- ปุ่ม ✨ สร้าง prompt รายฉาก (แนบรูปของฉากนั้นให้ + เลือก template "ต่อฉาก" ให้อัตโนมัติเมื่อเป็น FL2VA)
- **จำร่างอัตโนมัติ** ลง localStorage — refresh แล้วไม่หาย
- ส่งทีละฉาก (ใครกดก่อนได้คิวก่อน) หรือ **ส่งทั้งหมดเรียง 1→4**
- ปุ่ม **รวมคลิปที่เสร็จแล้ว** เป็นไฟล์เดียว
- ปุ่มล้างทั้งหมดเพื่อเริ่มเรื่องใหม่

### 🤖 สร้างซีรีย์ด้วย Claude Code (MCP)

ให้ Claude Code วางเรื่อง เขียนตอน สั่งสร้างทีละฉาก ตรวจภาพ และส่งออกไฟล์ให้ทั้งซีรีย์ผ่าน MCP server ชื่อ `h3-studio` ที่ฝังอยู่ใน backend (endpoint `/mcp`) — ดูความคืบหน้าและกด พัก/เล่นต่อ/ยกเลิก ได้ที่หน้า `/series` ของเว็บ

1. **เปิด backend ก่อน** แล้วค่อยเปิด Claude Code (backend ต้องรันอยู่ที่พอร์ต 8000 ตลอดเวลาที่สร้างซีรีย์)
2. เปิด Claude Code ในโฟลเดอร์โปรเจคนี้ — server ถูกลงทะเบียนไว้แล้วในไฟล์ `.mcp.json` ที่รากของโปรเจค (กดอนุมัติ server เมื่อ Claude Code ถาม)
3. พิมพ์ `/mcp` ใน Claude Code เพื่อเช็กว่า `h3-studio` เชื่อมต่อแล้ว
4. เริ่มด้วย prompt `new_series` (พิมพ์ `/mcp__h3-studio__new_series <ไอเดียของคุณ>`) — Claude จะอ่านคู่มือ วางโครงเรื่องให้คุณอนุมัติก่อน แล้วสร้างซีรีย์ตามลำดับ
5. ไฟล์ทั้งหมดอยู่ใน `outputs/series/<id>/` (รูปตัวละคร `refs/`, ภาพรีวิว `review/`, ไฟล์ส่งออก `export/` พร้อม `manifest.json`)

> Claude ฟังเสียงไม่ได้ — บทพูดและปากตรงเสียง (lip-sync) ให้คุณเปิดดูเองที่หน้า `/series`

> **ความปลอดภัย:** `/mcp` รับเฉพาะการเชื่อมต่อจากเครื่องเดียวกัน (loopback) เป็นค่าเริ่มต้น เพราะ `series_add_character` อ่านไฟล์รูปตาม path บนเครื่อง backend ได้ และ backend ไม่มีระบบล็อกอิน ถ้าตั้งใจให้เครื่องอื่นใน LAN ใช้ ให้ตั้ง `"mcp_allow_lan": true` ใน `backend\config.json` แล้วรีสตาร์ท backend

| tool | ทำอะไร |
|---|---|
| `studio_status` | backend/ComfyUI พร้อมไหม, VRAM, โหมด Local/RunPod, จำนวนงานในคิว, ค่าที่อนุญาต (duration / aspect / megapixels), รายการซีรีย์ย่อ |
| `series_guide` | คู่มือสำหรับ Claude: โครงสร้างซีรีย์แนวตั้ง, วิธีเลือก mode, ข้อจำกัดโมเดล, แนวเขียน prompt |
| `series_create` | สร้างซีรีย์ (title, logline, style_notes, aspect_ratio, megapixels, low_vram, run_mode) |
| `series_add_character` | เพิ่ม/แก้ตัวละคร: name, description, `image_paths[]` (path ไฟล์รูปบนเครื่อง backend หรือ path ใต้ `outputs/`) และ/หรือ `casting_prompt` |
| `series_write_episode` | เพิ่มตอนใหม่ หรือเขียนทับตอนที่ยังไม่เริ่ม: title, synopsis, caption, hashtags, scenes[] |
| `series_update_scene` | แก้ฉาก (prompt / mode / duration / characters / seed) และ `regenerate` |
| `series_control` | `start` / `pause` / `resume` / `finish` (ประกาศว่าเรื่องจบ) / `cancel` |
| `series_status` | ความคืบหน้ารายตอน/ฉาก, ฉากที่กำลังรัน + %, error, เวลาที่เหลือโดยประมาณ |
| `series_wait` | รอจนมีเหตุการณ์ถัดไป (ฉากเสร็จ/พัง, ตอนเสร็จ, หยุด, จบ) หรือ timeout แล้วคืนสถานะ |
| `series_review` | คืน**รูปภาพ**ให้ Claude ดู: ระบุฉาก → เฟรมกระจายทั่วคลิป + prompt; ระบุแค่ตอน → last frame ของทุกฉากในตอน; ระบุตัวละคร → รูปอ้างอิงของตัวละครนั้น |
| `series_export` | คัดลอกไฟล์ตอนที่เสร็จไป `outputs/series/<id>/export/` ตั้งชื่อ `EP01 - <ชื่อตอน>.mp4` + ปก + `manifest.json` |

### ✨ ผู้ช่วยเขียน Prompt (Gemma VLM)

ทำงานเป็น popup ไม่รกหน้า — ใช้ได้ทั้งหน้าสร้างคลิปสั้นและรายฉากในสร้างหนังสั้น

- ใส่ได้ **สูงสุด 6 รูป** — Gemma วิเคราะห์ทั้งหมดพร้อมกัน
- หรือเลือก **วิดีโอที่สร้างไว้** → ระบบสุ่มเฟรม 6 ภาพกระจายทั่วคลิปให้เอง
- **4 template สำเร็จรูป**
  - Cinematic H3 FL2V
  - 3-field cinematic (description / soundscape / music)
  - บรรยายภาพละเอียด
  - ต่อฉาก (continuing motion)
- ช่อง **Story** — พิมพ์แค่สิ่งที่ให้เกิดในฉาก ไม่ต้องเขียนคำสั่งควบคุม AI ซ้ำ
- Advanced: `max_length`, `temperature`, `seed`
- แก้ผลลัพธ์ก่อนกดใช้ได้ · คัดลอก · ใช้ prompt นี้เติมลงฟอร์มทันที

### 🖼 คลังมีเดีย (Media)

- Grid วิดีโอที่สร้างสำเร็จทั้งหมด พร้อม thumbnail
- กดรูปเพื่อเล่นในกล่องขนาดเดิม (ไม่กระโดด layout)
- **Copy Prompt** — มี fallback ใช้ได้แม้เปิดผ่าน LAN IP (ไม่ใช่ HTTPS)
- **ดึงเฟรม** — ดึง last frame ส่งเข้า ComfyUI input พร้อมใช้ต่อ
- ดาวน์โหลด · เปิดแท็บใหม่
- **ลบถาวร** ยืนยัน 2 จังหวะ (ลบไฟล์วิดีโอ + thumbnail + ประวัติ)
- **รวมคลิป (Merge)** — เลือกหลายคลิป → จัดลำดับ ↑↓ ในกล่องยืนยัน → ตั้งชื่อ → รวมด้วย ffmpeg
  - สเปคตรงกัน → ไม่ encode ใหม่ (เร็วมาก, คุณภาพเดิม)
  - สเปคต่างกัน → normalize ขนาด/fps/เสียง ให้เท่ากันอัตโนมัติ
- **เลือกหลายรายการ → เพิ่มเข้าโปรเจค** ผ่าน dropdown (+ สร้างโปรเจคใหม่ในที่เดียว, + นำออกจากโปรเจค)
- ค้นหา prompt · กรองประเภท · รีเฟรชอัตโนมัติทุก 10 วินาที

### 🎞 คลังเฟรม (Frames)

- ทุกเฟรมที่ดึงไว้ (อัตโนมัติหลัง gen + กดดึงเอง) อยู่ในหน้าเดียว
- Badge บอก `LAST` / `LAST −3` / `FIRST` + ขนาดไฟล์ + คลิปต้นทาง
- **Lightbox ซูม Fit / 100% / 200%** — ตรวจความคมก่อนนำไปต่อคลิป (เลื่อน ← → เปลี่ยนเฟรม, Esc ปิด)
- ดาวน์โหลด · เปิดแท็บใหม่ · **คัดลอกชื่อไฟล์** (เอาไปใส่ node LoadImage)
- **ส่งเข้า ComfyUI ซ้ำ** · **ต่อคลิปจากเฟรมนี้** (เด้งไปฟอร์มพร้อมรูปแนบ)
- ลบทีละใบ (ยืนยัน 2 จังหวะ) หรือเลือกหลายใบแล้วลบทีเดียว
- ค้นหา · กรองตำแหน่ง · เรียงใหม่/เก่า/ไฟล์ใหญ่

### 📁 โปรเจค (Projects)

- สร้าง / แก้ชื่อ-คำอธิบาย / ลบโปรเจค (ยืนยันด้วย modal)
- การ์ดแสดงจำนวนคลิป + วันที่
- ปุ่ม **+ เพิ่มวิดีโอ** → ไปคลังมีเดียในโหมดเลือก พร้อม banner บอกโปรเจคเป้าหมาย
- **หน้ารายละเอียดโปรเจค**: grid วิดีโอ thumbnail + กดเล่น + ดาวน์โหลด
- **นำคลิปออกจากโปรเจคทำได้ที่นี่ที่เดียว** (คลิปยังอยู่ในประวัติ ไม่ถูกลบไฟล์)
- ลบโปรเจค → คลิปถูกปลดออก แต่ไฟล์และประวัติยังอยู่ครบ

### 🕘 ประวัติ (History)

- เก็บทุกงานที่เสร็จ/ยกเลิก/ล้มเหลว ลง SQLite ถาวร
- ย้ายเข้าโปรเจค · ลบรายการ
- **ซิงก์อัตโนมัติจากทุกหน้า** — ไม่ต้องเปิดหน้าใดค้างไว้
- **ซิงก์ย้อนหลัง** — ปิดเว็บตอนงานรัน พอเปิดใหม่จะบันทึกให้เอง

### ⚙️ ตั้งค่า (Settings)

- สลับ **Local ↔ RunPod** พร้อมทดสอบการเชื่อมต่อ
- **5 ธีม** + ปรับขนาดตัวอักษร
- ค่าการเชื่อมต่อจำไว้ในเครื่อง

### ⌨️ Keyboard Shortcuts

| ปุ่ม | ทำอะไร | ที่ไหน |
|---|---|---|
| `Ctrl/Cmd + Enter` | ส่งงานเข้าคิว | สร้างคลิปสั้น |
| `/` | โฟกัสช่องค้นหา | มีเดีย / เฟรม |
| `Ctrl/Cmd + A` | เลือกทั้งหมดที่แสดง | โหมดเลือกหลายรายการ |
| `Delete` / `Backspace` | ลบรายการที่เลือก | คลังเฟรม |
| `Esc` | ปิด popup / ออกจากโหมดเลือก | ทุกหน้า |
| `←` `→` | เฟรมก่อนหน้า / ถัดไป | Lightbox |

### 📱 การใช้งานข้ามเครื่อง

- Responsive เต็มรูปแบบ — มือถือมี sidebar แบบ drawer
- ใช้ได้หลายคนในวง LAN พร้อมกัน คิวกลางตัวเดียว
- ไม่ต้องแก้ env / build ใหม่เมื่อ IP เปลี่ยน

### 🔧 ความสามารถฝั่ง Backend

- คิว FIFO ประมวลผลทีละงาน (thread worker) — ปลอดภัยต่อ VRAM
- Progress จริงจาก ComfyUI WebSocket + fallback เป็น history polling เมื่อ WS หลุด
- แยก progress ของงาน upscale ออกจาก sampling (ไม่กระโดด 99% ค้าง)
- ดึง **last frame อัตโนมัติ** ทุกครั้งที่ gen เสร็จ
- สร้าง thumbnail + อ่านความยาววิดีโอด้วย ffprobe
- อัปโหลดรูปเข้า ComfyUI ได้ทั้ง local (copy) และ remote (multipart, รองรับทั้ง `/upload/image` และ `/api/upload/image`)
- เสิร์ฟไฟล์วิดีโอ/thumbnail/เฟรมผ่าน API เดียว
- สถิติพื้นที่จัดเก็บจริงจากดิสก์

---

**ไฟล์ผลลัพธ์** อยู่ใน `outputs/`

```
outputs/
├── videos/        ไฟล์วิดีโอ (รวมคลิปที่ merge แล้วด้วย)
├── thumbnails/    รูปปกของทุกคลิป
└── frames/        เฟรมที่ดึงไว้สำหรับต่อคลิป
```

---

## แก้ปัญหาเบื้องต้น

| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| `start.bat` บอก "ยังไม่ได้ติดตั้ง" | รัน `install.bat` ก่อน |
| เปิดเว็บได้แต่ขึ้น backend ไม่พร้อม | เช็กหน้าต่าง `[H3 Backend]` ว่ามี error · เช็กว่าพอร์ต 8000 ไม่ถูกใช้ซ้ำ |
| สร้างวิดีโอแล้วค้าง 0% | ComfyUI ไม่ได้เปิด หรือโมเดลไม่ครบ — ดู log ในหน้าต่าง backend |
| `ไม่พบไฟล์เฟรมใน ComfyUI/input` | ไปหน้าเฟรม → กด "ส่งเข้า ComfyUI" ซ้ำ · ถ้าใช้ RunPod เช็กว่าอัปโหลดผ่าน |
| `ComfyUI /upload/image HTTP 404` | ระบบจะลอง `/api/upload/image` ให้อัตโนมัติ — ถ้ายังไม่ได้ ให้เช็ก URL ว่าชี้ถูกพอร์ต |
| CUDA out of memory | ลด Resolution ลง (0.5 → 0.35 MP) · ลด duration · ปิดงานอื่นที่ใช้ GPU |
| เครื่องอื่นใน LAN เข้าไม่ได้ | Firewall ยังไม่ allow พอร์ต 3000/8000 (ดูขั้นที่ 7) · เช็กว่าอยู่ Wi-Fi เดียวกัน |
| Copy Prompt ใช้ไม่ได้บนมือถือ | ระบบมี fallback ให้แล้ว — ถ้ายังไม่ได้ให้เปิดผ่าน `localhost` หรือใช้ HTTPS |
| รูปในคลังเฟรมไม่ขึ้น | เช็กว่า backend รันอยู่ · กดปุ่ม "ลองใหม่" บนการ์ด |
| build ล้มเหลวหลังแก้โค้ด | อ่าน error ในหน้าต่าง แล้วแก้ไฟล์ที่ระบุ · ถ้า dependencies เปลี่ยนให้รัน `install.bat` |
| งานเสร็จแต่ไม่โผล่ในประวัติ | เปิดหน้าใดก็ได้ของเว็บค้างไว้ ~3 วินาที ระบบจะซิงก์ย้อนหลังให้ |

---

## ข้อจำกัดที่ทราบ

- **ความยาววิดีโอ**: โมเดลเทรนไว้ช่วง ~5–15 วินาที (124–362 เฟรมที่ 24 fps) — เกิน 15 วิยังไม่มีหลักประกันคุณภาพ ระบบจึงล็อกตัวเลือกไว้ที่ 15
- **REF2VA**: หน้าเว็บจำกัดรูปอ้างอิง 2 รูป (ตัว node รองรับได้ถึง 9 — ยังไม่เปิดใน UI)
- **`ref_image_size`** (`match` / `max`) ยังไม่เปิดให้ปรับ — ค่า `max` ให้ตัวตนแม่นกว่าแต่ช้ากว่าหลายเท่า
- **Prompt tags** `<Picture 1>` / `<Video 1>` ยังไม่ใส่ให้อัตโนมัติ — เขียนเองใน prompt ได้เพื่อเพิ่มน้ำหนัก reference
- **ตัวละครเพี้ยนสะสม**: ต่อคลิปด้วย FL2VA ติดกันหลายคลิปโดยไม่กลับ REF2VA จะค่อย ๆ เพี้ยน — แนะนำกลับ REF2VA ทุก 2–3 ฉาก
- **รอยต่อตอนรวมคลิป**: การต่อกันตรง ๆ อาจกระตุกเล็กน้อย — ใช้ FL2VA แบบใส่ทั้ง first+last เพื่อสร้างคลิป transition จะเนียนกว่า crossfade
- **คิวเป็นแบบทีละงาน**: งานสร้าง prompt ต้องรอคิวหลังงานวิดีโอ (แต่รันเร็วเพราะไม่มี diffusion)
- **RunPod**: พอร์ต proxy บาง template ไม่รองรับ WebSocket → ระบบสลับไป dùng history polling ให้อัตโนมัติ

---

## แผนพัฒนาต่อ

- [ ] ตัวเลือก Vast.ai เป็นทางเลือกที่ 3 (+ SSH tunnel helper)
- [ ] รองรับรูปอ้างอิง REF2VA ถึง 9 รูป + toggle `ref_image_size`
- [ ] ใส่แท็ก `<Picture N>` ให้อัตโนมัติใน prompt REF2VA
- [ ] จัดการ template สร้าง prompt ผ่านหน้าเว็บ (ตาราง `LLMPromptTemplate` มีอยู่แล้ว)
- [ ] บันทึกประวัติการ enhance prompt (ตาราง `AIPromptEnhancement` มีอยู่แล้ว)
- [ ] ตัวกรองขั้นสูง: ช่วงวันที่ / ความยาว / สถานะ + ตัวเลือกเรียงลำดับ
- [ ] Favorites / ปักหมุดโปรเจค
- [ ] Timeline editor + Preview รวมเรื่อง
- [ ] Export / Import โปรเจค

---

## ผู้พัฒนา

**TonLikeIT** — Full Stack Developer & AI Enthusiast

- Facebook: [TonLikeIT](https://www.facebook.com/tonlikeit)
- YouTube: [TonLikeIT](https://www.youtube.com/@tonlikeit)
- GitHub: [Coding](https://github.com/tontheonelove)

---

## Stack ที่ใช้

**Frontend** — Next.js 16 · React · TypeScript · Tailwind CSS · shadcn/ui · lucide-react · sonner · Framer Motion
**Backend** — FastAPI · Uvicorn · Python 3.11
**Database** — Prisma + SQLite
**Engine** — ComfyUI · MiniMax H3 (FL2VA / REF2VA) · Pika H3 Flex LoRA · Gemma 4 VLM
**Media** — FFmpeg / FFprobe