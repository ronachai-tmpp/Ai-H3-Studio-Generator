"""
========================================
Console Encoding
========================================
Description:
    backend พิมพ์ log เป็นภาษาไทยด้วย print() หลายจุด
    บน Windows ถ้า stdout/stderr ไม่ใช่ console (ถูกส่งลงไฟล์หรือ pipe)
    Python จะใช้ codepage ของเครื่อง (เช่น cp1252) ซึ่งไม่มีอักษรไทย
    print() จึงโยน UnicodeEncodeError กลางงาน และทำให้งาน generate ล้มทั้งงาน
"""
from __future__ import annotations

import sys


def ensure_utf8_stdio() -> None:
    """
    บังคับให้ stdout/stderr เขียนเป็น UTF-8 และไม่โยน error เมื่อเจออักษรที่เข้ารหัสไม่ได้
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        reconfigure(encoding="utf-8", errors="replace")
