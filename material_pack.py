import io
import csv
import json
from dataclasses import dataclass
from typing import List, Dict, Any

from PIL import Image, ImageStat
import pypdfium2 as pdfium
import pandas as pd


@dataclass
class PackConfig:
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


def pdf_to_images(pdf_bytes: bytes, scale: float):
    pdf = pdfium.PdfDocument(pdf_bytes)
    images = []
    for i in range(len(pdf)):
        page = pdf[i]
        pil = page.render(scale=scale).to_pil()
        images.append(pil.convert("RGB"))
    return images


def slice_vertical(im: Image.Image, cfg: PackConfig):
    slices = []
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
    kw_list: List[str],
    df_market: pd.DataFrame,   # 这里保留参数，不影响 main.py 调用
    final_df: pd.DataFrame,
    res1_text: str,
    res3_text: str,
    out_root: str = "",        # ✅ 新增：控制写入 zip 的根目录
):
    # out_root="" => 写到zip根目录；out_root="xxx" => 写到 xxx/ 下
    prefix = out_root.strip("/").strip()
    def p(path: str) -> str:
        return f"{prefix}/{path}" if prefix else path

    # 1) 切片（基于最初上传文件）
    index_rows: List[Dict[str, Any]] = []
    ext = uploaded_filename.lower().split(".")[-1]

    if ext == "pdf":
        pages = pdf_to_images(uploaded_bytes, scale=cfg.pdf_scale)
        for pi, pim in enumerate(pages, start=1):
            rim = resize_to_width(pim, cfg.target_w)
            sl = slice_vertical(rim, cfg)
            for si, (y0, simg) in enumerate(sl, start=1):
                out_name = f"{folder_name}__p{pi:03d}__s{si:03d}.png"
                master_zip.writestr(p(f"slices/{out_name}"), _img_to_png_bytes(simg))
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
            master_zip.writestr(p(f"slices/{out_name}"), _img_to_png_bytes(simg))
            index_rows.append({
                "source": folder_name,
                "page": "",
                "slice": si,
                "y0": y0,
                "width": simg.size[0],
                "height": simg.size[1],
                "file": f"slices/{out_name}"
            })

    master_zip.writestr(
        p("index_images.csv"),
        _dicts_to_csv_bytes(index_rows, ["source", "page", "slice", "y0", "width", "height", "file"])
    )

    # 2) 表格数据化（你前面已要求：只保留最终表 + seed）
    df_seed = pd.DataFrame({"seed_keyword": kw_list})
    master_zip.writestr(p("tables/keywords_seed.csv"), _df_to_csv_bytes(df_seed))
    master_zip.writestr(p("tables/market_top.csv"), _df_to_csv_bytes(final_df))

    # 3) schema
    schema = {
        "product": folder_name,
        "source_file": uploaded_filename,
        "tables": {
            "keywords_seed": "tables/keywords_seed.csv",
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
    master_zip.writestr(p("schema.json"), json.dumps(schema, ensure_ascii=False, indent=2).encode("utf-8"))

    # 4) reports
    master_zip.writestr(p("reports/res1_raw.txt"), res1_text.encode("utf-8"))
    master_zip.writestr(p("reports/res3_raw.txt"), res3_text.encode("utf-8"))

    # 5) howto
    howto = (
        "【如何用这个喂料包给GPT分析】\n"
        "1) tables/market_top.csv：最终可用的核心数据表（优先读这个）。\n"
        "2) tables/keywords_seed.csv：第一步AI种子词（需要时参考）。\n"
        "3) slices/：原始详情页切片（按 index_images.csv 顺序看）。\n"
        "4) reports/：Gemini原报告（用于校验理解）。\n"
    )
    master_zip.writestr(p("HOW_TO_USE_WITH_GPT.txt"), howto.encode("utf-8"))
