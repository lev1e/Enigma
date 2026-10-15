"""Строит реалистичные финансовые книги для проверки маскирования сумм (anonymizer/finance.py).

    .venv-mac/bin/python tools/make_finance_corpus.py [папка]

Функции возвращают байты .xlsx; тесты (tests/test_ws_finance.py) вызывают их напрямую.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.worksheet.formula import ArrayFormula
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.workbook.defined_name import DefinedName

RUB = '#,##0 "₽"'
THOUS = "#,##0"
PCT = "0.0%"


def _bytes(wb: Workbook) -> bytes:
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def pl_model() -> bytes:
    """P&L за четыре квартала: SUM/SUMIF/IF/ROUND/VLOOKUP, ссылки между листами, именованный диапазон, таблица, диаграмма."""
    wb = Workbook()
    pl = wb.active
    pl.title = "P&L"
    prices = wb.create_sheet("Цены 2024")
    prices["A1"], prices["B1"] = "Товар", "Цена, руб"
    for i, (name, price) in enumerate([("Товар А", 1250.5), ("Товар Б", 899), ("Товар В", 15400)], start=2):
        prices[f"A{i}"], prices[f"B{i}"] = name, price
        prices[f"B{i}"].number_format = RUB
    prices.add_table(Table(displayName="Прайс", ref="A1:B4", tableStyleInfo=TableStyleInfo(name="TableStyleLight1")))

    pl["A1"] = "Статья"
    for j, q in enumerate(["Q1", "Q2", "Q3", "Q4"]):
        pl.cell(row=1, column=2 + j, value=f"{q} 2024")
    pl["F1"] = "Итого, руб"
    rows = [
        ("Выручка", [4_200_000, 4_650_000, 5_100_500, 6_020_000], RUB),
        ("Себестоимость", [2_520_000, 2_790_000, 3_060_300, 3_500_000], RUB),
        ("Коммерческие расходы", [310_000, 340_500, 365_000, 402_000], THOUS),
        ("Управленческие расходы", [250_000, 250_000, 262_500, 275_000], THOUS),
    ]
    for i, (label, values, fmt) in enumerate(rows, start=2):
        pl.cell(row=i, column=1, value=label)
        for j, v in enumerate(values):
            c = pl.cell(row=i, column=2 + j, value=v)
            c.number_format = fmt
    col = lambda j: "BCDE"[j]
    pl["A6"], pl["A7"], pl["A8"], pl["A9"], pl["A10"] = "Валовая прибыль", "EBITDA", "Маржа EBITDA, %", "Налог на прибыль", "Чистая прибыль"
    for j in range(4):
        c = col(j)
        pl[f"{c}6"] = f"={c}2-{c}3"
        pl[f"{c}7"] = f"={c}6-{c}4-{c}5"
        pl[f"{c}8"] = f"={c}7/{c}2"
        pl[f"{c}8"].number_format = PCT
        pl[f"{c}9"] = f"=ROUND({c}7*$B$13,0)"
        pl[f"{c}10"] = f"={c}7-{c}9"
    for r in (2, 3, 4, 5, 6, 7, 9, 10):
        pl[f"F{r}"] = f"=SUM(B{r}:E{r})"
        pl[f"F{r}"].number_format = THOUS
    pl["F8"] = "=F7/F2"
    pl["F8"].number_format = PCT
    pl["A12"], pl["A13"], pl["A14"] = "Параметры", "Ставка налога, %", "Выручка по товару А"
    pl["B13"] = 0.2
    pl["B13"].number_format = "0%"
    pl["B14"] = "=VLOOKUP(\"Товар А\",'Цены 2024'!A2:B4,2,FALSE)*B15"
    pl["A15"], pl["B15"] = "Количество, шт", 340
    pl["A16"] = "Флаг рентабельности"
    pl["B16"] = '=IF(B8>0.1,"высокая","низкая")'
    pl["A17"], pl["B17"] = "Продажи по Q1+Q2 (SUMIF)", '=SUMIF(A2:A5,"Выручка",B2:B5)'
    pl["A18"], pl["B18"] = "Маржа в диапазоне", "=SUM(B6:E6)/SUM(B2:E2)"
    pl["B18"].number_format = PCT
    pl["B19"] = ArrayFormula("B19:B19", "=SUM(B2:E2*1)")
    pl["A19"] = "Выручка (массив)"
    pl["B2"].comment = Comment("Согласовано с ФД: 4,2 млн ₽ плановая выручка", "Иванов И.")
    wb.defined_names["Total_Revenue"] = DefinedName("Total_Revenue", attr_text="'P&L'!$F$2")
    pl["A21"], pl["B21"] = "Доля выручки Q4", "=E2/Total_Revenue"
    pl["B21"].number_format = PCT

    chart = BarChart()
    chart.title = "Выручка по кварталам"
    chart.add_data(Reference(pl, min_col=2, max_col=5, min_row=2), from_rows=True, titles_from_data=False)
    pl.add_chart(chart, "H2")

    hidden = wb.create_sheet("Служебный")
    hidden["A1"], hidden["B1"] = "Резерв, руб", 777_333
    hidden.sheet_state = "hidden"
    return _bytes(wb)


def simple_model() -> bytes:
    """Только + - * / SUM на одном листе: для сверки масштабной инвариантности простым вычислителем."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Модель"
    ws.append(["Статья", "Q1", "Q2", "Q3"])
    ws.append(["Выручка", 1_000_000, 1_200_000, 1_450_000])
    ws.append(["Себестоимость", 600_000, 700_000, 820_000])
    ws.append(["Прибыль", "=B2-B3", "=C2-C3", "=D2-D3"])
    ws.append(["Маржа, %", "=B4/B2", "=C4/C2", "=D4/D2"])
    ws.append(["Итого прибыль", "=SUM(B4:D4)", None, None])
    ws.append(["Рост выручки", None, "=C2/B2", "=D2/C2"])
    for c in "BCD":
        for r in (2, 3, 4):
            ws[f"{c}{r}"].number_format = THOUS
        ws[f"{c}5"].number_format = PCT
    return _bytes(wb)


def inconsistent_model() -> bytes:
    """Намеренно ломаемая при масштабировании модель: цена * сумма, сумма + число, сравнение суммы с числом."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Сделки"
    ws.append(["Позиция", "Цена, руб", "Сумма контракта", "Произведение", "С надбавкой", "Крупная?", "Итого сумма"])
    for i, (price, total) in enumerate([(120.5, 5_000), (310.25, 12_000), (99.9, 7_500)], start=2):
        ws.append([f"Сделка {i - 1}", price, total, f"=B{i}*C{i}", f"=C{i}+1000", f'=IF(C{i}>10000,"да","нет")', f"=SUM(C2:C4)" if i == 2 else None])
    ws["A9"], ws["B9"] = "Выручка", 2_345_678
    ws["A10"], ws["B10"] = "Себестоимость", 1_234_567
    ws["A11"], ws["B11"] = "Прибыль", "=B9-B10"
    return _bytes(wb)


def balance_sheet() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Баланс"
    data = [("Актив", None), ("Денежные средства", 1_250_300), ("Дебиторская задолженность", 2_480_100), ("Основные средства", 7_320_450),
            ("Итого активы", "=SUM(B2:B4)"), ("Пассив", None), ("Кредиты и займы", 3_100_000), ("Кредиторская задолженность", 1_150_850),
            ("Капитал", 6_799_999), ("Итого пассивы", "=SUM(B7:B9)"), ("Проверка баланса", "=B5-B10")]
    for label, v in data:
        ws.append([label, v])
    for r in range(2, 12):
        ws[f"B{r}"].number_format = THOUS
    return _bytes(wb)


def cap_table() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Cap table"
    ws.append(["Акционер", "Акций, шт", "Доля, %", "Цена за акцию, $", "Вложено, $"])
    rows = [("Основатель 1", 4_000_000, 0.4, 0.0125), ("Основатель 2", 3_000_000, 0.3, 0.0125), ("Инвестор А", 3_000_000, 0.3, 1.5)]
    for i, (n, sh, pct, price) in enumerate(rows, start=2):
        ws.append([n, sh, pct, price, f"=B{i}*D{i}"])
        ws[f"C{i}"].number_format = "0%"
        ws[f"D{i}"].number_format = "$#,##0.0000"
    ws.append(["Всего", "=SUM(B2:B4)", "=SUM(C2:C4)", None, "=SUM(E2:E4)"])
    ws.append(["Раунд, $", 4_500_000])
    return _bytes(wb)


def build_all(folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, fn in [("pl_model", pl_model), ("simple_model", simple_model), ("inconsistent_model", inconsistent_model),
                     ("balance_sheet", balance_sheet), ("cap_table", cap_table)]:
        path = folder / f"{name}.xlsx"
        path.write_bytes(fn())
        paths.append(path)
    return paths


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests/eval/finance")
    for p in build_all(target):
        print(p)
