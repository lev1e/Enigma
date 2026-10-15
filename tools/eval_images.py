"""Оценка обезличивания картинок на синтетическом наборе (v1): утечки, ложные закраски, точность восстановления.

Запуск: .venv-mac/bin/python tools/eval_images.py [--out каталог] [--keep]
Данные выдуманные. Утечка = значение читается на результате независимым распознаванием при масштабах 1x/2x/3x
и при повороте на 90°. Восстановление сверяется побайтно.
"""
from __future__ import annotations

import argparse
import io
import json
import random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from anonymizer import ocr
from tests.helpers import Env

FONTS = {"arial": "/System/Library/Fonts/Supplemental/Arial.ttf", "times": "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
         "courier": "/System/Library/Fonts/Supplemental/Courier New.ttf", "verdana": "/System/Library/Fonts/Supplemental/Verdana.ttf",
         "arialbold": "/System/Library/Fonts/Supplemental/Arial Bold.ttf"}
V = {"name": "Смирнов Алексей Петрович", "email": "a.smirnov@rostelecom-demo.ru", "phone": "+7 (916) 555-12-34",
     "inn": "7707083893", "org": "ООО «Ромашка Логистик»", "en": "John Whitfield", "card": "4276 3800 1234 5678"}
SECRETS = [V["inn"], "Смирнов", "Петрович", "a.smirnov", "rostelecom-demo", "555-12-34", "Ромашка", "Whitfield", "4276"]


def draw(lines, font="arial", size=22, fg=(20, 20, 20), bg=(255, 255, 255), noise=0, blur=0.0, rot=0, width=900, pad=24, gap=1.5):
    f = ImageFont.truetype(FONTS[font], size)
    img = Image.new("RGB", (width, int(pad * 2 + len(lines) * size * gap)), bg)
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((pad, pad + i * size * gap), line, font=f, fill=fg)
    if rot:
        img = img.rotate(rot, expand=True, fillcolor=bg)
    if noise:
        rnd = random.Random(7)
        px = img.load()
        for _ in range(img.width * img.height * noise // 100):
            x, y = rnd.randrange(img.width), rnd.randrange(img.height)
            v = rnd.randrange(-40, 40)
            r, g, b = px[x, y]
            px[x, y] = (max(0, min(255, r + v)), max(0, min(255, g + v)), max(0, min(255, b + v)))
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    return img


def cases():
    L = lambda *p: [s.format(**V) for s in p]
    yield "letter_arial", draw(L("Клиент: {name}", "Организация: {org}, ИНН {inn}", "Тел.: {phone}  Email: {email}", "Contact: {en}")), "png"
    yield "small_font", draw(L("Клиент: {name}, ИНН {inn}", "{email} {phone}"), size=13), "png"
    yield "large_font", draw(L("{name}", "{email}"), size=44, width=1300), "png"
    yield "dark_theme", draw(L("Пользователь: {name}", "Почта: {email}", "Телефон {phone}"), fg=(235, 235, 235), bg=(24, 28, 40)), "png"
    yield "colored_bg", draw(L("Контакт: {name}", "{org} ИНН {inn}"), fg=(10, 40, 90), bg=(255, 236, 170)), "png"
    yield "courier_code", draw(L("name = '{name}'", "mail = '{email}'", "inn  = {inn}"), font="courier"), "png"
    yield "times_doc", draw(L("Договор с {org}", "Директор {name}", "ИНН {inn}, тел. {phone}"), font="times", size=26), "png"
    yield "noisy_jpg", draw(L("Клиент {name}", "{email}  {phone}"), noise=25), "jpg"
    yield "blurry_jpg", draw(L("Клиент {name}", "ИНН {inn} {email}"), blur=0.7, size=24), "jpg"
    yield "rotated_3deg", draw(L("Клиент {name}", "{email}", "ИНН {inn}"), rot=3), "png"
    yield "table_like", draw(L("ФИО               | Телефон            | Email", "{name} | {phone} | {email}", "{en} | +1 202 555 0170 | j.w@example.com"), font="courier", size=18, width=1200), "png"
    yield "no_secrets", draw(["Квартальный отчёт по продажам", "Выручка выросла на 12 процентов", "Спасибо за внимание"]), "png"
    yield "card_number", draw(L("Карта {card}", "Владелец {name}")), "png"
    yield "english_only", draw(["Customer: John Whitfield", "Mail: j.whitfield@acme-demo.com", "Phone +44 20 7946 0958"]), "png"
    yield "low_contrast", draw(L("Клиент {name}", "{email}"), fg=(150, 150, 150), bg=(215, 215, 215)), "png"
    yield "tiny_jpg_lowq", draw(L("{name} {phone}"), size=16, noise=10), "jpg"


def words_at(data: bytes, scales=(1.0, 2.0, 3.0)) -> str:
    out = []
    for rotate in (0, 90):
        doc = fitz.open()
        pix = fitz.Pixmap(data)
        page = doc.new_page(width=pix.width, height=pix.height)
        page.insert_image(page.rect, stream=data, rotate=rotate) if rotate else page.insert_image(page.rect, stream=data)
        for sc in scales:
            out += [w.text for w in ocr.ocr_page_words(page, scale=sc)[0]]
    return " ".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    out_dir = Path(args.out or tempfile.mkdtemp(prefix="evalimg-"))
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, leaked_total, unreadable = [], 0, 0
    for name, img, fmt in cases():
        buf = io.BytesIO()
        img.save(buf, "PNG" if fmt == "png" else "JPEG", **({} if fmt == "png" else {"quality": 80}))
        raw = buf.getvalue()
        (out_dir / f"{name}.{fmt}").write_bytes(raw)
        env = Env()
        try:
            before = words_at(raw)
            readable = [s for s in SECRETS if s.lower() in before.lower() or s.replace(" ", "").lower() in before.replace(" ", "").lower()]
            t0 = time.time()
            job = env.anonymize((f"{name}.{fmt}", raw))
            dt = time.time() - t0
            f = job.files[0]
            row = {"case": name, "fmt": fmt, "readable_before": readable, "status": f.status, "seconds": round(dt, 2),
                   "messages": [m["text"] for m in f.messages][:2]}
            if f.out_path:
                outb = Path(f.out_path).read_bytes()
                (out_dir / f"{name}.out.{fmt}").write_bytes(outb)
                after = words_at(outb)
                norm = lambda t: t.replace(" ", "").lower()
                leaks = [s for s in readable if norm(s) in norm(after)]
                row["leaks"] = leaks
                row["dims_same"] = (fitz.Pixmap(outb).width, fitz.Pixmap(outb).height) == (fitz.Pixmap(raw).width, fitz.Pixmap(raw).height)
                rf = env.restore(env.as_upload(job)).files[0]
                row["restore_exact"] = bool(rf.out_path) and Path(rf.out_path).read_bytes() == raw
                leaked_total += len(leaks)
            else:
                row["blocked"] = True
            if not readable:
                unreadable += 1
            rows.append(row)
        finally:
            env.close()
    (out_dir / "matrix.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
    print(f"\nTOTAL cases={len(rows)} leaked_values={leaked_total} blocked={sum(1 for r in rows if r.get('blocked'))} "
          f"restore_exact={sum(1 for r in rows if r.get('restore_exact'))} out={out_dir}")
    return 1 if leaked_total else 0


if __name__ == "__main__":
    raise SystemExit(main())
