"""Actual source PTS boundaries, cached by source identity in each project."""
import json
import subprocess
from videogen.application.projects import atomic_json


def frame_boundaries(project_dir, project, info):
    path = project_dir / "frame-index.json"
    try:
        cached = json.loads(path.read_text())
        if cached.get("source_sha256") == project["source_sha256"]:
            return cached["boundaries"]
    except (OSError, ValueError, KeyError):
        pass
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", str(info.video_stream_index),
        "-show_frames", "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", project["source_path"]],
        capture_output=True, text=True, check=True, timeout=60)
    frames = json.loads(result.stdout)["frames"]
    boundaries = sorted({0.0, info.duration, *(max(0.0, min(info.duration,
        float(frame["best_effort_timestamp_time"]) - info.video_start)) for frame in frames
        if frame.get("best_effort_timestamp_time") is not None)})
    if len(boundaries) < 2:
        raise ValueError("Timestamp frame tidak ditemukan.")
    atomic_json(path, {"schema_version": 1, "source_sha256": project["source_sha256"], "boundaries": boundaries})
    return boundaries


if __name__ == "__main__":
    import argparse
    import os
    from pathlib import Path
    from videogen.application.projects import load_project
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    if os.name == "posix":
        os.setsid()
    project, _, info = load_project(args.project)
    frame_boundaries(args.project, project, info)
