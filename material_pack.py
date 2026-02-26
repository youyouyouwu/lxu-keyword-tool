# material_pack.py
import io
import csv
import json
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional

from PIL import Image, ImageStat
import pypdfium2 as pdfium
import pandas as pd


@dataclass
class PackConfig:
    # --- image/pdf slicing ---
    target_w: int = 1400
    max_h: int = 1600
    min_h: int = 900
    overlap: float = 0.12
    skip_blank: bool = True
    blank_std_threshold: float = 6.0
    pdf_scale: float = 2.0


def is_blank(im: Image.Image, std_threshold: float) -> bool:
    g = im.convert("L")
    stat = ImageStat.Stat(g)
    return (stat.stddev[0] if stat.stddev else 0.0) < std_threshold


def resize_to_width(im: Image.Image, target_w: int) -> Image.Image:
    w, h = im.size
    if w == target_w:
        return im
    scale = target_w / float(w)
    new_h = int(round(h * scale))
    return im.resize((target_w, new_h), Image.LANCZOS)


def pdf_to_images(pdf_bytes: bytes, scale: float) -> List[Image.Image]:
    pdf = pdfium.PdfDocument(pdf_bytes)
    images: List[Image.Image] = []
    for i in range(len(pdf)):
        page = pdf[i]
        pil = page.render(scale=scale).to_pil()
        images.append(pil.convert("RGB"))
    return images


def slice_vertical(im: Image.Image, cfg: PackConfig) -> List[Tuple[int, Image.Image]]:
    slices: List[Tuple[int, Image.Image]] = []
    w, h = im.size
    slice_h = max(cfg.min_h, min(cfg.max_h, cfg.max_h))
    ov = int(round(slice_h * cfg.overlap))
    step = max(1, slice_h - ov)

    y = 0
    while y < h:
        y2 = min(h, y + slice_h)
        crop = im.crop((0, y, w, y2))
        if (not cfg.skip_blank) or (not is_blank(crop, cfg.blank_std_threshold)):
            slices.append((y, crop))
        if y2 >= h:
            break
        y += step
    return slices


def _img_to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def _dicts_to_csv_bytes(rows: List[Dict[str, Any]], fieldnames: List[str]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in fieldnames})
    return buf.getvalue().encode("utf-8-sig")


def write_feed_to_master_zip(
    master_zip,
    folder_name: str,
    uploaded_filename: str,
    uploaded_bytes: bytes,
    cfg: PackConfig,
    # data outputs you already have
    kw_list: List[str],
    df_market: pd.DataFrame,
    final_df: pd.DataFrame,
    res1_text: str,
    res3_text: str,
):
    """
    Writes a FEED_{folder_name}/ directory into existing master_zip.
    Does NOT change your workflow, only adds more files into same zip.
    """
    base = f"{folder_name}/FEED_{folder_name}"
    slices_prefix = f"{base}/slices"
    tables_prefix = f"{base}/tables"
    reports_prefix = f"{base}/reports"

    # 1) build image slices
    index_rows: List[Dict[str, Any]] = []

    ext = uploaded_filename.lower().split(".")[-1]
    if ext == "pdf":
        pages = pdf_to_images(uploaded_bytes, scale=cfg.pdf_scale)
        for pi, pim in enumerate(pages, start=1):
            rim = resize_to_width(pim, cfg.target_w)
            sl = slice_vertical(rim, cfg)
            for si, (y0, simg) in enumerate(sl, start=1):
                out_name = f"{folder_name}__p{pi:03d}__s{si:03d}.png"
                master_zip.writestr(f"{slices_prefix}/{out_name}", _img_to_png_bytes(simg))
                index_rows.append({
                    "source": folder_name,
                    "page": pi,
                    "slice": si,
                    "y0": y0,
                    "width": simg.size[0],
                    "height": simg.size[1],
                    "file": f"slices/{out_name}"
                })
    else:
        im = Image.open(io.BytesIO(uploaded_bytes)).convert("RGB")
        rim = resize_to_width(im, cfg.target_w)
        sl = slice_vertical(rim, cfg)
        for si, (y0, simg) in enumerate(sl, start=1):
            out_name = f"{folder_name}__s{si:03d}.png"
            master_zip.writestr(f"{slices_prefix}/{out_name}", _img_to_png_bytes(simg))
            index_rows.append({
                "source": folder_name,
                "page": "",
                "slice": si,
                "y0": y0,
                "width": simg.size[0],
                "height": simg.size[1],
                "file": f"slices/{out_name}"
            })

    # 2) write index_images.csv
    master_zip.writestr(
        f"{base}/index_images.csv",
        _dicts_to_csv_bytes(index_rows, ["source", "page", "slice", "y0", "width", "height", "file"])
    )

    # 3) write tables (data化)
    df_seed = pd.DataFrame({"seed_keyword": kw_list})
    master_zip.writestr(f"{tables_prefix}/keywords_seed.csv", _df_to_csv_bytes(df_seed))

    # df_market: from Naver API (already has columns)
    master_zip.writestr(f"{tables_prefix}/market_data.csv", _df_to_csv_bytes(df_market))

    # final_df: seed + top expanded (you used for step3 prompt)
    master_zip.writestr(f"{tables_prefix}/market_top.csv", _df_to_csv_bytes(final_df))

    schema = {
        "product": folder_name,
        "source_file": uploaded_filename,
        "tables": {
            "keywords_seed": "tables/keywords_seed.csv",
            "market_data": "tables/market_data.csv",
            "market_top": "tables/market_top.csv",
        },
        "images": {
            "index": "index_images.csv",
            "slices_dir": "slices/"
        },
        "slice_config": {
            "target_w": cfg.target_w,
            "max_h": cfg.max_h,
            "min_h": cfg.min_h,
            "overlap": cfg.overlap,
            "skip_blank": cfg.skip_blank,
            "blank_std_threshold": cfg.blank_std_threshold,
            "pdf_scale": cfg.pdf_scale
        }
    }
    master_zip.writestr(f"{base}/schema.json", json.dumps(schema, ensure_ascii=False, indent=2).encode("utf-8"))

    # 4) write reports (方便 GPT 复盘)
    master_zip.writestr(f"{reports_prefix}/res1_raw.txt", res1_text.encode("utf-8"))
    master_zip.writestr(f"{reports_prefix}/res3_raw.txt", res3_text.encode("utf-8"))

    # 5) GPT usage guide
    howto = (
        "【如何用这个喂料包给GPT分析】\n"
        "1) slices/：按 index_images.csv 从上到下阅读切片（带重叠，避免文字断裂）。\n"
        "2) tables/：关键词与查量数据（CSV），优先让GPT以 market_top.csv 为核心筛词。\n"
        "3) reports/：Gemini原报告，供GPT校验产品理解与否定词。\n"
        "推荐你对GPT的指令：\n"
        "“请先读取 tables/market_top.csv + tables/keywords_seed.csv，再结合 slices/ 的图片内容校验属性，输出可投关键词分组与否定词。”\n"
    )
    master_zip.writestr(f"{base}/HOW_TO_USE_WITH_GPT.txt", howto.encode("utf-8"))
