"""演示 GIF 录制工具（scripts/record_demo.py）。

mss 截帧 + PIL 合成 gif,零外部依赖(项目 venv 已有 mss/Pillow)。
capture 的数据源可注入,单测不依赖真实屏幕。

用法:
    .venv/Scripts/python scripts/record_demo.py --out assets/demo.gif \
        --seconds 25 --fps 8 --width 960 [--region L,T,R,B] [--countdown 3]
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from PIL import Image


def capture_frames(seconds: float, fps: int, region: tuple | None = None,
                   source=None) -> list[Image.Image]:
    """按 fps 截 seconds 秒,返回 PIL 帧列(RGB)。

    source 可注入:无参可调用对象,每次返回一帧 PIL.Image(测试用合成帧);
    缺省用 mss 截主屏或 region=(left, top, right, bottom)。
    """
    if source is None:
        import mss
        sct = mss.mss()
        mon = sct.monitors[1]
        box = ({"left": region[0], "top": region[1],
                "width": region[2] - region[0], "height": region[3] - region[1]}
               if region else
               {"left": mon["left"], "top": mon["top"],
                "width": mon["width"], "height": mon["height"]})

        def source() -> Image.Image:
            shot = sct.grab(box)
            return Image.frombytes("RGB", (shot.width, shot.height),
                                   shot.bgra, "raw", "BGRX")

    n = max(1, int(round(seconds * fps)))
    interval = 1.0 / fps
    frames: list[Image.Image] = []
    t0 = time.perf_counter()
    for i in range(n):
        frames.append(source())
        # 按绝对时刻表推进,截帧耗时的轮次自动少睡(掉帧保时长)
        target = t0 + (i + 1) * interval
        delay = target - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
    return frames


def downscale(frame: Image.Image, width: int) -> Image.Image:
    """等比缩到指定宽(width<=0 原样返回)。"""
    if width <= 0 or frame.width <= width:
        return frame
    h = round(frame.height * width / frame.width)
    return frame.resize((width, h), Image.LANCZOS)


def save_gif(frames: list[Image.Image], out: str | Path, fps: int,
             width: int = 960, colors: int = 256) -> dict:
    """合成 gif(自适应调色板/循环播放),返回产物信息(直出)。

    colors 越小文件越小(128 对桌面内容通常无损观感)。
    """
    if not frames:
        raise ValueError("无帧可写")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    paletted = [downscale(f, width).convert(
        "P", palette=Image.ADAPTIVE, colors=colors) for f in frames]
    duration_ms = round(1000 / fps)
    paletted[0].save(out, save_all=True, append_images=paletted[1:],
                     duration=duration_ms, loop=0, optimize=True)
    return {"path": str(out), "frames": len(frames),
            "duration_s": round(len(frames) / fps, 2),
            "size_bytes": out.stat().st_size}


def concat_gifs(paths: list[str], out: str | Path, gap_ms: int = 0) -> dict:
    """分段拍摄拼接:各 GIF 帧序列首尾相连;gap_ms>0 时段间停顿
    (上段末帧停留时长加 gap_ms,硬切观感自然)。

    停顿实现:追加一帧与上段末帧同内容的帧——PIL 保存时会把同内容
    相邻帧合并成"时长加长"(实测 optimize 开关皆然),视觉即停顿帧。
    产物信息以落盘后直读为准,不虚报物理帧数。

    fail-closed:空列表/尺寸不一致 → ValueError。返回产物信息(直出)。
    """
    if not paths:
        raise ValueError("无输入 GIF")
    segments: list[list[tuple[Image.Image, int]]] = []   # 每段=帧序列
    size = None
    for p in paths:
        with Image.open(p) as gif:
            n = getattr(gif, "n_frames", 1)
            frames = []
            for i in range(n):
                gif.seek(i)
                frame = gif.convert("RGB")
                if size is None:
                    size = frame.size
                elif frame.size != size:
                    raise ValueError(
                        f"帧尺寸不一致: {frame.size} != {size}"
                        f"（各段须用同一录制参数）")
                frames.append((frame, int(gif.info.get("duration", 100))))
            segments.append(frames)
    frames: list[Image.Image] = []
    durations: list[int] = []
    for idx, seg in enumerate(segments):
        for frame, dur in seg:
            frames.append(frame)
            durations.append(dur)
        # 段间停顿:只在上一段的末帧之后插,时长 gap_ms
        if gap_ms > 0 and idx < len(segments) - 1:
            frames.append(seg[-1][0])
            durations.append(gap_ms)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    paletted = [f.convert("P", palette=Image.ADAPTIVE, colors=256)
                for f in frames]
    # optimize=False:optimize=True 会把跨段同内容帧也合并(段结构被
    # 破坏);False 仅合并相邻同内容帧=停顿帧,恰是设计语义
    paletted[0].save(out, save_all=True, append_images=paletted[1:],
                     duration=durations, loop=0, optimize=False)
    with Image.open(out) as gif:                 # 落盘直读,不虚报
        n = getattr(gif, "n_frames", 1)
        total_ms = 0
        for i in range(n):
            gif.seek(i)
            total_ms += gif.info.get("duration", 0)
    return {"path": str(out), "frames": n,
            "duration_s": round(total_ms / 1000, 2),
            "size_bytes": out.stat().st_size}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DeskPilot 演示 GIF 录制")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=float, default=20)
    ap.add_argument("--fps", type=int, default=8)
    ap.add_argument("--width", type=int, default=960,
                    help="输出宽,等比缩放;<=0 不缩放")
    ap.add_argument("--colors", type=int, default=256,
                    help="gif 调色板色数,越小文件越小")
    ap.add_argument("--region", default="",
                    help="L,T,R,B 像素区域;缺省主屏全屏")
    ap.add_argument("--countdown", type=float, default=3,
                    help="开录前倒计时(秒)")
    args = ap.parse_args(argv)

    region = None
    if args.region:
        parts = [int(x) for x in args.region.split(",")]
        if len(parts) != 4:
            ap.error("--region 须为 L,T,R,B 四个整数")
        region = tuple(parts)

    for s in range(int(args.countdown), 0, -1):
        print(f"  {s}...", flush=True)
        time.sleep(1)
    print("录制中...", flush=True)
    frames = capture_frames(args.seconds, args.fps, region)
    info = save_gif(frames, args.out, args.fps, args.width, args.colors)
    print(f"完成: {info['path']}  {info['frames']} 帧 "
          f"{info['duration_s']}s  {info['size_bytes'] / 1024:.0f}KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
