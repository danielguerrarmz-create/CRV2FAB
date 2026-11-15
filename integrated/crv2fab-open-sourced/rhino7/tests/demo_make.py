# -*- coding: utf-8 -*-
"""Make the demo video, one command (CPython 3, from the gnj-rhino7 folder):

    python tests\\demo_make.py

1. Exports the cores from git into the demo folder (main HEAD for beats 1 to 5, the part branch for
   beat 6), so the running cores are exactly those commits, whatever the working trees hold.
2. Widens the GNJSmoke TEST scheme's right-hand dock bar to 420 px (only that scheme's layout file;
   never the user's Default scheme), so the CRV2FAB tab is readable.
3. Runs tests/demo_record.py in a fresh Rhino 7 test instance (/scheme=GNJSmoke), killing only that
   process if it overruns. Never touches another Rhino, port 8742 or the sample file.
4. Assembles the captured frames (caption bar, title and end cards) into an MP4 with ffmpeg, and
   writes README.md.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile

DEMO = r"C:\Users\danie\scratch\2026-11-14\demo"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_REPO = r"C:\Users\danie\code\gnj-nudge-core"
PART_REPO = r"C:\Users\danie\code\_worktrees\gnj-nudge-core--part"
PART_REF = os.environ.get("GNJ_DEMO_PART_REF", "HEAD")
RHINO = r"C:\Program Files\Rhino 7\System\Rhino.exe"
SCHEME_LAYOUT = os.path.join(os.environ["APPDATA"], r"McNeel\Rhinoceros\7.0\settings\window_positions-Scheme__GNJSmoke.xml")
DOCK_BAR = '<child key="5a5b89a0-830f-c90d-5f60-35c2e907e18c">'   # the right-hand container the tab docks into
VIDEO = os.path.join(DEMO, "crv2fab-demo-2026-11-14.mp4")
W, H, BAR = 1920, 1080, 84
TITLE = ("CRV2FAB: Gesture, Nudge, Judge.", "Rhino 7, 14 November 2026.",
         "Assembled from real captures of the running system.")
ENDING = ("Not shown because not merged yet:", "sculpting, reading a photo, variable-curvature billets, editable settings.")


def git(repo, *args):
    return subprocess.check_output(["git", "-C", repo] + list(args)).decode().strip()


def export(repo, ref, dest):
    if os.path.isdir(dest):
        shutil.rmtree(dest)   # only ever the demo folder's own export
    data = subprocess.check_output(["git", "-C", repo, "archive", "--format=zip", ref])
    zipfile.ZipFile(io.BytesIO(data)).extractall(dest)
    return git(repo, "rev-parse", "--short", ref)


def widen_dock_bar(width=420):
    t = open(SCHEME_LAYOUT, encoding="utf-8").read()
    a = t.index(DOCK_BAR)
    b = t.index("</child>", a)
    block = t[a:b]
    import re
    block = re.sub(r'(<entry key="MRUDockPos">0,0,)\d+(,\d+</entry>)', r"\g<1>%d\2" % width, block)
    block = re.sub(r'(<entry key="MRUDockHorz">)\d+(,\d+</entry>)', r"\g<1>%d\2" % width, block)
    block = re.sub(r'(<entry key="MRUDockVert">)\d+(,\d+</entry>)', r"\g<1>%d\2" % width, block)
    open(SCHEME_LAYOUT, "w", encoding="utf-8").write(t[:a] + block + t[b:])


def record():
    script = os.path.join(REPO, "tests", "demo_record.py")
    cmd = '"%s" /nosplash /scheme=GNJSmoke /runscript="_-RunPythonScript %s _-Exit _No"' % (RHINO, script)
    p = subprocess.Popen(cmd)
    try:
        p.wait(timeout=900)
    except subprocess.TimeoutExpired:
        p.kill()   # only the instance this command started
        raise SystemExit("Rhino overran 900 s; killed pid %d" % p.pid)


def font(size, bold=False):
    from PIL import ImageFont
    name = "segoeuib.ttf" if bold else "segoeui.ttf"
    return ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name), size)


def card(lines, path):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), (28, 33, 38))
    d = ImageDraw.Draw(img)
    y = H // 2 - 40 * len(lines)
    for i, line in enumerate(lines):
        f = font(56 if i == 0 else 38, bold=(i == 0))
        w = d.textlength(line, font=f)
        d.text(((W - w) / 2, y), line, font=f, fill=(240, 240, 236))
        y += 90 if i == 0 else 64
    img.save(path)


def compose(raw, caption, path):
    """The capture fitted above a white caption bar with dark text."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), (28, 33, 38))
    shot = Image.open(raw).convert("RGB")
    area_h = H - BAR
    k = min(W / float(shot.width), area_h / float(shot.height))
    shot = shot.resize((int(shot.width * k), int(shot.height * k)), Image.LANCZOS)
    img.paste(shot, ((W - shot.width) // 2, (area_h - shot.height) // 2))
    d = ImageDraw.Draw(img)
    d.rectangle([0, H - BAR, W, H], fill=(255, 255, 255))
    f = font(30)
    text = caption
    while d.textlength(text, font=f) > W - 80 and len(text) > 10:
        text = text[:-2]
    d.text((40, H - BAR + (BAR - 38) // 2), text, font=f, fill=(24, 28, 32))
    img.save(path)


def assemble():
    frames = json.load(open(os.path.join(DEMO, "frames.json")))
    out = os.path.join(DEMO, "frames")
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    seq = [("title.png", 5.0)]
    card(TITLE, os.path.join(out, "title.png"))
    for i, f in enumerate(frames):
        name = "%03d.png" % (i + 1)
        compose(os.path.join(DEMO, "frames_raw", f["file"]), f["caption"], os.path.join(out, name))
        seq.append((name, f["seconds"]))
    card(ENDING, os.path.join(out, "end.png"))
    seq.append(("end.png", 5.0))
    lst = os.path.join(out, "concat.txt")
    with open(lst, "w") as fh:
        for name, sec in seq:
            fh.write("file '%s'\nduration %.4f\n" % (name, sec))
        fh.write("file '%s'\n" % seq[-1][0])   # the concat demuxer needs the last file twice
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                           "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                           "-movflags", "+faststart", VIDEO])
    return sum(s for _, s in seq), len(frames)


def main():
    if not os.path.isdir(DEMO):
        os.makedirs(DEMO)
    commits = {"gnj-rhino7": git(REPO, "rev-parse", "--short", "HEAD"),
               "core main (beats 1 to 5)": export(CORE_REPO, "main", os.path.join(DEMO, "core-main")),
               "core part branch (beat 6)": export(PART_REPO, PART_REF, os.path.join(DEMO, "core-part"))}
    json.dump(commits, open(os.path.join(DEMO, "commits.json"), "w"), indent=1)
    widen_dock_bar()
    for old in ("frames_raw", "frames.json", "dropped.json", "record.log", "record-main.jsonl", "record-part.jsonl"):
        path = os.path.join(DEMO, old)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)
    t0 = time.time()
    record()
    print("recorded in %.0f s" % (time.time() - t0))
    seconds, n = assemble()
    print("video:", VIDEO, "| %.1f s | %d captured frames" % (seconds, n), "| commits:", commits)


if __name__ == "__main__":
    main()
