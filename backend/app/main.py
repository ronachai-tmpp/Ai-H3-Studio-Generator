"""
========================================
FastAPI Main Application
========================================
Description:
    จุดเริ่มต้นของ backend ทั้งหมด
    - สร้าง FastAPI app
    - เปิด CORS ให้ Next.js localhost:3000 เรียกได้
    - ลงทะเบียน router ของแต่ละระบบ
    - เริ่ม queue worker ตอน startup
    - เตรียม outputs folders
    - รองรับ LLM idle watchdog ถ้าไฟล์ llm_service มีฟังก์ชันนี้
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import config
from app.mcp_server import build_mcp, mcp_asgi_app, register_mcp
from app.routers import generations, llm, media, series, system, uploads, workflows
from app.services.llm_service import llm_service
from app.services.queue_service import queue_service
from app.services.series_runtime import series_gateway, series_runner, series_service, series_store

# MCP server (สร้างครั้งเดียวตอน import: session_manager เข้า run() ได้ครั้งเดียวต่อ server)
mcp_server = build_mcp(series_service, series_store, series_gateway, config.OUTPUTS_DIR)
mcp_app = mcp_asgi_app(mcp_server, allow_lan=config.MCP_ALLOW_LAN)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle ของ FastAPI app

    Description:
        ตอน startup:
            - เตรียม outputs folders
            - เริ่ม queue worker
            - เริ่ม LLM idle watchdog ถ้ามี
            - เปิด session manager ของ MCP server

        ตอน shutdown:
            - ยกเลิก watchdog
            - unload LLM ถ้ามีฟังก์ชัน unload
            - หยุด queue worker
    """
    (config.OUTPUTS_DIR / "videos").mkdir(parents=True, exist_ok=True)
    (config.OUTPUTS_DIR / "thumbnails").mkdir(parents=True, exist_ok=True)

    series_store.load_all()
    queue_service.start_worker()
    series_runner.start()

    watchdog_task = None
    if hasattr(llm_service, "idle_watchdog"):
        watchdog_task = asyncio.create_task(llm_service.idle_watchdog())

    try:
        async with mcp_server.session_manager.run():
            yield
    finally:
        if watchdog_task is not None:
            watchdog_task.cancel()
            try:
                await watchdog_task
            except asyncio.CancelledError:
                pass

        if hasattr(llm_service, "unload"):
            try:
                llm_service.unload()
            except Exception:
                # ขณะ shutdown ไม่ควรให้ error มาบล็อกการปิด app
                pass

        # ต้องหยุด runner ก่อนคิว: คิวมาร์กงานที่รันอยู่เป็น CANCELLED ตอนหยุด runner ต้องไม่เห็นสถานะนั้น
        series_runner.stop()
        queue_service.stop_worker()


# สร้าง FastAPI app หลัก
app = FastAPI(
    title="MiniMax H3 Studio Backend",
    description="Backend สำหรับสร้างวิดีโอ AI ในเครื่อง (MiniMax H3 + ComfyUI engine)",
    version="0.1.0",
    lifespan=lifespan,
)

# อนุญาตให้ Next.js เรียก backend นี้จากทุก origin ใน LAN
# (localhost, 127.0.0.1, หรือ IP เครื่อง เช่น http://10.1.1.1:3000)
#
# Note:
# - allow_origins=["*"] ต้องคู่กับ allow_credentials=False ตาม CORS spec
# - แอปนี้ไม่ได้ใช้ cookie/auth ข้าม origin จึงไม่ต้องเปิด credentials
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ลงทะเบียน router แต่ละระบบ
app.include_router(system.router, prefix="/api/system", tags=["system"])
app.include_router(generations.router, prefix="/api/generations", tags=["generations"])
app.include_router(llm.router, prefix="/api/llm", tags=["llm"])
app.include_router(uploads.router, prefix="/api/uploads", tags=["uploads"])
app.include_router(workflows.router, prefix="/api/workflows", tags=["workflows"])
app.include_router(media.router, prefix="/api/media", tags=["media"])
app.include_router(series.router, prefix="/api/series", tags=["series"])


@app.get("/", summary="หน้ารากของ backend")
def root():
    """คืนข้อมูลพื้นฐานของ backend ใช้เช็คว่าบริการรันอยู่"""
    return {
        "service": "MiniMax H3 Studio Backend",
        "version": "0.1.0",
        "docs": "/docs",
        "engine": "comfyui-ref2va",
    }


# ลงทะเบียนเฉพาะ /mcp (ไม่ mount "/" เพราะจะทำให้ redirect ท้าย / และ 405 ของ route อื่นหาย)
register_mcp(app, mcp_app)