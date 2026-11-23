# Series Runner + MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Claude Code write a vertical episodic series and have H3 Studio generate it scene by scene, unattended, until the story ends.

**Architecture:** A series runner thread inside the FastAPI backend owns the series state (JSON on disk) and drives the existing in-memory job queue one scene at a time. An MCP server mounted in the same FastAPI app is a thin remote control over that service; a small REST router feeds a read-only web page. Everything the runner needs from the queue, ffmpeg and ComfyUI goes through one gateway object, so the state machine is tested without a GPU.

**Tech Stack:** Python 3.13, FastAPI 0.115, Pydantic 2, `mcp` 2.3 (`MCPServer`, Streamable HTTP), pytest; Next.js 16, React 19, TypeScript, Tailwind, shadcn/ui.

**Spec:** `docs/superpowers/specs/2026-11-23-series-mcp-design.md` (Thai). Read it before starting any task; section numbers below refer to it.

## Global Constraints

- Work on branch `feature/series-mcp`. Commit per task. Never push.
- Do not change the behavior of any existing endpoint, the queue, or any ComfyUI workflow. Existing files are touched only where a task lists them.
- Never delete user files. Regenerating or re-merging leaves old files on disk.
- New Python code follows the existing style: Thai docstrings/comments, `from __future__ import annotations`, type hints.
- All media paths stored in series state are relative to `config.OUTPUTS_DIR` with forward slashes (`videos/x.mp4`, `series/<id>/refs/a.jpg`).
- Allowed scene durations: `5, 8, 10, 12, 15`. Allowed megapixels: `0.1, 0.25, 0.35, 0.5, 0.75, 1.0`. Max scenes per episode: `20`. Max reference images per scene: `9`.
- Series defaults: aspect ratio `"9:16 (Portrait Widescreen)"`, megapixels `0.35`, `run_mode="autopilot"`, `max_attempts=2`, `low_vram=False`.
- Job result files are named by job id: `videos/{job_id}.mp4`, `frames/{job_id}_last.jpg`, `thumbnails/{job_id}.jpg`.
- Only one new runtime dependency: `mcp>=2.3,<3`. Dev-only: `pytest`, `httpx`.
- `/mcp` accepts loopback clients only unless `mcp_allow_lan` is true in `backend/config.json`.
- Run Python tests from `backend/` with `venv\Scripts\python.exe -m pytest`.
- User-facing strings (errors returned to Claude or shown in the web page) are Thai, matching the rest of the app.

## Review Focus

1. A series title made only of Thai characters, or containing `<>:"/\|?*` — the series id and exported filenames must still be valid on Windows (Task 1, Task 3).
2. A corrupt or half-written `series.json` at startup — the backend still starts and the other series load (Task 1).
3. A character image path that is missing, not an image, or over the upload size limit — a clear error, series unchanged (Task 2).
4. Merging an episode fails (ffmpeg missing, disk full) — the series pauses once with the error; the merge is not retried every tick (Task 4).
5. A scene is regenerated while its job is queued, and the cancelled job's result arrives later — the stale result is ignored (Task 4).

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/services/series_models.py` | Pydantic models, constants, pure helpers (validation, id, progress) |
| `backend/app/services/series_store.py` | Load/save `series.json`, lock, event log for `series_wait` |
| `backend/app/services/series_gateway.py` | `StudioGateway` Protocol — everything the series code needs from the outside |
| `backend/app/services/series_service.py` | Mutations: create, characters, episodes, scene edits, control |
| `backend/app/services/series_export.py` | Manifest, export folder, review images |
| `backend/app/services/series_runner.py` | Tick state machine + background thread |
| `backend/app/services/series_runtime.py` | `RealGateway` and the process singletons |
| `backend/app/routers/series.py` | REST for the web page |
| `backend/app/services/series_guide.py` | Text of `series_guide` and the `new_series` prompt |
| `backend/app/mcp_server.py` | MCP tools, loopback guard, ASGI app |
| `backend/tests/` | pytest suite, `fakes.py` (`FakeGateway`) |
| `components/series/series-view.tsx`, `app/(studio)/series/page.tsx` | Web page |

---

### Task 1: Models, validation, store

**Files:**
- Create: `backend/app/services/series_models.py`, `backend/app/services/series_store.py`
- Create: `backend/requirements-dev.txt` (`pytest`, `httpx`), `backend/pytest.ini` (`pythonpath = .`, `testpaths = tests`)
- Test: `backend/tests/conftest.py`, `backend/tests/test_series_models.py`, `backend/tests/test_series_store.py`

**Interfaces:**
- Produces (`series_models.py`):

```python
ALLOWED_DURATIONS = (5, 8, 10, 12, 15)
ALLOWED_MEGAPIXELS = (0.1, 0.25, 0.35, 0.5, 0.75, 1.0)
DEFAULT_ASPECT_RATIO = "9:16 (Portrait Widescreen)"
DEFAULT_MEGAPIXELS = 0.35
DEFAULT_MAX_ATTEMPTS = 2
MAX_SCENES_PER_EPISODE = 20
MAX_REF_IMAGES_PER_SCENE = 9
CASTING_DURATION_SECONDS = 5

class SeriesError(ValueError): ...            # ข้อความภาษาไทย ส่งต่อให้ผู้ใช้ได้เลย

class RefImage(BaseModel):
    path: str                                  # outputs-relative
    comfy_name: str | None = None
    comfy_base_url: str | None = None

class Character(BaseModel):
    name: str
    description: str = ""
    reference_images: list[RefImage] = []
    casting_prompt: str | None = None
    casting_job_id: str | None = None
    casting_attempts: int = 0

class Scene(BaseModel):
    index: int
    prompt: str
    beat: str = ""
    mode: Literal["text", "ref", "chain"]
    characters: list[str] = []
    duration_seconds: int = 5
    seed: int = -1
    status: Literal["PENDING", "QUEUED", "RUNNING", "DONE", "FAILED"] = "PENDING"
    job_id: str | None = None
    attempts: int = 0
    progress: int = 0
    error: str | None = None
    video_path: str | None = None
    thumbnail_path: str | None = None
    last_frame_path: str | None = None
    started_at: float | None = None            # epoch seconds
    finished_at: float | None = None

class Episode(BaseModel):
    number: int
    title: str
    synopsis: str = ""
    caption: str = ""
    hashtags: list[str] = []
    status: Literal["PENDING", "RUNNING", "DONE"] = "PENDING"
    scenes: list[Scene]
    final_video_path: str | None = None
    thumbnail_path: str | None = None
    duration: float | None = None

class Series(BaseModel):
    id: str
    title: str
    logline: str = ""
    style_notes: str = ""
    aspect_ratio: str = DEFAULT_ASPECT_RATIO
    megapixels: float = DEFAULT_MEGAPIXELS
    low_vram: bool = False
    run_mode: Literal["autopilot", "review"] = "autopilot"
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    status: Literal["DRAFT", "RUNNING", "PAUSED", "DONE", "CANCELLED"] = "DRAFT"
    pause_reason: Literal["user", "review", "casting", "error"] | None = None
    pause_message: str | None = None
    story_complete: bool = False
    characters: list[Character] = []
    episodes: list[Episode] = []
    created_at: float
    updated_at: float

def new_series_id(title: str) -> str            # "<ascii-slug>-<6 hex>"; ถ้า slug ว่าง ใช้ "series-<6 hex>"
def slugify(text: str) -> str                   # a-z0-9 กับ "-" เท่านั้น อาจคืน ""
def job_type_for(mode: str, low_vram: bool) -> str   # T2V / REF2VA / FL2VA (+ "_LOW")
def needs_casting(character: Character) -> bool # ไม่มีรูป และมี casting_prompt
def find_character(series: Series, name: str) -> Character | None
def validate_series(series: Series) -> list[str]     # [] = ผ่าน
def waiting_for(series: Series) -> str | None   # "episodes" เมื่อ RUNNING, ทุกตอน DONE, ยังไม่ story_complete
def progress_of(series: Series) -> dict         # scenes_done, scenes_total, avg_scene_seconds, eta_seconds
```

- Produces (`series_store.py`):

```python
class SeriesStore:
    def __init__(self, root: Path)              # root = OUTPUTS_DIR / "series"
    lock: threading.RLock
    load_errors: list[str]                      # ชื่อโฟลเดอร์ที่โหลดไม่ได้
    def load_all(self) -> None
    def list(self) -> list[Series]              # เรียงตาม created_at
    def get(self, series_id: str) -> Series     # ไม่พบ → SeriesError
    def add(self, series: Series) -> None       # บันทึกทันที
    def save(self, series: Series, event: str | None = None) -> None
    def series_dir(self, series_id: str) -> Path
    def cursor(self, series_id: str) -> int
    def wait_events(self, series_id: str, after: int, timeout: float) -> tuple[int, list[str]]
```

`validate_series` rules (spec 5.3 plus limits): aspect ratio in `workflow_service.ALLOWED_ASPECT_RATIOS`; megapixels and every duration in the allowed tuples; prompt non-empty; character names unique; 1–20 scenes per episode; episode 1 scene 1 is not `chain`; a `ref` scene lists at least one character, each exists and has an image or a `casting_prompt`; images across a `ref` scene's characters total at most 9 (a character awaiting casting counts as 1).

`progress_of`: `avg_scene_seconds` = mean of `finished_at - started_at` over DONE scenes that have both (None if none); `eta_seconds` = avg × scenes not DONE (None if avg is None).

`save` writes `series_dir/series.json` via temp file + `os.replace`, sets `updated_at`, and when `event` is given appends it to an in-memory per-series event log and notifies waiters. `wait_events` returns `(new_cursor, events_after)` as soon as there is at least one event past `after`, else `(after, [])` at timeout.

- [ ] **Step 1: Add dev tooling** — `requirements-dev.txt`, `pytest.ini`, install into `backend/venv`.

Run: `venv\Scripts\python.exe -m pip install -r requirements-dev.txt` then `venv\Scripts\python.exe -m pytest` → "no tests ran".

- [ ] **Step 2: Write `conftest.py`**

```python
@pytest.fixture
def outputs(tmp_path) -> Path:        # tmp outputs/ with videos, frames, thumbnails, series
@pytest.fixture
def store(outputs) -> SeriesStore:    # SeriesStore(outputs / "series")
@pytest.fixture
def make_series(outputs):             # callable(**overrides) -> Series (not added to a store)
```

`make_series()` default: id `"demo-abc123"`, title `"Demo"`, one character `mali` with `RefImage(path="series/demo-abc123/refs/mali_1.jpg")` (file created on disk), episode 1 = scenes `[text, ref(mali), chain]`, episode 2 = `[chain, text]`, all 5 seconds, all `PENDING`.

- [ ] **Step 3: Write failing model tests**

```python
def test_job_type_for():
    assert job_type_for("text", False) == "T2V"
    assert job_type_for("ref", False) == "REF2VA"
    assert job_type_for("chain", False) == "FL2VA"
    assert job_type_for("chain", True) == "FL2VA_LOW"

def test_default_series_is_valid(make_series):
    assert validate_series(make_series()) == []

def test_first_scene_of_first_episode_cannot_chain(make_series):
    s = make_series(); s.episodes[0].scenes[0].mode = "chain"
    assert len(validate_series(s)) == 1

def test_ref_scene_needs_known_character_with_image_or_casting(make_series):
    s = make_series(); s.episodes[0].scenes[1].characters = ["nobody"]
    assert validate_series(s)
    s.episodes[0].scenes[1].characters = []
    assert validate_series(s)
    s.episodes[0].scenes[1].characters = ["mali"]
    s.characters[0].reference_images = []
    assert validate_series(s)
    s.characters[0].casting_prompt = "a young woman"
    assert validate_series(s) == []

def test_duration_and_megapixels_must_be_allowed(make_series):
    s = make_series(megapixels=0.4); assert validate_series(s)
    s = make_series(); s.episodes[0].scenes[0].duration_seconds = 7
    assert validate_series(s)

def test_scene_count_limit(make_series):
    s = make_series()
    s.episodes[0].scenes = [Scene(index=i, prompt="p", mode="text") for i in range(1, 22)]
    assert validate_series(s)

def test_reference_image_limit(make_series):
    s = make_series()
    s.characters[0].reference_images = [RefImage(path=f"series/x/refs/{i}.jpg") for i in range(10)]
    assert validate_series(s)

def test_new_series_id():
    assert re.fullmatch(r"love-story-[0-9a-f]{6}", new_series_id("Love Story!"))
    assert re.fullmatch(r"series-[0-9a-f]{6}", new_series_id("รักข้ามเวลา"))
    assert re.fullmatch(r"series-[0-9a-f]{6}", new_series_id('<>:"/\\|?*'))

def test_waiting_for(make_series):
    s = make_series(status="RUNNING")
    assert waiting_for(s) is None
    for e in s.episodes: e.status = "DONE"
    assert waiting_for(s) == "episodes"
    s.story_complete = True
    assert waiting_for(s) is None

def test_progress_of(make_series):
    s = make_series()
    a, b = s.episodes[0].scenes[0], s.episodes[0].scenes[1]
    a.status = b.status = "DONE"
    a.started_at, a.finished_at = 0.0, 100.0
    b.started_at, b.finished_at = 100.0, 300.0
    assert progress_of(s) == {"scenes_done": 2, "scenes_total": 5,
                              "avg_scene_seconds": 150.0, "eta_seconds": 450.0}
```

- [ ] **Step 4: Run** `venv\Scripts\python.exe -m pytest tests/test_series_models.py -v` → FAIL (import error).
- [ ] **Step 5: Implement `series_models.py`.** Run again → PASS.
- [ ] **Step 6: Write failing store tests**

```python
def test_roundtrip(store, make_series, outputs):
    store.add(make_series())
    fresh = SeriesStore(outputs / "series"); fresh.load_all()
    assert fresh.get("demo-abc123").episodes[1].scenes[0].mode == "chain"

def test_save_leaves_no_temp_file(store, make_series):
    s = make_series(); store.add(s); store.save(s)
    assert [p.name for p in store.series_dir(s.id).iterdir() if p.is_file()] == ["series.json"]

def test_corrupt_file_is_skipped(store, make_series, outputs):
    store.add(make_series())
    bad = outputs / "series" / "bad"; bad.mkdir(); (bad / "series.json").write_text("{not json")
    fresh = SeriesStore(outputs / "series"); fresh.load_all()
    assert [s.id for s in fresh.list()] == ["demo-abc123"]
    assert fresh.load_errors == ["bad"]

def test_get_unknown_raises(store):
    with pytest.raises(SeriesError): store.get("nope")

def test_wait_events_returns_new_events(store, make_series):
    s = make_series(); store.add(s)
    c = store.cursor(s.id)
    store.save(s, event="EP01 scene 1 DONE")
    assert store.wait_events(s.id, c, timeout=1.0) == (c + 1, ["EP01 scene 1 DONE"])

def test_wait_events_times_out(store, make_series):
    s = make_series(); store.add(s)
    c = store.cursor(s.id); t = time.monotonic()
    assert store.wait_events(s.id, c, timeout=0.2) == (c, [])
    assert time.monotonic() - t < 1.0

def test_save_without_event_does_not_wake_waiters(store, make_series):
    s = make_series(); store.add(s); c = store.cursor(s.id)
    store.save(s)
    assert store.cursor(s.id) == c
```

- [ ] **Step 7: Run → FAIL. Implement `series_store.py`. Run → PASS.**
- [ ] **Step 8: Commit** `feat(series): models, validation and JSON store`

---

### Task 2: Service mutations

**Files:**
- Create: `backend/app/services/series_gateway.py`, `backend/app/services/series_service.py`
- Test: `backend/tests/fakes.py`, `backend/tests/test_series_service.py`

**Interfaces:**
- Consumes: everything from Task 1.
- Produces (`series_gateway.py`):

```python
class StudioGateway(Protocol):
    def submit_job(self, *, prompt: str, job_type: str, megapixels: float, aspect_ratio: str,
                   duration_seconds: int, seed: int,
                   reference_names: list[str] | None = None,
                   first_frame_name: str | None = None) -> str: ...
    def get_job(self, job_id: str) -> dict | None: ...   # keys: status, progress, error, video_path, thumbnail_path, duration
    def cancel_job(self, job_id: str) -> None: ...
    def find_output_video(self, job_id: str) -> str | None: ...   # "videos/<job_id>.<ext>" ถ้ามีไฟล์
    def output_exists(self, rel_path: str) -> bool: ...
    def push_image(self, rel_path: str) -> str: ...      # → ชื่อไฟล์ใน ComfyUI input
    def comfy_base_url(self) -> str: ...
    def comfy_input_exists(self, name: str) -> bool | None: ...   # None = ตรวจไม่ได้ (remote)
    def extract_frame(self, video_rel: str, dest_rel: str, position: str = "last",
                      offset_from_end: int = 0) -> bool: ...
    def concat(self, video_rels: list[str], dest_rel: str) -> dict: ...        # {"ok": bool, "error": str | None}
    def make_thumbnail(self, video_rel: str, thumb_rel: str) -> dict: ...      # {"thumbnail_created": bool, "duration": float | None}
    def sample_frames(self, video_rel: str, out_dir_rel: str, count: int, max_edge: int = 512) -> list[str]: ...
    def studio_info(self) -> dict: ...                   # comfyui_ok, comfyui_mode, vram, queue_pending, queue_running
```

- Produces (`series_service.py`):

```python
class SeriesService:
    def __init__(self, store: SeriesStore, gateway: StudioGateway, outputs_dir: Path,
                 allowed_image_extensions: Sequence[str], max_image_bytes: int)
    def create_series(self, title: str, logline: str = "", style_notes: str = "",
                      aspect_ratio: str = DEFAULT_ASPECT_RATIO, megapixels: float = DEFAULT_MEGAPIXELS,
                      low_vram: bool = False, run_mode: str = "autopilot") -> Series
    def set_character(self, series_id: str, name: str, description: str = "",
                      image_paths: list[str] | None = None, casting_prompt: str | None = None) -> Character
    def write_episode(self, series_id: str, title: str, scenes: list[dict], synopsis: str = "",
                      caption: str = "", hashtags: list[str] | None = None,
                      episode_number: int | None = None) -> Episode
    def update_scene(self, series_id: str, episode_number: int, scene_index: int, *,
                     prompt: str | None = None, beat: str | None = None, mode: str | None = None,
                     characters: list[str] | None = None, duration_seconds: int | None = None,
                     seed: int | None = None, regenerate: bool = False) -> list[tuple[int, int]]
    def control(self, series_id: str, action: str) -> Series   # start | pause | resume | finish | cancel
    def detail(self, series_id: str) -> dict      # series.model_dump() + "progress" + "waiting_for"
    def overview(self) -> list[dict]              # id, title, status, pause_reason, waiting_for, episodes_done, episodes_total, progress
```

Behavior the tests pin (spec 5.2, 5.5):

- Every mutation takes `store.lock`, validates the resulting series with `validate_series`, and raises `SeriesError` leaving the stored series unchanged when invalid.
- `set_character` with an existing name replaces `description`, `casting_prompt` and the whole image set. Images are copied to `series/<id>/refs/<stem>_<n><ext>`, where `<stem>` is `slugify(name)` or, when that is empty (Thai names), `char<k>` with `k` the character's 1-based position in `series.characters` — two Thai-named characters must not share files. An `image_paths` entry is an absolute path or a path relative to `outputs_dir`. Passing `casting_prompt` without images clears existing images (re-cast) and resets `casting_job_id` / `casting_attempts`. DONE scenes are never reset by this call.
- `write_episode` with `episode_number=None` appends. With an existing number it replaces that episode only if every scene is `PENDING`. Scene dicts take `prompt, mode, beat, characters, duration_seconds, seed`; `index` is assigned 1..n.
- `update_scene` returns the list of `(episode_number, scene_index)` it reset. A scene is reset (status `PENDING`, `job_id/attempts/progress/error/video_path/thumbnail_path/last_frame_path/started_at/finished_at` cleared, in-flight job cancelled through the gateway) when `regenerate=True`, or when a `QUEUED`/`RUNNING` scene is edited. Resetting a scene also resets every directly following `chain` scene, crossing episode boundaries, until the first non-`chain` scene. Each touched episode gets status `PENDING` and `final_video_path/thumbnail_path/duration` cleared.
- Series status after `update_scene` with a reset or `write_episode`: `RUNNING` stays, `PAUSED` stays, `DONE` → `RUNNING`, `CANCELLED` → `SeriesError`, `DRAFT` stays.
- `control`: `start` only from `DRAFT`, needs at least one episode, → `RUNNING`. `pause` only from `RUNNING` → `PAUSED` / `user`. `resume` only from `PAUSED` → `RUNNING`, clears pause fields; if the reason was `error`, every `FAILED` scene becomes `PENDING` with `attempts=0` and every character's `casting_attempts=0`. `finish` sets `story_complete=True` (not on `CANCELLED`). `cancel` cancels in-flight scene and casting jobs → `CANCELLED`. Anything else, or any action on `CANCELLED`, raises `SeriesError`.

- [ ] **Step 1: Write `fakes.py`**

```python
class FakeGateway:
    def __init__(self, outputs: Path)
    jobs: dict[str, dict]            # job_id → snapshot
    submitted: list[dict]            # kwargs of each submit_job, plus "job_id"
    cancelled: list[str]
    pushed: list[str]                # rel paths passed to push_image
    input_names: set[str]            # names currently "in ComfyUI input"
    base_url: str = "http://127.0.0.1:8188"
    concat_result: dict = {"ok": True, "error": None}
    concat_calls: list[tuple[list[str], str]]
    extract_calls: list[tuple[str, str, str, int]]
    def finish(self, job_id: str, status: str = "DONE", error: str | None = None) -> None
    def set_running(self, job_id: str, progress: int) -> None
    def forget(self, job_id: str) -> None
```

`submit_job` returns `"job-1"`, `"job-2"`, …. `finish(..., "DONE")` creates `videos/<id>.mp4`, `frames/<id>_last.jpg`, `thumbnails/<id>.jpg` and fills the snapshot (`duration` = `10.0`). `push_image` returns `"in_<n><suffix>"` and adds it to `input_names`. `comfy_input_exists` is membership in `input_names`. `extract_frame`, `concat` (when `ok`), `make_thumbnail` and `sample_frames` create the destination files; `make_thumbnail` returns `{"thumbnail_created": True, "duration": 10.0}`.

Add fixtures to `conftest.py`: `gateway(outputs) -> FakeGateway`, `service(store, gateway, outputs) -> SeriesService` (extensions `[".png", ".jpg", ".jpeg", ".webp"]`, max bytes `1_000_000`), and `done_series(service, store, gateway, make_series)` → the default series added to the store with every scene `DONE` (real files via `gateway.finish`), both episodes `DONE` with `final_video_path` set, status `DONE`, `story_complete=True`.

- [ ] **Step 2: Write failing tests**

```python
def test_create_defaults(service):
    s = service.create_series("Love Story")
    assert (s.aspect_ratio, s.megapixels, s.run_mode, s.status, s.max_attempts) == \
           ("9:16 (Portrait Widescreen)", 0.35, "autopilot", "DRAFT", 2)

def test_create_rejects_bad_megapixels(service):
    with pytest.raises(SeriesError): service.create_series("x", megapixels=0.4)

def test_set_character_copies_image(service, outputs, tmp_path):
    s = service.create_series("x"); src = tmp_path / "face.png"; src.write_bytes(b"png")
    c = service.set_character(s.id, "Mali", image_paths=[str(src)])
    assert c.reference_images[0].path == f"series/{s.id}/refs/mali_1.png"
    assert (outputs / c.reference_images[0].path).read_bytes() == b"png" and src.exists()

def test_set_character_accepts_outputs_relative_path(service, outputs):
    s = service.create_series("x"); (outputs / "frames" / "f.jpg").write_bytes(b"j")
    assert service.set_character(s.id, "Mali", image_paths=["frames/f.jpg"]).reference_images

def test_set_character_replaces_image_set(service, tmp_path):
    s = service.create_series("x"); a = tmp_path / "a.jpg"; a.write_bytes(b"a")
    service.set_character(s.id, "Mali", image_paths=[str(a), str(a)])
    assert len(service.set_character(s.id, "Mali", image_paths=[str(a)]).reference_images) == 1

@pytest.mark.parametrize("make", ["missing", "not_image", "too_big"])
def test_set_character_rejects_bad_image(service, store, tmp_path, make):
    s = service.create_series("x")
    p = tmp_path / ("a.txt" if make == "not_image" else "a.jpg")
    if make != "missing": p.write_bytes(b"x" * (2_000_000 if make == "too_big" else 10))
    with pytest.raises(SeriesError): service.set_character(s.id, "Mali", image_paths=[str(p)])
    assert store.get(s.id).characters == []

def test_recast_clears_images_and_keeps_done_scenes(service, done_series):
    c = service.set_character(done_series.id, "mali", casting_prompt="new face")
    assert c.reference_images == [] and c.casting_prompt == "new face"
    assert service.detail(done_series.id)["episodes"][0]["scenes"][1]["status"] == "DONE"

def test_write_episode_appends_and_numbers(service):
    s = service.create_series("x")
    e1 = service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    e2 = service.write_episode(s.id, "two", [{"prompt": "p", "mode": "chain"}, {"prompt": "q", "mode": "text"}])
    assert (e1.number, e2.number, [x.index for x in e2.scenes]) == (1, 2, [1, 2])

def test_write_episode_replace_only_if_not_started(service, store):
    s = service.create_series("x")
    service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    assert service.write_episode(s.id, "one b", [{"prompt": "p2", "mode": "text"}], episode_number=1).title == "one b"
    live = store.get(s.id); live.episodes[0].scenes[0].status = "QUEUED"; store.save(live)
    with pytest.raises(SeriesError):
        service.write_episode(s.id, "again", [{"prompt": "p", "mode": "text"}], episode_number=1)

def test_invalid_episode_leaves_series_unchanged(service, store):
    s = service.create_series("x")
    with pytest.raises(SeriesError): service.write_episode(s.id, "one", [{"prompt": "p", "mode": "chain"}])
    assert store.get(s.id).episodes == []

def test_edit_pending_scene_resets_nothing(service):
    s = service.create_series("x"); service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    assert service.update_scene(s.id, 1, 1, prompt="new") == []
    assert service.detail(s.id)["episodes"][0]["scenes"][0]["prompt"] == "new"

def test_regenerate_resets_following_chain_scenes_across_episodes(service, store, done_series, outputs):
    old = done_series.episodes[0].scenes[1].video_path
    assert service.update_scene(done_series.id, 1, 2, regenerate=True) == [(1, 2), (1, 3), (2, 1)]
    s = store.get(done_series.id)
    assert s.episodes[1].scenes[1].status == "DONE"
    assert [e.status for e in s.episodes] == ["PENDING", "PENDING"]
    assert s.episodes[0].final_video_path is None
    assert (outputs / old).exists()                 # ไฟล์เก่าไม่ถูกลบ
    assert s.status == "RUNNING" and s.story_complete is True

def test_regenerate_queued_scene_cancels_job(service, store, gateway):
    s = service.create_series("x"); service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    live = store.get(s.id); sc = live.episodes[0].scenes[0]
    sc.status, sc.job_id = "QUEUED", "job-9"; store.save(live)
    service.update_scene(s.id, 1, 1, prompt="new")
    assert gateway.cancelled == ["job-9"] and store.get(s.id).episodes[0].scenes[0].job_id is None

def test_regenerate_status_rules(service, store, done_series):
    live = store.get(done_series.id); live.status, live.pause_reason = "PAUSED", "user"; store.save(live)
    service.update_scene(done_series.id, 1, 1, regenerate=True)
    assert store.get(done_series.id).status == "PAUSED"
    live = store.get(done_series.id); live.status = "CANCELLED"; store.save(live)
    with pytest.raises(SeriesError): service.update_scene(done_series.id, 1, 1, regenerate=True)

def test_write_episode_reopens_done_series(service, store, done_series):
    service.write_episode(done_series.id, "three", [{"prompt": "p", "mode": "text"}])
    assert store.get(done_series.id).status == "RUNNING"

def test_control_transitions(service, store):
    s = service.create_series("x")
    with pytest.raises(SeriesError): service.control(s.id, "start")          # ไม่มีตอน
    service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    assert service.control(s.id, "start").status == "RUNNING"
    with pytest.raises(SeriesError): service.control(s.id, "start")
    p = service.control(s.id, "pause"); assert (p.status, p.pause_reason) == ("PAUSED", "user")
    r = service.control(s.id, "resume"); assert (r.status, r.pause_reason) == ("RUNNING", None)
    assert service.control(s.id, "finish").story_complete is True
    assert service.control(s.id, "cancel").status == "CANCELLED"
    with pytest.raises(SeriesError): service.control(s.id, "resume")

def test_resume_from_error_resets_failed_scenes(service, store):
    s = service.create_series("x"); service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    live = store.get(s.id); live.status, live.pause_reason = "PAUSED", "error"
    sc = live.episodes[0].scenes[0]; sc.status, sc.attempts, sc.error = "FAILED", 2, "boom"; store.save(live)
    service.control(s.id, "resume")
    sc = store.get(s.id).episodes[0].scenes[0]
    assert (sc.status, sc.attempts, sc.error) == ("PENDING", 0, None)

def test_cancel_cancels_in_flight_job(service, store, gateway):
    s = service.create_series("x"); service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    service.control(s.id, "start")
    live = store.get(s.id); live.episodes[0].scenes[0].job_id = "job-3"; live.episodes[0].scenes[0].status = "RUNNING"; store.save(live)
    service.control(s.id, "cancel")
    assert gateway.cancelled == ["job-3"]

def test_detail_and_overview(service, done_series):
    d = service.detail(done_series.id)
    assert d["progress"]["scenes_done"] == 5 and d["waiting_for"] is None
    row = service.overview()[0]
    assert (row["id"], row["episodes_done"], row["episodes_total"]) == (done_series.id, 2, 2)
```

- [ ] **Step 3: Run** `venv\Scripts\python.exe -m pytest tests/test_series_service.py -v` → FAIL.
- [ ] **Step 4: Implement `series_gateway.py` and `series_service.py`.** Run → PASS. Run the whole suite → PASS.
- [ ] **Step 5: Commit** `feat(series): service mutations and regenerate rules`

---

### Task 3: Manifest, export, review images

**Files:**
- Create: `backend/app/services/series_export.py`
- Test: `backend/tests/test_series_export.py`

**Interfaces:**
- Consumes: `SeriesStore`, `StudioGateway`, models; fixtures `done_series`, `gateway`, `store`, `outputs`.
- Produces:

```python
def build_manifest(series: Series) -> dict
def write_manifest(store: SeriesStore, series: Series) -> Path       # series_dir/manifest.json
def safe_filename(text: str) -> str
def export_series(store: SeriesStore, outputs_dir: Path, series_id: str) -> dict   # {"dir": rel, "files": [names]}
def review_images(store: SeriesStore, gateway: StudioGateway, series_id: str, *,
                  episode: int | None = None, scene: int | None = None,
                  character: str | None = None, frames: int = 4) -> tuple[str, list[str]]
```

`build_manifest` → `{"id", "title", "logline", "aspect_ratio", "story_complete", "episodes": [{"number", "title", "synopsis", "caption", "hashtags", "video", "thumbnail", "duration"}]}`, DONE episodes only, `video` = `final_video_path`.

`safe_filename`: replace each of `<>:"/\|?*` and control characters with a space, collapse whitespace, strip trailing dots and spaces; Thai is kept.

`export_series` copies each DONE episode to `series/<id>/export/EP01 - <safe title>.mp4` (`EP01.mp4` when the safe title is empty) and its thumbnail to `EP01.jpg`, and writes `export/manifest.json` whose `video` / `thumbnail` are those filenames. Re-running overwrites. No DONE episode → `SeriesError`.

`review_images` returns `(text, outputs-relative image paths)`. Exactly one of `episode` / `character` is required, else `SeriesError`. `episode` + `scene`: scene must be DONE; `gateway.sample_frames(video, f"series/<id>/review/ep01_s02", count=clamp(frames, 1, 8), max_edge=512)`; text holds mode, duration and the prompt. `episode` only: the `last_frame_path` of every DONE scene, text lists scene index → beat. `character`: its reference image paths, text holds description; no images → `SeriesError`.

- [ ] **Step 1: Write failing tests**

```python
def test_manifest_lists_done_episodes(done_series):
    m = build_manifest(done_series)
    assert [e["number"] for e in m["episodes"]] == [1, 2]
    assert m["episodes"][0]["video"] == done_series.episodes[0].final_video_path
    assert set(m["episodes"][0]) == {"number", "title", "synopsis", "caption", "hashtags", "video", "thumbnail", "duration"}

def test_manifest_skips_unfinished_episodes(done_series):
    done_series.episodes[1].status = "PENDING"
    assert [e["number"] for e in build_manifest(done_series)["episodes"]] == [1]

def test_safe_filename():
    assert safe_filename('ตอน: "แรก"?') == "ตอน แรก"
    assert safe_filename("a/b\\c. ") == "a b c"
    assert safe_filename('<>:"/\\|?*') == ""

def test_export_copies_with_clean_names(store, outputs, done_series):
    live = store.get(done_series.id)
    live.episodes[0].title = 'เจอกัน: "ครั้งแรก"'; live.episodes[1].title = "???"; store.save(live)
    out = export_series(store, outputs, done_series.id)
    assert out["dir"] == f"series/{done_series.id}/export"
    assert sorted(out["files"]) == ["EP01 - เจอกัน ครั้งแรก.mp4", "EP01.jpg", "EP02.jpg", "EP02.mp4", "manifest.json"]
    m = json.loads((outputs / out["dir"] / "manifest.json").read_text(encoding="utf-8"))
    assert m["episodes"][0]["video"] == "EP01 - เจอกัน ครั้งแรก.mp4"

def test_export_without_done_episode_raises(store, outputs, make_series):
    s = make_series(); store.add(s)
    with pytest.raises(SeriesError): export_series(store, outputs, s.id)

def test_review_scene_samples_frames(store, gateway, done_series, outputs):
    text, images = review_images(store, gateway, done_series.id, episode=1, scene=2, frames=3)
    assert len(images) == 3 and all((outputs / p).is_file() for p in images)
    assert done_series.episodes[0].scenes[1].prompt in text

def test_review_frames_clamped(store, gateway, done_series):
    assert len(review_images(store, gateway, done_series.id, episode=1, scene=1, frames=99)[1]) == 8

def test_review_episode_returns_last_frames(store, gateway, done_series):
    _, images = review_images(store, gateway, done_series.id, episode=1)
    assert images == [s.last_frame_path for s in done_series.episodes[0].scenes]

def test_review_character_returns_reference_images(store, gateway, done_series):
    assert review_images(store, gateway, done_series.id, character="mali")[1] == \
           ["series/demo-abc123/refs/mali_1.jpg"]

def test_review_rejects_bad_requests(store, gateway, done_series, make_series):
    with pytest.raises(SeriesError): review_images(store, gateway, done_series.id)
    with pytest.raises(SeriesError): review_images(store, gateway, done_series.id, episode=1, character="mali")
    with pytest.raises(SeriesError): review_images(store, gateway, done_series.id, episode=9)
    live = store.get(done_series.id); live.episodes[0].scenes[0].status = "PENDING"; store.save(live)
    with pytest.raises(SeriesError): review_images(store, gateway, done_series.id, episode=1, scene=1)
```

- [ ] **Step 2: Run** `venv\Scripts\python.exe -m pytest tests/test_series_export.py -v` → FAIL.
- [ ] **Step 3: Implement `series_export.py`.** Run → PASS.
- [ ] **Step 4: Commit** `feat(series): manifest, export and review images`

---

### Task 4: Runner — scenes, outcomes, merge

**Files:**
- Create: `backend/app/services/series_runner.py`
- Test: `backend/tests/test_series_runner.py`

**Interfaces:**
- Consumes: `SeriesStore`, `StudioGateway`, `SeriesService` (tests only), `write_manifest`, `job_type_for`.
- Produces:

```python
class SeriesRunner:
    def __init__(self, store: SeriesStore, gateway: StudioGateway,
                 tick_seconds: float = 1.0, clock: Callable[[], float] = time.time)
    def tick(self) -> None        # หนึ่งรอบ ครอบคลุมทุกซีรีย์ที่ RUNNING; เรียกจาก test ได้โดยตรง
```

`tick` for each `RUNNING` series, in order (spec 5.4; casting is Task 5 and runs before step 1):

1. Current episode = first not `DONE`. None → `story_complete` ? status `DONE` (event `"series DONE"`) : nothing.
2. Current scene = first not `DONE`.
3. Scene without `job_id` → set episode `RUNNING`, resolve inputs, `gateway.submit_job(...)`, remember the id in `self._submitted`, scene `QUEUED`, `started_at = clock()`.
   - `text`: no extra inputs.
   - `ref`: for each character in order, each `RefImage`: reuse `comfy_name` when `comfy_base_url == gateway.comfy_base_url()` and `gateway.comfy_input_exists(name)` is not `False`; otherwise `push_image` and store the name and base URL. Pass the names as `reference_names`.
   - `chain`: previous scene = the one before it, or the last scene of the previous episode. Use its `last_frame_path`; if that file does not exist, `gateway.extract_frame(prev.video_path, f"frames/{prev.job_id}_last.jpg", "last", 0)`. Push it every time and pass the name as `first_frame_name`.
4. Scene with `job_id` → `gateway.get_job`:
   - `PENDING` → nothing. `RUNNING` → scene `RUNNING`, copy `progress` (in memory, no save).
   - `DONE` → `video_path`, `thumbnail_path` from the job, `last_frame_path = f"frames/{job_id}_last.jpg"`, `progress=100`, `finished_at`, status `DONE`, event `"EP01 scene 2 DONE"`.
   - `FAILED` → `attempts += 1`. Below `max_attempts`: clear `job_id`, status `PENDING` (resubmitted next tick). Otherwise scene `FAILED` with the job error, series `PAUSED` / `error`, `pause_message` naming episode, scene and error, event `"EP01 scene 2 FAILED: <error>"`.
   - `CANCELLED` → clear `job_id`, scene `PENDING`, series `PAUSED` / `user`.
   - `None` → `find_output_video(job_id)` found: treat as `DONE` (thumbnail `thumbnails/{job_id}.jpg` if it exists). Not found and id in `self._submitted`: clear `job_id`, scene `PENDING`, series `PAUSED` / `user`. Not found and not in `self._submitted`: clear `job_id`, scene `PENDING`, attempts unchanged.
5. Every scene `DONE` → for any scene whose `video_path` no longer exists, reset it with the same rule as `SeriesService.update_scene(regenerate=True)` and stop this pass. Otherwise merge: one scene → `final_video_path` / `thumbnail_path` are that scene's. More → `gateway.concat(paths, f"videos/series_{id}_ep{NN}_{6hex}.mp4")` then `make_thumbnail(..., f"thumbnails/<same stem>.jpg")`. Concat not ok → series `PAUSED` / `error` with the concat error, episode untouched. Ok → episode `DONE`, `duration`, `write_manifest`, event `"EP01 DONE"`; `run_mode == "review"` → series `PAUSED` / `review`.

One state change per series per tick is enough; tests call `tick` repeatedly. Hold `store.lock` while reading and mutating a series; call `gateway.concat` outside it. Save with an event for every status change; plain progress updates are not saved.

To share the reset rule with the service, move it into a module-level function in `series_service.py`: `reset_scene(series: Series, gateway: StudioGateway, episode_number: int, scene_index: int) -> list[tuple[int, int]]`, used by both.

- [ ] **Step 1: Add fixtures** to `conftest.py`: `runner(store, gateway) -> SeriesRunner` and `running(service) -> Series`: created through the service, character `mali` with one image, the two default episodes written, started.

Helper in the test module:

```python
def drive(runner, gateway, max_ticks=300):
    """tick จนซีรีย์นิ่ง: งานค้างในคิวปลอมถูกทำให้ DONE ทีละงาน จบเมื่อ tick 5 รอบติดไม่มีงานค้าง"""
    idle = 0
    for _ in range(max_ticks):
        runner.tick()
        open_jobs = [j for j, v in gateway.jobs.items() if v["status"] in ("PENDING", "RUNNING")]
        if open_jobs:
            idle = 0; gateway.finish(open_jobs[0])
        else:
            idle += 1
            if idle >= 5: return
```

- [ ] **Step 2: Write failing tests**

```python
def test_text_scene_submits_t2v(runner, gateway, running, store):
    runner.tick()
    job = dict(gateway.submitted[0]); job_id = job.pop("job_id")
    assert job == {"prompt": running.episodes[0].scenes[0].prompt, "job_type": "T2V", "megapixels": 0.35,
                   "aspect_ratio": "9:16 (Portrait Widescreen)", "duration_seconds": 5, "seed": -1,
                   "reference_names": None, "first_frame_name": None}
    sc = store.get(running.id).episodes[0].scenes[0]
    assert (sc.status, sc.job_id) == ("QUEUED", job_id)

def test_one_job_in_flight(runner, gateway, running):
    runner.tick(); runner.tick(); runner.tick()
    assert len(gateway.submitted) == 1

def test_progress_is_mirrored(runner, gateway, running, store):
    runner.tick(); gateway.set_running("job-1", 43); runner.tick()
    sc = store.get(running.id).episodes[0].scenes[0]
    assert (sc.status, sc.progress) == ("RUNNING", 43)

def test_done_job_records_results(runner, gateway, running, store):
    runner.tick(); gateway.finish("job-1"); runner.tick()
    sc = store.get(running.id).episodes[0].scenes[0]
    assert (sc.status, sc.video_path, sc.last_frame_path, sc.thumbnail_path) == \
           ("DONE", "videos/job-1.mp4", "frames/job-1_last.jpg", "thumbnails/job-1.jpg")
    assert sc.finished_at is not None

def test_ref_scene_uses_character_images(runner, gateway, running):
    runner.tick(); gateway.finish("job-1"); runner.tick(); runner.tick()
    job = gateway.submitted[1]
    assert job["job_type"] == "REF2VA" and job["reference_names"] == ["in_1.jpg"]
    assert gateway.pushed == [f"series/{running.id}/refs/mali_1.jpg"]

def test_chain_scene_uses_previous_last_frame(runner, gateway, running):
    for _ in range(2): runner.tick(); gateway.finish(f"job-{len(gateway.submitted)}"); runner.tick()
    runner.tick()
    job = gateway.submitted[2]
    assert job["job_type"] == "FL2VA" and gateway.pushed[-1] == "frames/job-2_last.jpg"
    assert job["first_frame_name"] == "in_2.jpg"

def test_chain_extracts_missing_last_frame(runner, gateway, running, outputs):
    for _ in range(2): runner.tick(); gateway.finish(f"job-{len(gateway.submitted)}"); runner.tick()
    (outputs / "frames" / "job-2_last.jpg").unlink()
    runner.tick()
    assert gateway.extract_calls == [("videos/job-2.mp4", "frames/job-2_last.jpg", "last", 0)]

def test_chain_across_episodes(runner, gateway, running):
    drive(runner, gateway)
    ep2_first = gateway.submitted[3]
    assert ep2_first["job_type"] == "FL2VA" and gateway.pushed[-1] == "frames/job-3_last.jpg"

def test_low_vram_job_types(service, runner, gateway, tmp_path):
    s = service.create_series("x", low_vram=True)
    service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}]); service.control(s.id, "start")
    runner.tick()
    assert gateway.submitted[0]["job_type"] == "T2V_LOW"

def test_ref_image_pushed_once_then_again_when_comfy_changes(service, runner, gateway, tmp_path):
    img = tmp_path / "a.jpg"; img.write_bytes(b"a")
    s = service.create_series("x"); service.set_character(s.id, "mali", image_paths=[str(img)])
    ref = {"prompt": "p", "mode": "ref", "characters": ["mali"]}
    service.write_episode(s.id, "one", [ref, ref, ref, ref]); service.control(s.id, "start")
    runner.tick(); gateway.finish("job-1"); runner.tick(); runner.tick()
    assert len(gateway.pushed) == 1                                   # cache ใช้ได้
    gateway.base_url = "https://pod-8188.proxy.runpod.net"
    gateway.finish("job-2"); runner.tick(); runner.tick()
    assert len(gateway.pushed) == 2                                   # URL เปลี่ยน
    gateway.input_names.clear()
    gateway.finish("job-3"); runner.tick(); runner.tick()
    assert len(gateway.pushed) == 3                                   # ไฟล์หายจาก input

def test_failed_job_retries_then_pauses(runner, gateway, running, store):
    runner.tick(); gateway.finish("job-1", "FAILED", "CUDA out of memory"); runner.tick(); runner.tick()
    assert len(gateway.submitted) == 2 and store.get(running.id).status == "RUNNING"
    gateway.finish("job-2", "FAILED", "CUDA out of memory"); runner.tick(); runner.tick()
    s = store.get(running.id)
    assert (s.status, s.pause_reason, s.episodes[0].scenes[0].status) == ("PAUSED", "error", "FAILED")
    assert "CUDA out of memory" in s.pause_message and len(gateway.submitted) == 2

def test_cancelled_job_pauses_without_retry(runner, gateway, running, store):
    runner.tick(); gateway.finish("job-1", "CANCELLED"); runner.tick(); runner.tick()
    s = store.get(running.id)
    assert (s.status, s.pause_reason) == ("PAUSED", "user") and len(gateway.submitted) == 1

def test_missing_job_with_output_file_is_done(runner, gateway, running, store):
    runner.tick(); gateway.finish("job-1"); gateway.forget("job-1"); runner.tick()
    assert store.get(running.id).episodes[0].scenes[0].status == "DONE"

def test_missing_job_deleted_by_user_pauses(runner, gateway, running, store):
    runner.tick(); gateway.forget("job-1"); runner.tick()
    s = store.get(running.id)
    assert (s.status, s.pause_reason) == ("PAUSED", "user")

def test_missing_job_after_restart_is_resubmitted(store, gateway, running):
    SeriesRunner(store, gateway).tick(); gateway.forget("job-1")
    fresh = SeriesRunner(store, gateway); fresh.tick(); fresh.tick()
    sc = store.get(running.id).episodes[0].scenes[0]
    assert len(gateway.submitted) == 2 and sc.attempts == 0 and store.get(running.id).status == "RUNNING"

def test_episode_is_merged(runner, gateway, running, store, outputs):
    for _ in range(3): runner.tick(); gateway.finish(f"job-{len(gateway.submitted)}"); runner.tick()
    runner.tick()
    ep = store.get(running.id).episodes[0]
    assert gateway.concat_calls[0][0] == ["videos/job-1.mp4", "videos/job-2.mp4", "videos/job-3.mp4"]
    assert ep.status == "DONE" and ep.final_video_path.startswith(f"videos/series_{running.id}_ep01_")
    assert ep.thumbnail_path.startswith("thumbnails/series_") and ep.duration == 10.0
    assert (store.series_dir(running.id) / "manifest.json").is_file()

def test_single_scene_episode_skips_concat(service, runner, gateway, store):
    s = service.create_series("x"); service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    service.control(s.id, "start"); drive(runner, gateway)
    ep = store.get(s.id).episodes[0]
    assert gateway.concat_calls == [] and ep.final_video_path == "videos/job-1.mp4" and ep.status == "DONE"

def test_concat_failure_pauses_once(runner, gateway, running, store):
    gateway.concat_result = {"ok": False, "error": "ไม่พบ ffmpeg"}
    for _ in range(3): runner.tick(); gateway.finish(f"job-{len(gateway.submitted)}"); runner.tick()
    for _ in range(5): runner.tick()
    s = store.get(running.id)
    assert (s.status, s.pause_reason) == ("PAUSED", "error") and "ไม่พบ ffmpeg" in s.pause_message
    assert len(gateway.concat_calls) == 1 and s.episodes[0].status != "DONE"

def test_missing_scene_file_is_regenerated_before_merge(runner, gateway, running, store, outputs):
    for _ in range(3): runner.tick(); gateway.finish(f"job-{len(gateway.submitted)}"); runner.tick()
    (outputs / "videos" / "job-1.mp4").unlink()
    runner.tick(); runner.tick()
    assert gateway.concat_calls == [] and len(gateway.submitted) == 4
    assert store.get(running.id).episodes[0].scenes[0].status == "QUEUED"

def test_review_mode_pauses_after_episode(service, runner, gateway, store):
    s = service.create_series("x", run_mode="review")
    service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    service.write_episode(s.id, "two", [{"prompt": "p", "mode": "text"}])
    service.control(s.id, "start"); drive(runner, gateway)
    live = store.get(s.id)
    assert (live.status, live.pause_reason, [e.status for e in live.episodes]) == \
           ("PAUSED", "review", ["DONE", "PENDING"])

def test_autopilot_runs_to_done_when_story_complete(service, runner, gateway, running, store):
    service.control(running.id, "finish"); drive(runner, gateway); runner.tick()
    assert store.get(running.id).status == "DONE" and len(gateway.submitted) == 5

def test_waits_for_episodes_when_story_not_complete(runner, gateway, running, store):
    drive(runner, gateway); runner.tick()
    s = store.get(running.id)
    assert s.status == "RUNNING" and waiting_for(s) == "episodes"

def test_paused_series_is_not_advanced(service, runner, gateway, running):
    service.control(running.id, "pause"); runner.tick(); runner.tick()
    assert gateway.submitted == []

def test_stale_result_after_regenerate_is_ignored(service, runner, gateway, running, store):
    runner.tick()
    service.update_scene(running.id, 1, 1, prompt="better prompt")
    gateway.finish("job-1")
    runner.tick()
    sc = store.get(running.id).episodes[0].scenes[0]
    assert sc.job_id == "job-2" and sc.video_path is None and gateway.submitted[1]["prompt"] == "better prompt"

def test_runner_resumes_after_restart(store, gateway, running, outputs):
    r1 = SeriesRunner(store, gateway); r1.tick(); gateway.finish("job-1"); r1.tick()
    fresh_store = SeriesStore(outputs / "series"); fresh_store.load_all()
    r2 = SeriesRunner(fresh_store, gateway); r2.tick()
    assert len(gateway.submitted) == 2 and fresh_store.get(running.id).episodes[0].scenes[1].status == "QUEUED"

def test_events_are_emitted(runner, gateway, running, store):
    c = store.cursor(running.id)
    runner.tick(); gateway.finish("job-1"); runner.tick()
    _, events = store.wait_events(running.id, c, timeout=0.1)
    assert "EP01 scene 1 DONE" in events
```

- [ ] **Step 3: Run** `venv\Scripts\python.exe -m pytest tests/test_series_runner.py -v` → FAIL.
- [ ] **Step 4: Implement `series_runner.py` (`tick` only) and extract `reset_scene`.** Run → PASS. Whole suite → PASS.
- [ ] **Step 5: Commit** `feat(series): runner state machine for scenes and episode merge`

---

### Task 5: Runner — auto-casting and background thread

**Files:**
- Modify: `backend/app/services/series_runner.py`
- Test: `backend/tests/test_series_casting.py`

**Interfaces:**
- Consumes: Task 4 runner; `needs_casting`, `CASTING_DURATION_SECONDS`, `slugify`.
- Produces:

```python
class SeriesRunner:
    def start(self) -> None     # thread "h3-series-runner", daemon; เรียกซ้ำได้
    def stop(self) -> None      # ตั้ง stop event แล้ว join จน thread จบ
```

Casting runs at the top of a series' tick, before step 1 of Task 4 (spec 5.2):

- First character with `needs_casting` and no `casting_job_id` → `submit_job(prompt=casting_prompt, job_type=job_type_for("text", low_vram), duration_seconds=5, seed=-1, megapixels/aspect from the series)`, store `casting_job_id`. Nothing else happens for this series this tick.
- With `casting_job_id`: `DONE` (or missing from the queue but `find_output_video` finds it) → `gateway.extract_frame(video, f"series/<id>/refs/<stem>_cast.jpg", "last", 3)` (`<stem>` as in Task 2: slug, or `char<k>`), set `reference_images=[RefImage(path=...)]`, clear `casting_job_id`, event `"character <name> cast"`. `FAILED` → `casting_attempts += 1`, clear `casting_job_id`; at `max_attempts` → series `PAUSED` / `error`. `CANCELLED`, or missing and submitted by this process → clear and series `PAUSED` / `user`. Missing after restart → clear (resubmitted).
- When a cast completes and no character still needs casting → series `PAUSED` / `casting`, `pause_message` listing the cast character names. This happens in every `run_mode`.

The thread loop calls `tick()` every `tick_seconds` and swallows-and-prints exceptions from a tick (`traceback.print_exc()`) so one bad series cannot kill the loop. `stop()` must not return while a tick is still running.

- [ ] **Step 1: Write failing tests**

```python
@pytest.fixture
def casting(service):
    s = service.create_series("x")
    service.set_character(s.id, "Mali", casting_prompt="a young woman, front view, plain wall")
    service.write_episode(s.id, "one", [{"prompt": "p", "mode": "ref", "characters": ["Mali"]}])
    return service.control(s.id, "start")

def test_casting_job_runs_before_scenes(runner, gateway, casting):
    runner.tick(); runner.tick()
    job = dict(gateway.submitted[0]); job.pop("job_id")
    assert len(gateway.submitted) == 1
    assert job == {"prompt": "a young woman, front view, plain wall", "job_type": "T2V", "megapixels": 0.35,
                   "aspect_ratio": "9:16 (Portrait Widescreen)", "duration_seconds": 5, "seed": -1,
                   "reference_names": None, "first_frame_name": None}

def test_cast_done_sets_reference_and_pauses_for_review(runner, gateway, casting, store, outputs):
    runner.tick(); gateway.finish("job-1"); runner.tick()
    s = store.get(casting.id); ref = s.characters[0].reference_images[0].path
    assert ref == f"series/{casting.id}/refs/mali_cast.jpg" and (outputs / ref).is_file()
    assert gateway.extract_calls == [("videos/job-1.mp4", ref, "last", 3)]
    assert (s.status, s.pause_reason) == ("PAUSED", "casting") and "Mali" in s.pause_message

def test_resume_after_casting_starts_scenes(service, runner, gateway, casting):
    runner.tick(); gateway.finish("job-1"); runner.tick()
    service.control(casting.id, "resume"); runner.tick()
    assert gateway.submitted[1]["job_type"] == "REF2VA"
    assert gateway.pushed == [f"series/{casting.id}/refs/mali_cast.jpg"]

def test_casting_failure_pauses_after_max_attempts(runner, gateway, casting, store):
    runner.tick(); gateway.finish("job-1", "FAILED", "boom"); runner.tick(); runner.tick()
    gateway.finish("job-2", "FAILED", "boom"); runner.tick(); runner.tick()
    s = store.get(casting.id)
    assert (s.status, s.pause_reason) == ("PAUSED", "error") and len(gateway.submitted) == 2

def test_all_characters_cast_before_pause(service, runner, gateway, store):
    s = service.create_series("x")
    service.set_character(s.id, "A", casting_prompt="a"); service.set_character(s.id, "B", casting_prompt="b")
    service.write_episode(s.id, "one", [{"prompt": "p", "mode": "ref", "characters": ["A", "B"]}])
    service.control(s.id, "start")
    runner.tick(); gateway.finish("job-1"); runner.tick()
    assert store.get(s.id).status == "RUNNING"
    runner.tick(); gateway.finish("job-2"); runner.tick()
    assert store.get(s.id).pause_reason == "casting"

def test_recast_runs_again_and_keeps_done_scenes(service, runner, gateway, casting, store):
    runner.tick(); gateway.finish("job-1"); runner.tick()
    service.control(casting.id, "resume"); runner.tick(); gateway.finish("job-2"); runner.tick(); runner.tick()
    service.set_character(casting.id, "Mali", casting_prompt="older woman")
    service.write_episode(casting.id, "two", [{"prompt": "p", "mode": "ref", "characters": ["Mali"]}])
    runner.tick()
    assert gateway.submitted[-1]["prompt"] == "older woman"
    assert store.get(casting.id).episodes[0].scenes[0].status == "DONE"

def test_thai_named_characters_get_separate_files(service, runner, gateway, store, outputs):
    s = service.create_series("x")
    service.set_character(s.id, "มะลิ", casting_prompt="a"); service.set_character(s.id, "ก้อง", casting_prompt="b")
    service.write_episode(s.id, "one", [{"prompt": "p", "mode": "ref", "characters": ["มะลิ", "ก้อง"]}])
    service.control(s.id, "start")
    runner.tick(); gateway.finish("job-1"); runner.tick(); runner.tick(); gateway.finish("job-2"); runner.tick()
    paths = [c.reference_images[0].path for c in store.get(s.id).characters]
    assert paths == [f"series/{s.id}/refs/char1_cast.jpg", f"series/{s.id}/refs/char2_cast.jpg"]
    assert all((outputs / p).is_file() for p in paths)

def test_thread_start_stop(store, gateway, running):
    r = SeriesRunner(store, gateway, tick_seconds=0.01)
    r.start(); r.start()
    deadline = time.monotonic() + 2
    while not gateway.submitted and time.monotonic() < deadline: time.sleep(0.01)
    r.stop()
    assert gateway.submitted and not any(t.name == "h3-series-runner" and t.is_alive() for t in threading.enumerate())

def test_tick_exception_does_not_kill_thread(store, gateway, running, monkeypatch):
    r = SeriesRunner(store, gateway, tick_seconds=0.01); calls = []
    def boom(): calls.append(1); raise RuntimeError("x")
    monkeypatch.setattr(r, "tick", boom)
    r.start(); time.sleep(0.2); r.stop()
    assert len(calls) > 1
```

- [ ] **Step 2: Run** `venv\Scripts\python.exe -m pytest tests/test_series_casting.py -v` → FAIL.
- [ ] **Step 3: Implement casting and the thread.** Run → PASS. Whole suite → PASS.
- [ ] **Step 4: Commit** `feat(series): auto-casting with review pause and runner thread`

---

### Task 6: Real gateway, wiring, REST

**Files:**
- Create: `backend/app/services/series_runtime.py`, `backend/app/routers/series.py`
- Modify: `backend/app/core/config.py` (add `MCP_ALLOW_LAN` next to the other `_get` values), `backend/config.example.json` (add `"mcp_allow_lan": false`), `backend/app/main.py`
- Test: `backend/tests/test_real_gateway.py`, `backend/tests/test_series_api.py`

**Interfaces:**
- Consumes: all previous tasks; existing `queue_service` (`create_job`, `get_job`, `cancel_job`, `list_jobs`), `media_processor` (`extract_frame`, `concat_videos`, `process_video_outputs`, `extract_video_frames`), `prompt_enhance_service.push_image_to_comfyui(path: Path) -> str`, `comfyui_client.get_system_stats()`, `config`.
- Produces (`series_runtime.py`):

```python
class RealGateway:                      # implements StudioGateway
    def __init__(self, queue=queue_service, outputs_dir: Path | None = None)   # None → config.OUTPUTS_DIR at call time
series_store: SeriesStore               # SeriesStore(config.OUTPUTS_DIR / "series")
series_gateway: RealGateway
series_service: SeriesService
series_runner: SeriesRunner
```

- Produces (`routers/series.py`): `router`, and `get_service() -> SeriesService` used as a FastAPI dependency so tests can override it.

| Method | Path | Response |
|---|---|---|
| GET | `/api/series/` | `service.overview()` |
| GET | `/api/series/{series_id}` | `service.detail(series_id)` |
| POST | `/api/series/{series_id}/control` | body `{"action": "pause" \| "resume" \| "cancel"}` → `service.detail(series_id)` |

Unknown series → 404. Other `SeriesError` → 400 with the message as `detail`. Any other action value → 422.

`RealGateway` notes: `submit_job` calls `queue.create_job(prompt=..., type_=job_type, resolution=f"{megapixels} MP", steps=6, seed=..., duration_seconds=..., aspect_ratio=..., reference_names=..., first_frame_name=...)` and returns the snapshot's `id`. `find_output_video` globs `videos/{job_id}.*`. `comfy_input_exists` returns `None` when `config.COMFYUI_IS_REMOTE`, else whether the file is in `config.COMFYUI_INPUT_DIR`. `sample_frames` must return images whose longer edge is at most `max_edge` (how is the implementer's choice; the spec leaves it open). `studio_info` must not raise when ComfyUI is down: `comfyui_ok=False`.

`main.py` lifespan order — startup: create output dirs, `series_store.load_all()`, `queue_service.start_worker()`, `series_runner.start()`. Shutdown: `series_runner.stop()` **before** `queue_service.stop_worker()` (the queue marks the running job `CANCELLED` on stop; the runner must not see that). Register the router at prefix `/api/series`.

- [ ] **Step 1: Write failing tests**

```python
# test_real_gateway.py
class StubQueue:
    def __init__(self): self.created = []
    def create_job(self, **kw): self.created.append(kw); return {"id": "abc"}
    def get_job(self, job_id): return None
    def cancel_job(self, job_id): return None

def test_submit_job_maps_to_queue_arguments(outputs):
    q = StubQueue(); g = RealGateway(queue=q, outputs_dir=outputs)
    assert g.submit_job(prompt="p", job_type="FL2VA", megapixels=0.35,
                        aspect_ratio="9:16 (Portrait Widescreen)", duration_seconds=8, seed=-1,
                        first_frame_name="in.jpg") == "abc"
    kw = q.created[0]
    assert (kw["type_"], kw["resolution"], kw["duration_seconds"], kw["aspect_ratio"], kw["first_frame_name"]) == \
           ("FL2VA", "0.35 MP", 8, "9:16 (Portrait Widescreen)", "in.jpg")

def test_megapixel_string_parses_back(outputs):
    from app.services.h3_service import _megapixels_for_resolution
    assert _megapixels_for_resolution("0.35 MP") == 0.35

def test_find_output_video(outputs):
    g = RealGateway(queue=StubQueue(), outputs_dir=outputs)
    assert g.find_output_video("j1") is None
    (outputs / "videos" / "j1.mp4").write_bytes(b"v")
    assert g.find_output_video("j1") == "videos/j1.mp4" and g.output_exists("videos/j1.mp4")

def test_studio_info_survives_comfyui_down(outputs, monkeypatch):
    from app.services import comfyui_client
    monkeypatch.setattr(comfyui_client, "get_system_stats", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    assert RealGateway(queue=StubQueue(), outputs_dir=outputs).studio_info()["comfyui_ok"] is False

# test_series_api.py
@pytest.fixture
def client(service):
    app = FastAPI(); app.include_router(series_router.router, prefix="/api/series")
    app.dependency_overrides[series_router.get_service] = lambda: service
    return TestClient(app)

def test_list_and_detail(client, done_series):
    rows = client.get("/api/series/").json()
    assert rows[0]["id"] == done_series.id and rows[0]["episodes_done"] == 2
    d = client.get(f"/api/series/{done_series.id}").json()
    assert d["episodes"][0]["scenes"][0]["prompt"] and d["progress"]["scenes_total"] == 5

def test_unknown_series_is_404(client):
    assert client.get("/api/series/nope").status_code == 404

def test_control(client, running):
    r = client.post(f"/api/series/{running.id}/control", json={"action": "pause"})
    assert r.status_code == 200 and r.json()["status"] == "PAUSED"
    assert client.post(f"/api/series/{running.id}/control", json={"action": "pause"}).status_code == 400
    assert client.post(f"/api/series/{running.id}/control", json={"action": "start"}).status_code == 422

def test_app_lifespan_starts_and_stops_runner(monkeypatch):
    from app.main import app
    from app.services import series_runtime
    # แอปจริงชี้ outputs/ จริง: ปิด tick กันไม่ให้ test ส่งงานของซีรีย์จริงเข้า GPU
    monkeypatch.setattr(series_runtime.series_runner, "tick", lambda: None)
    with TestClient(app) as c:
        assert c.get("/api/series/").status_code == 200
        assert any(t.name == "h3-series-runner" and t.is_alive() for t in threading.enumerate())
    assert not any(t.name == "h3-series-runner" and t.is_alive() for t in threading.enumerate())
```

- [ ] **Step 2: Run** `venv\Scripts\python.exe -m pytest tests/test_real_gateway.py tests/test_series_api.py -v` → FAIL.
- [ ] **Step 3: Implement.** Run → PASS. Whole suite → PASS.
- [ ] **Step 4: Check the existing API still works** — `venv\Scripts\python.exe -c "from app.main import app; print(sorted(r.path for r in app.routes if r.path.startswith('/api/generations')))"` lists the six generation routes unchanged.
- [ ] **Step 5: Commit** `feat(series): real gateway, lifespan wiring and REST`

---

### Task 7: MCP server

**Files:**
- Create: `backend/app/services/series_guide.py`, `backend/app/mcp_server.py`, `.mcp.json`
- Modify: `backend/requirements.txt` (add `mcp>=2.3,<3`), `backend/app/main.py`, `README.md`
- Test: `backend/tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `SeriesService`, `SeriesStore`, `StudioGateway`, `export_series`, `review_images`, `progress_of`, `config.MCP_ALLOW_LAN`, `config.OUTPUTS_DIR`.
- Produces:

```python
# series_guide.py
SERIES_GUIDE: str
def new_series_prompt(idea: str) -> str

# mcp_server.py
def build_mcp(service: SeriesService, store: SeriesStore, gateway: StudioGateway, outputs_dir: Path) -> MCPServer
def mcp_asgi_app(server: MCPServer, allow_lan: bool) -> ASGIApp     # streamable HTTP at path "/mcp", loopback guard applied
```

`mcp` 2.3 API (verified from the wheel; re-check against the installed package): `from mcp.server.mcpserver import MCPServer, Image`; tools via `@server.tool()`, prompts via `@server.prompt()`; `server.streamable_http_app(streamable_http_path="/mcp", json_response=True, stateless_http=True, transport_security=..., host=...)` returns a Starlette app; `server.session_manager.run()` is an async context manager that must be entered in the FastAPI lifespan, and `session_manager` exists only after `streamable_http_app()` was called. `mcp.server.fastmcp` no longer exists. `TransportSecuritySettings` lives in `mcp.server.transport_security`.

Mounting: build the app once at import of `main.py`, enter `server.session_manager.run()` inside the existing lifespan, and `app.mount("/", mcp_asgi_app(...))` as the **last** route so every existing route keeps priority and `/mcp` needs no trailing-slash redirect.

Loopback guard: a plain ASGI wrapper. For `http` scopes, when `allow_lan` is false and `scope["client"][0]` is not `127.0.0.1` or `::1`, respond 403 with JSON `{"detail": "MCP รับเฉพาะการเชื่อมต่อจากเครื่องนี้ (ตั้ง mcp_allow_lan เพื่อเปิด)"}`. When `allow_lan` is true, also pass transport security that does not reject LAN `Host` headers.

Tools (name = function name; all return `str` except `series_review`):

```python
def studio_status() -> str
def series_guide() -> str
def series_create(title: str, logline: str = "", style_notes: str = "",
                  aspect_ratio: str = "9:16 (Portrait Widescreen)", megapixels: float = 0.35,
                  low_vram: bool = False, run_mode: str = "autopilot") -> str
def series_add_character(series_id: str, name: str, description: str = "",
                         image_paths: list[str] | None = None, casting_prompt: str | None = None) -> str
def series_write_episode(series_id: str, title: str, scenes: list[dict], synopsis: str = "",
                         caption: str = "", hashtags: list[str] | None = None,
                         episode_number: int | None = None) -> str
def series_update_scene(series_id: str, episode: int, scene: int, prompt: str | None = None,
                        beat: str | None = None, mode: str | None = None, characters: list[str] | None = None,
                        duration_seconds: int | None = None, seed: int | None = None,
                        regenerate: bool = False) -> str
def series_control(series_id: str, action: str) -> str
def series_status(series_id: str | None = None) -> str
async def series_wait(series_id: str, timeout_seconds: int = 120, after_event: int = -1) -> str
def series_review(series_id: str, episode: int | None = None, scene: int | None = None,
                  character: str | None = None, frames: int = 4) -> list     # [str, Image, Image, ...]
def series_export(series_id: str) -> str
```

- Each tool's docstring is its description for Claude: one or two English sentences saying when to call it, plus the allowed values for constrained parameters (durations, megapixels, modes, actions). `series_write_episode` documents the scene dict keys.
- A `SeriesError` is returned as the tool's text prefixed `ERROR: ` (not raised), so Claude can read it and fix its call.
- `studio_status`: ComfyUI reachable / mode / VRAM, queue counts, the allowed durations, megapixels and aspect ratios, and one line per series from `service.overview()`.
- `series_status` without id = overview lines. With id: a compact block — status line (with pause reason/message and `waiting_for`), one line per episode (`EP01 DONE 1:12 "title"`), one line per scene not `DONE` in the current episode (index, mode, status, progress, attempts, error), character lines (has reference / needs casting), `progress_of` with the ETA in minutes, and `event_cursor`.
- `series_wait`: `timeout_seconds` clamped to 5–300. `after_event=-1` means "from now". Runs `store.wait_events` in a worker thread (`anyio.to_thread.run_sync`), then returns the events followed by the same block as `series_status`.
- `series_review`: `review_images(...)` → `[text, *[Image(path=outputs_dir / p) for p in paths]]`.
- Prompt: `@server.prompt() def new_series(idea: str) -> str` returning `new_series_prompt(idea)`.
- Server `instructions`: two sentences — what the server is, and "call `series_guide` before writing a series".

`SERIES_GUIDE` (English, ≤ 80 lines) must cover every bullet of spec 5.7, and state: the three modes with when to use each; re-anchor with `ref` every 2–3 `chain` scenes; `chain` prompts start with `continuing the same motion, `; the three-field prompt layout (`integrated_multimodal_description` / `overall_soundscape` / `non_diegetic_music`); `<Picture N>` numbering in `ref` scenes; repeat the same physical description of each character in every scene; 60–120 s per episode (6–12 scenes), hook in the first 3 seconds, cliffhanger ending, subject centered for 9:16; the megapixels-vs-VRAM table from README 1.1; casting always pauses for review — look at the cast with `series_review(character=...)` before resuming; Claude cannot hear audio, so ask the user to check dialogue and lip-sync on the `/series` page.

`new_series_prompt(idea)` lists the order: `series_guide` → `studio_status` → outline (logline, characters, episode list) and show it to the user → `series_create` → `series_add_character` → `series_write_episode` for each episode → `series_control start` → `series_wait` / `series_review` loop, regenerating bad scenes → `series_control finish` → `series_export`.

`.mcp.json`:

```json
{
  "mcpServers": {
    "h3-studio": { "type": "http", "url": "http://127.0.0.1:8000/mcp" }
  }
}
```

README: add a section `### 🤖 สร้างซีรีย์ด้วย Claude Code (MCP)` under section 4 — backend must be running before Claude Code starts; the server is registered by `.mcp.json`; type `/mcp` in Claude Code to check; start with the `new_series` prompt; where files land (`outputs/series/<id>/`); `mcp_allow_lan`; the tool table from spec 5.6. Add `mcp_allow_lan` to the config notes.

- [ ] **Step 1: Install** — add the requirement line, `venv\Scripts\python.exe -m pip install -r requirements.txt`, then `venv\Scripts\python.exe -m pytest` → existing suite still PASS (FastAPI/Starlette/Pydantic versions unchanged: `pip list` shows fastapi 0.115.x).
- [ ] **Step 2: Write failing tests**

```python
EXPECTED_TOOLS = {"studio_status", "series_guide", "series_create", "series_add_character",
                  "series_write_episode", "series_update_scene", "series_control", "series_status",
                  "series_wait", "series_review", "series_export"}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}

def make_client(service, store, gateway, outputs, allow_lan=False, client=("127.0.0.1", 50000)):
    server = build_mcp(service, store, gateway, outputs)
    asgi = mcp_asgi_app(server, allow_lan=allow_lan)
    @asynccontextmanager
    async def lifespan(app):
        async with server.session_manager.run(): yield
    app = FastAPI(lifespan=lifespan)
    @app.get("/")
    def root(): return {"ok": True}
    app.mount("/", asgi)
    return TestClient(app, client=client)

def rpc(c, method, params=None, id_=1):
    r = c.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})
    assert r.status_code == 200, r.text
    return r.json()["result"]

def call(c, name, **arguments):
    return rpc(c, "tools/call", {"name": name, "arguments": arguments})

@pytest.fixture
def mcp(service, store, gateway, outputs):
    with make_client(service, store, gateway, outputs) as c:
        rpc(c, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "pytest", "version": "0"}})
        yield c

def test_tools_and_prompt_are_listed(mcp):
    assert {t["name"] for t in rpc(mcp, "tools/list")["tools"]} == EXPECTED_TOOLS
    assert [p["name"] for p in rpc(mcp, "prompts/list")["prompts"]] == ["new_series"]

def test_existing_routes_keep_priority(mcp):
    assert mcp.get("/").json() == {"ok": True}

def test_create_write_start_status_roundtrip(mcp, store):
    text = call(mcp, "series_create", title="Love Story")["content"][0]["text"]
    series_id = store.list()[0].id
    assert series_id in text
    call(mcp, "series_write_episode", series_id=series_id, title="one",
         scenes=[{"prompt": "a street at night", "mode": "text", "duration_seconds": 8}])
    call(mcp, "series_control", series_id=series_id, action="start")
    status = call(mcp, "series_status", series_id=series_id)["content"][0]["text"]
    assert "RUNNING" in status and "event_cursor" in status

def test_series_error_is_returned_as_text(mcp):
    out = call(mcp, "series_status", series_id="nope")
    assert out["content"][0]["text"].startswith("ERROR: ")

def test_review_returns_images(mcp, done_series):
    content = call(mcp, "series_review", series_id=done_series.id, episode=1, scene=1, frames=2)["content"]
    assert [c["type"] for c in content] == ["text", "image", "image"]

def test_wait_returns_at_timeout_with_status(mcp, running):
    t = time.monotonic()
    text = call(mcp, "series_wait", series_id=running.id, timeout_seconds=5)["content"][0]["text"]
    assert time.monotonic() - t < 15 and running.id in text

def test_guide_and_prompt_have_the_essentials():
    for needle in ("continuing the same motion, ", "integrated_multimodal_description", "<Picture",
                   "cliffhanger", "9:16", "series_review"):
        assert needle in SERIES_GUIDE
    assert "time-travel romance" in new_series_prompt("time-travel romance")

def test_non_loopback_client_is_rejected(service, store, gateway, outputs):
    with make_client(service, store, gateway, outputs, client=("192.168.1.50", 50000)) as c:
        r = c.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 403

def test_lan_client_allowed_when_enabled(service, store, gateway, outputs):
    with make_client(service, store, gateway, outputs, allow_lan=True, client=("192.168.1.50", 50000)) as c:
        r = c.post("/mcp", headers={**HEADERS, "Host": "192.168.1.5:8000"},
                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 200
```

If the installed `mcp` needs a different request shape for stateless JSON mode (protocol-version header, `notifications/initialized`), adjust `rpc` / the `mcp` fixture only — the assertions stand.

- [ ] **Step 3: Run** `venv\Scripts\python.exe -m pytest tests/test_mcp_server.py -v` → FAIL.
- [ ] **Step 4: Implement `series_guide.py`, `mcp_server.py`, the `main.py` mount, `.mcp.json`, README.** Run → PASS. Whole suite → PASS.
- [ ] **Step 5: Live check** — start the backend (`venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000`), then:

```bash
curl -s -X POST http://127.0.0.1:8000/mcp -H "Accept: application/json, text/event-stream" -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Expected: JSON listing the 11 tools. `curl -s http://127.0.0.1:8000/api/system/health` still returns the health JSON. Stop the backend.

- [ ] **Step 6: Commit** `feat(series): MCP server with series tools, guide and new_series prompt`

---

### Task 8: Web page `/series`

**Files:**
- Modify: `lib/backend.ts` (append a "Series API" block), `components/layout/sidebar.tsx` (add `{ href: '/series', label: 'ซีรีย์', icon: Tv }` after `/shortfilm`)
- Create: `components/series/series-view.tsx`, `app/(studio)/series/page.tsx`

**Interfaces:**
- Consumes: REST from Task 6; existing `apiFetch`, `getMediaUrl`, `getFrameUrl`, shadcn `Card` / `Button` / `Badge` / `Progress`, `sonner` toast.
- Produces (`lib/backend.ts`):

```ts
export type SeriesStatus = 'DRAFT' | 'RUNNING' | 'PAUSED' | 'DONE' | 'CANCELLED'
export type SceneStatus = 'PENDING' | 'QUEUED' | 'RUNNING' | 'DONE' | 'FAILED'
export interface SeriesProgress { scenes_done: number; scenes_total: number; avg_scene_seconds: number | null; eta_seconds: number | null }
export interface SeriesOverview { id: string; title: string; status: SeriesStatus; pause_reason: string | null; waiting_for: string | null; episodes_done: number; episodes_total: number; progress: SeriesProgress }
export interface SeriesScene { index: number; prompt: string; beat: string; mode: 'text' | 'ref' | 'chain'; characters: string[]; duration_seconds: number; status: SceneStatus; progress: number; attempts: number; error: string | null; video_path: string | null; thumbnail_path: string | null; last_frame_path: string | null }
export interface SeriesEpisode { number: number; title: string; synopsis: string; caption: string; hashtags: string[]; status: 'PENDING' | 'RUNNING' | 'DONE'; scenes: SeriesScene[]; final_video_path: string | null; thumbnail_path: string | null; duration: number | null }
export interface SeriesDetail extends Omit<SeriesOverview, 'episodes_done' | 'episodes_total'> { logline: string; run_mode: string; pause_message: string | null; story_complete: boolean; episodes: SeriesEpisode[] }
export async function fetchSeriesList(): Promise<SeriesOverview[]>
export async function fetchSeries(id: string): Promise<SeriesDetail>
export async function controlSeries(id: string, action: 'pause' | 'resume' | 'cancel'): Promise<SeriesDetail>
```

Page behavior (spec 5.8; layout sketch there):

- `page.tsx` follows `app/(studio)/media/page.tsx` (padding wrapper, renders `<SeriesView />`).
- `SeriesView` is a client component. It polls `fetchSeriesList()` every 5 s and, for the selected series, `fetchSeries(id)` every 5 s. The first series is selected by default; clicking a row selects it.
- Series row: title, status badge, `ตอน x/y · ฉาก a/b`, and when `eta_seconds` is set `เหลือประมาณ …` formatted as hours/minutes. `PAUSED` shows the reason in Thai (`user` หยุดโดยผู้ใช้, `review` รอตรวจตอน, `casting` รอตรวจตัวละคร, `error` เกิดข้อผิดพลาด) and `pause_message`. `waiting_for === 'episodes'` shows `รอตอนถัดไปจาก Claude Code`.
- Buttons: `หยุดชั่วคราว` when `RUNNING`, `รันต่อ` when `PAUSED`, `ยกเลิกซีรีย์` when `RUNNING`/`PAUSED`/`DRAFT`. Cancel asks for a second click to confirm (the two-step pattern the media gallery uses for delete). Failures show a toast with the error message.
- Episode card: `EP01 <title>`, status, duration `m:ss`. `DONE` → a `<video controls>` in a 9:16 box (`aspect-[9/16]`, max width ~280px) with `poster` from the thumbnail, download link, caption + hashtags with a `คัดลอก` button (copy must work over plain-HTTP LAN: reuse the fallback approach the media gallery's Copy Prompt uses).
- Scene dots under each episode, one per scene, colored by status; the `RUNNING` scene shows `ฉาก n: p%`. Clicking a dot opens a panel for that scene: its clip in a `<video controls>` when `video_path` is set, mode, duration, prompt, beat, and `error` when present.
- Empty state: `ยังไม่มีซีรีย์ — เปิด Claude Code แล้วใช้ prompt new_series ของ h3-studio`.
- Backend unreachable: an inline error with a retry button; polling continues.
- No editing controls. Match the look of `components/projects/project-detail-view.tsx`.

- [ ] **Step 1: Record the baseline** — `npm run lint` and `npx tsc --noEmit`; note the existing error/warning counts.
- [ ] **Step 2: Add the Series API block to `lib/backend.ts`** — use `apiFetch`; `controlSeries` posts JSON.
- [ ] **Step 3: Build `series-view.tsx`, `page.tsx`, and the sidebar entry.**
- [ ] **Step 4: Verify** — `npx tsc --noEmit` and `npm run lint` report no new problems versus the baseline; `npm run build` succeeds and lists `/series`.
- [ ] **Step 5: See it work** — start the backend, create a series with a finished episode so the page has data (run from `backend/`):

```bash
venv\Scripts\python.exe -c "from app.services.series_runtime import series_service as s; x=s.create_series('UI check'); s.write_episode(x.id,'ตอนแรก',[{'prompt':'a street at night','mode':'text'}],caption='ทดสอบ',hashtags=['#test']); print(x.id)"
```

Run `npm run dev`, open `http://localhost:3000/series`: the series row shows `DRAFT`, the episode shows one grey dot, clicking the dot shows the prompt, `ยกเลิกซีรีย์` needs two clicks and then the badge reads `CANCELLED`. Check the page at a 390px-wide viewport: no horizontal scroll. Delete the test folder `outputs/series/ui-check-*` afterwards.

- [ ] **Step 6: Commit** `feat(series): /series monitor page`

---

## Final verification (controller, after all tasks)

- [ ] `cd backend && venv\Scripts\python.exe -m pytest` → all PASS.
- [ ] `npm run lint`, `npx tsc --noEmit`, `npm run build` → no new problems.
- [ ] Backend running → `claude mcp list` shows `h3-studio` connected.
- [ ] With ComfyUI running (ask the owner to start it): through the MCP tools create a series at `megapixels=0.1` with one episode of two 5-second scenes (`text` then `chain`), start it, and confirm: both scenes `DONE`, episode merged, `series_review` returns frames, `series_export` writes `EP01 - ….mp4` + `manifest.json`, and the `/series` page plays the episode and each scene.
- [ ] Restart the backend mid-scene during that run and confirm the series continues on its own.
- [ ] Existing pages still work: `/studio` can queue a clip, `/shortfilm` loads.
