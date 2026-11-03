import os
import time
from types import SimpleNamespace

import cv2
import numpy as np

BATCH = 8


def delay():
    return float(os.environ.get('PE_OCR_FAKE_DELAY', '0.4'))


def ink_rows(gray):
    ink = gray < 140
    rows = ink.any(axis=1)
    bands, start = [], None
    for y, filled in enumerate(np.append(rows, False)):
        if filled and start is None:
            start = y
        elif not filled and start is not None:
            if y - start >= 6:
                bands.append((start, y))
            start = None
    boxes = []
    for y0, y1 in bands:
        xs = np.nonzero(ink[y0:y1].any(axis=0))[0]
        boxes.append((float(xs.min()), float(y0), float(xs.max() + 1), float(y1)))
    return boxes


class FakeSteps:
    def detect(self, path):
        time.sleep(delay())
        boxes = ink_rows(cv2.imread(path, cv2.IMREAD_GRAYSCALE))
        batches = [list(range(i, min(i + BATCH, len(boxes)))) for i in range(0, len(boxes), BATCH)]
        return SimpleNamespace(boxes=boxes, batches=batches, texts={})

    def recognize(self, scan, batch):
        time.sleep(delay())
        for index in batch:
            scan.texts[index] = f'Recognized line {index + 1}'

    def items(self, scan):
        return [(scan.texts[i], 0.99, box) for i, box in enumerate(scan.boxes) if i in scan.texts]


def steps():
    return FakeSteps()
