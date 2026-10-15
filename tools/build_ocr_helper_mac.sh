#!/bin/sh
# Собирает помощника распознавания (Apple Vision) для упаковки в .app: на Mac пользователя компилятора может не быть.
set -e
cd "$(dirname "$0")/.."
swiftc -O anonymizer/ocr_helpers/vision_ocr.swift -o anonymizer/ocr_helpers/vision_ocr
echo "built anonymizer/ocr_helpers/vision_ocr"
