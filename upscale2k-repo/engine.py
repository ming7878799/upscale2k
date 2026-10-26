#!/usr/bin/env python3
"""Engine upscale video len 2K bang AI super-resolution (OpenCV dnn_superres).

Pipeline: tach frame -> super-resolve x2 tung frame -> rap lai + giu am thanh goc.
Dau ra chuan 2K: ngang 2560x1440, doc 1440x2560 (fit theo ty le goc).
"""
import json
import os
import subprocess
import sys

import cv2

BASE = os.path.dirname(os.path.abspath(__file__))
MODELS = {
    "fast": ("FSRCNN-small_x2.pb", "fsrcnn"),   # ~0.4s/frame o 720p
    "quality": ("FSRCNN_x2.pb", "fsrcnn"),      # ~1s/frame o 720p, net hon
}
TARGET_LONG = 2560  # canh dai chuan 2K
TARGET_SHORT = 1440


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def probe(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate",
        "-show_entries", "format=duration", "-of", "json", path])
    info = json.loads(out)
    st = info["streams"][0]
    num, den = st["avg_frame_rate"].split("/")
    fps = float(num) / float(den) if float(den) else 24.0
    has_audio = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout.strip() != ""
    return st["width"], st["height"], fps, float(info["format"]["duration"]), has_audio


def target_size(w, h):
    """Kich thuoc 2K theo huong video, giu ty le, canh dai = 2560."""
    scale = TARGET_LONG / max(w, h)
    tw = int(round(w * scale / 2)) * 2
    th = int(round(h * scale / 2)) * 2
    return tw, th


def upscale_video(input_path, output_path, mode="quality", progress_cb=None):
    w, h, fps, dur, has_audio = probe(input_path)
    tw, th = target_size(w, h)
    job_dir = os.path.join(BASE, "jobs", "_tmp_" + str(os.getpid()))
    frames_in = os.path.join(job_dir, "in")
    frames_out = os.path.join(job_dir, "out")
    os.makedirs(frames_in, exist_ok=True)
    os.makedirs(frames_out, exist_ok=True)
    try:
        run(["ffmpeg", "-y", "-v", "error", "-i", input_path,
             os.path.join(frames_in, "%06d.png")])
        files = sorted(f for f in os.listdir(frames_in) if f.endswith(".png"))
        total = len(files)
        if total == 0:
            raise RuntimeError("Khong tach duoc frame nao tu video")

        model_file, model_name = MODELS[mode]
        sr = cv2.dnn_superres.DnnSuperResImpl_create()
        sr.readModel(os.path.join(BASE, "models", model_file))
        sr.setModel(model_name, 2)

        for i, name in enumerate(files):
            img = cv2.imread(os.path.join(frames_in, name))
            up = sr.upsample(img)  # x2 bang AI
            if up.shape[1] != tw or up.shape[0] != th:
                interp = cv2.INTER_LANCZOS4 if (tw < up.shape[1]) else cv2.INTER_CUBIC
                up = cv2.resize(up, (tw, th), interpolation=interp)
            cv2.imwrite(os.path.join(frames_out, name), up)
            if progress_cb:
                progress_cb(i + 1, total)

        cmd = ["ffmpeg", "-y", "-v", "error", "-framerate", f"{fps:.4f}",
               "-i", os.path.join(frames_out, "%06d.png")]
        if has_audio:
            cmd += ["-i", input_path, "-map", "0:v", "-map", "1:a",
                    "-c:a", "aac", "-b:a", "160k", "-shortest"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16",
                "-movflags", "+faststart", output_path]
        run(cmd)
        return {"width": tw, "height": th, "frames": total, "fps": fps, "duration": dur}
    finally:
        import shutil
        shutil.rmtree(job_dir, ignore_errors=True)


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    mode = sys.argv[3] if len(sys.argv) > 3 else "quality"
    def cb(done, total):
        print(f"\r{done}/{total}", end="", flush=True)
    info = upscale_video(src, dst, mode, cb)
    print("\nDONE", json.dumps(info))
