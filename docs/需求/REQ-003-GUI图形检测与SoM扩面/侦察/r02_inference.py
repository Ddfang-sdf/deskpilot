"""REQ-003 R-02 推理脚本(侦察证据归档,非一次性):候选模型零样本实测。

两候选均包装为详设 §2 检测器契约:入参内存 PIL 图 → list[{"rect","confidence"}]。
  · PicoDet-S 320(后处理内含 NMS):image [1,3,320,320] + scale_factor;
    输出行 [label, score, x1, y1, x2, y2](原图坐标)
  · RT-DETR-R18 640:pixel_values [1,3,640,640](/255 后 (x-0.5)/0.5);
    输出 logits sigmoid 取各类最大值,pred_boxes cxcywh 归一化 → 像素 xyxy
口径:门槛 0.3(零样本探测惯例);计时 = 装填(建 session)与稳态推理(3 次均值)分列;
样本 = samples/ 下四张(paint v1/v2 整窗、wxwork、seeyou)。标注图另存 r02-*.png。
"""
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image

ort.set_default_logger_severity(3)

ROOT = Path(__file__).resolve().parent
WEIGHTS = ROOT / "weights"
SAMPLES = ROOT / "samples"

COCO80 = ("person bicycle car motorcycle airplane bus train truck boat "
          "trafficlight firehydrant stopsign parkingmeter bench bird cat dog "
          "horse sheep cow elephant bear zebra giraffe backpack umbrella "
          "handbag tie suitcase frisbee skis snowboard sportsball kite "
          "baseballbat baseballglove skateboard surfboard tennisracket bottle "
          "wineglass cup fork knife spoon bowl banana apple sandwich orange "
          "broccoli carrot hotdog pizza donut cake chair couch pottedplant bed "
          "diningtable toilet tv laptop mouse remote keyboard cellphone "
          "microwave oven toaster sink refrigerator book clock vase scissors "
          "teddybear hairdrier toothbrush").split()

THRESHOLD = 0.3


class PicoDet:
    def __init__(self):
        self.sess = ort.InferenceSession(
            str(WEIGHTS / "picodet_s_320_lcnet_postprocessed.onnx"),
            providers=["CPUExecutionProvider"])

    def __call__(self, image: Image.Image) -> list[dict]:
        w, h = image.size
        arr = np.asarray(image.convert("RGB"), dtype=np.float32)
        resized = cv2.resize(arr, (320, 320))
        x = resized / 255.0
        x = (x - np.array([0.485, 0.456, 0.406])) / np.array([0.229, 0.224, 0.225])
        x = x.transpose(2, 0, 1)[None].astype(np.float32)
        sf = np.array([[320.0 / h, 320.0 / w]], dtype=np.float32)
        det, _n = self.sess.run(None, {"image": x, "scale_factor": sf})
        out = []
        for label, score, x1, y1, x2, y2 in det:
            if score >= THRESHOLD:
                out.append({"rect": [int(x1), int(y1), int(x2), int(y2)],
                            "confidence": float(score), "_cls": int(label)})
        return out


class RtDetr:
    def __init__(self):
        self.sess = ort.InferenceSession(str(WEIGHTS / "rtdetr_r18vd.onnx"),
                                         providers=["CPUExecutionProvider"])

    def __call__(self, image: Image.Image) -> list[dict]:
        w, h = image.size
        arr = np.asarray(image.convert("RGB"), dtype=np.float32)
        x = cv2.resize(arr, (640, 640)) / 255.0
        x = (x - 0.5) / 0.5
        x = x.transpose(2, 0, 1)[None].astype(np.float32)
        logits, boxes = self.sess.run(None, {"pixel_values": x})
        scores = 1.0 / (1.0 + np.exp(-logits[0]))        # sigmoid
        cls = scores.argmax(axis=1)
        conf = scores.max(axis=1)
        out = []
        for c, cf, (cx, cy, bw_, bh_) in zip(cls, conf, boxes[0]):
            if cf >= THRESHOLD:
                x1 = (cx - bw_ / 2) * w
                y1 = (cy - bh_ / 2) * h
                out.append({"rect": [int(x1), int(y1), int(x1 + bw_ * w),
                                     int(y1 + bh_ * h)],
                            "confidence": float(cf), "_cls": int(c)})
        return out


def run():
    models = [("picodet-s", PicoDet), ("rtdetr-r18", RtDetr)]
    sample_paths = sorted(SAMPLES.glob("paint-canvas-v*.png")) + [
        SAMPLES / "wxwork-main-全盲.png", SAMPLES / "seeyou-accelerator-全盲.png"]
    print(f"{'模型':<12}{'样本':<28}{'装填ms':>8}{'稳态ms':>8}{'框数':>5}  顶部分数(类:置信度)")
    for mname, cls in models:
        t0 = time.perf_counter()
        det = cls()
        load_ms = (time.perf_counter() - t0) * 1000
        for sp in sample_paths:
            img = Image.open(sp)
            det(img)  # 预热
            t0 = time.perf_counter()
            for _ in range(3):
                out = det(img)
            infer_ms = (time.perf_counter() - t0) * 1000 / 3
            top = sorted(out, key=lambda d: -d["confidence"])[:5]
            tops = " ".join(f"{COCO80[d['_cls']]}:{d['confidence']:.2f}"
                            for d in top)
            print(f"{mname:<12}{sp.stem[:26]:<28}{load_ms:>8.0f}"
                  f"{infer_ms:>8.1f}{len(out):>5}  {tops}")
            vis = cv2.imdecode(np.fromfile(str(sp), dtype=np.uint8),
                               cv2.IMREAD_COLOR)
            for d in out:
                l, t, r, b = d["rect"]
                cv2.rectangle(vis, (l, t), (r, b), (60, 60, 255), 2)
            cv2.imencode(".png", vis)[1].tofile(
                str(SAMPLES / f"r02-{mname}-{sp.stem}.png"))


if __name__ == "__main__":
    run()
