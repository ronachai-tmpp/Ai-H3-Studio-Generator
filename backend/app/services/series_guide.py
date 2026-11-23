"""ข้อความคู่มือสำหรับ Claude (tool `series_guide`) และ prompt `new_series` ของ MCP server"""

from __future__ import annotations

SERIES_GUIDE = """\
H3 Studio series guide (vertical short-drama series, one video model, scenes of 5-15 s)

STRUCTURE
- Vertical series: each episode runs 60-120 s (6-12 scenes, max 20).
- Put a hook in the first 3 seconds and end every episode on a cliffhanger.
- Compose for 9:16: keep the subject centered in the frame.

SCENE MODES (pick one per scene)
- text  (T2V): opening shots, scenery, new location with no main character. Prompt only.
- ref   (REF2VA): a new cut where a main character must look right. Uses the reference
  images of the characters listed in `characters` (max 9 images in total).
- chain (FL2VA): continue the motion of the previous scene without a cut. The first frame
  is the last frame of the previous scene. The first scene of episode 1 cannot be chain.
- Re-anchor identity with a `ref` scene every 2-3 `chain` scenes, or the character drifts.
- In a `ref` scene refer to images as <Picture 1>, <Picture 2> ... in the order of the
  images of the characters in `characters`.

PROMPT LAYOUT (the model generates sound together with the picture)
- Three fields: integrated_multimodal_description (visuals and action, dialogue in quotes),
  overall_soundscape (ambience, effects), non_diegetic_music (score, or "none").
- A chain prompt starts with `continuing the same motion, ` and keeps the same character,
  outfit, lighting and camera as the previous scene.
- Repeat the same physical description of each character in every scene (body, outfit,
  hairstyle). Never rely on the name alone.

LIMITS
- duration_seconds: 5, 8, 10, 12 or 15.
- megapixels: 0.1, 0.25, 0.35, 0.5, 0.75 or 1.0 (default 0.35).
- Megapixels vs VRAM (12 GB card): megapixels cost more VRAM than length. On CUDA out of
  memory lower megapixels first, then length.
    MP    5 s    10 s   15 s
    0.25  ok     ok     ok
    0.35  ok     ok     ok
    0.5   ok     ok     risky (OOM)
    0.75  ok     risky  no
    1.0   risky  no     no
  An 8 GB card handles only 0.1-0.35 MP. low_vram=true selects the GGUF Low VRAM models.
- Max 20 scenes per episode, max 9 reference images per scene.

CHARACTERS AND CASTING
- Give each recurring character a name, a description and either image_paths or a
  casting_prompt. Image paths are files on the backend machine or paths under outputs/.
- A character with only a casting_prompt is cast by the runner (a 5 s clip, then a frame).
  Casting ALWAYS pauses the series for review: look at the cast with
  series_review(series_id, character=NAME) before series_control resume. If the face is
  wrong, call series_add_character again with a better casting_prompt or real images.

WORKFLOW AND REVIEW
- series_create -> series_add_character -> series_write_episode (per episode) ->
  series_control start -> series_wait / series_review loop -> series_control finish ->
  series_export.
- Write episodes ahead, or one at a time: while every episode is done and the story is not
  finished the series waits ("waiting_for: episodes"). Call series_control finish when the
  story is complete.
- Review finished scenes with series_review (episode + scene gives sampled frames, episode
  alone gives the last frame of every scene). If a character drifted or the picture is
  broken, fix the prompt with series_update_scene(..., regenerate=true). Regenerating a
  scene also resets the chain scenes that follow it.
- run_mode "review" pauses after each episode so you can check it before continuing.
- Claude cannot hear audio: ask the user to check dialogue and lip-sync on the /series page
  of the web app.
"""


def new_series_prompt(idea: str) -> str:
    """ข้อความพา Claude ทำซีรีย์ตั้งแต่ไอเดียจนส่งออก (prompt `new_series`)"""
    return f"""\
Make a vertical short-drama series with the h3-studio MCP tools.

Idea: {idea}

Follow this order:
1. Call `series_guide` and read it fully.
2. Call `studio_status` to check ComfyUI, VRAM and the allowed values.
3. Write an outline: logline, characters (with a repeatable physical description) and the
   episode list. Show the outline to the user and wait for their approval.
4. `series_create` (pick megapixels that fit the VRAM).
5. `series_add_character` for each main character (image_paths or casting_prompt).
6. `series_write_episode` for each episode (6-12 scenes, hook, cliffhanger).
7. `series_control` with action "start". If casting pauses the series, check the cast with
   `series_review(character=...)` and then resume.
8. Loop `series_wait` and `series_review`; fix bad scenes with `series_update_scene`
   (regenerate=true).
9. `series_control` with action "finish" when the story is complete.
10. `series_export`, then tell the user where the files are and ask them to check the
    audio and lip-sync on the /series page.
"""
