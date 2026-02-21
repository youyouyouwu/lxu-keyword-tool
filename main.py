import streamlit as st
import google.generativeai as genai
import pandas as pd
import time
import os
import re
import requests
import hashlib
import hmac
import base64
from PIL import Image
import io
from google.api_core import exceptions

# ==========================================
# 0. 配置与多 Key 初始化
# ==========================================
st.set_page_config(page_title="LxU 测品工厂 (终极兼容版)", layout="wide")

raw_keys = st.secrets.get("GEMINI_API_KEY", "")
API_KEYS = [k.strip() for k in raw_keys.split(",") if k.strip()]
NAVER_API_KEY = st.secrets.get("API_KEY")
NAVER_SECRET_KEY = st.secrets.get("SECRET_KEY")
NAVER_CUSTOMER_ID = st.secrets.get("CUSTOMER_ID")

if not API_KEYS or not NAVER_API_KEY:
    st.error("⚠️ 密钥缺失，请检查 Secrets。")
    st.stop()

SECRET_KEY_BYTES = NAVER_SECRET_KEY.encode("utf-8")
NAVER_API_URL = "https://api.searchad.naver.com/keywordstool"

# ==========================================
# 1. 核心工具函数 (新增自动压图)
# ==========================================
def compress_image(uploaded_file):
    """把大图压缩到 2MB 以内，防止额度瞬间耗尽"""
    img = Image.open(uploaded_file)
    # 如果是 RGBA (PNG)，转成 RGB 以便存为 JPG
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    
    img_byte_arr = io.BytesIO()
    # 初始质量 80
    img.save(img_byte_arr, format='JPEG', quality=80, optimize=True)
    
    # 如果还是太大，继续降质量
    if img_byte_arr.tell() > 2 * 1024 * 1024:
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=50, optimize=True)
        
    return img_byte_arr.getvalue()

def safe_generate_content(content_payload):
    """尝试多种模型名称，解决 404 兼容性问题"""
    # 按照兼容性从新到旧排序
    model_names = ["gemini-1.5-flash", "models/gemini-1.5-flash", "gemini-pro-vision"]
    
    for i, key in enumerate(API_KEYS):
        genai.configure(api_key=key)
        for m_name in model_names:
            try:
                model = genai.GenerativeModel(m_name)
                response = model.generate_content(content_payload)
                return response
            except (exceptions.NotFound, exceptions.InvalidArgument):
                continue # 名字不对，换下一个名字试
            except exceptions.ResourceExhausted:
                st.warning(f"⚠️ Key {i+1} 额度已干涸，切换 Key 中...")
                break # 额度没了，直接换下一个 Key
            except Exception as e:
                st.warning(f"⚠️ Key {i+1} 使用 {m_name} 时出错: {e}")
                continue
    return None

# Naver 查量函数
def fetch_naver_data(main_keywords, pb, st_text):
    all_rows = []
    for i, mk in enumerate(main_keywords, start=1):
        st_text.text(f"📊 Naver 拓词中 [{i}/{len(main_keywords)}]: {mk}")
        pb.progress(i / len(main_keywords))
        try:
            ts = str(int(time.time() * 1000))
            headers = {
                "X-Timestamp": ts, "X-API-KEY": NAVER_API_KEY, 
                "X-Customer": NAVER_CUSTOMER_ID, 
                "X-Signature": base64.b64encode(hmac.new(SECRET_KEY_BYTES, f"{ts}.GET./keywordstool".encode("utf-8"), hashlib.sha256).digest()).decode("utf-8")
            }
            res = requests.get(NAVER_API_URL, headers=headers, params={"hintKeywords": mk.replace(" ", ""), "showDetail": 1})
            if res.status_code == 200:
                for item in res.json().get("keywordList", [])[:8]:
                    pc = int(str(item.get("monthlyPcQcCnt", 0)).replace("<", "").replace(",", "")) if item.get("monthlyPcQcCnt") else 0
                    all_rows.append({"Naver词": item.get("relKeyword", ""), "搜索量": pc, "AI源词": mk})
        except: pass
        time.sleep(0.5)
    return pd.DataFrame(all_rows).drop_duplicates(subset=["Naver词"]).sort_values(by="搜索量", ascending=False) if all_rows else pd.DataFrame()

# ==========================================
# 2. 核心 Prompt
# ==========================================
PROMPT_STEP_1 = """
你是一个精通韩国 Coupang 运营的 SEO 专家，品牌名为 LxU。你的团队在中国，除韩文词外，所有分析文字必须 100% 使用简体中文。
第一，找出20个韩国搜索关键词，必须以 Markdown 表格形式输出。
第二，将所有词汇总去重放在 [LXU_KEYWORDS_START] 和 [LXU_KEYWORDS_END] 之间，每行一个词。
"""

PROMPT_STEP_3 = """
基于以下数据输出终极策略，必须包含一个汇总所有词的表格：
{market_data}
"""

# ==========================================
# 3. 运行界面
# ==========================================
st.title("🚀 LxU 自动化工厂 (终极兼容版)")

# 侧边栏清理
if st.sidebar.button("🗑️ 清理云端缓存"):
    for k in API_KEYS:
        try:
            genai.configure(api_key=k); [genai.delete_file(f.name) for f in genai.list_files()]
            st.sidebar.success(f"清理成功")
        except: pass

file = st.file_uploader("📥 上传详情页 (会自动压缩)", type=["png", "jpg", "jpeg"])

if file and st.button("开始全自动流水线"):
    # 自动压图
    with st.spinner("正在智能压缩图片以节省额度..."):
        compressed_data = compress_image(file)
        
    with st.status("🔍 第一步：AI 提词...", expanded=True) as s1:
        # 使用压缩后的数据直接上传
        temp_file_name = f"temp_upload_{int(time.time())}.jpg"
        with open(temp_file_name, "wb") as f:
            f.write(compressed_data)
        
        gen_file = genai.upload_file(path=temp_file_name)
        while gen_file.state.name == "PROCESSING":
            time.sleep(2)
            gen_file = genai.get_file(gen_file.name)
        
        response = safe_generate_content([gen_file, PROMPT_STEP_1])
        if response:
            st.markdown(response.text)
            kw_match = re.search(r"\[LXU_KEYWORDS_START\](.*?)\[LXU_KEYWORDS_END\]", response.text, re.DOTALL)
            kw_list = [re.sub(r'[^가-힣\s]', '', l).strip() for l in kw_match.group(1).split('\n') if l.strip()] if kw_match else []
            s1.update(label=f"✅ 第一步完成", state="complete")
        else:
            st.error("❌ 尝试了所有模型名称和 Key，均无法运行。请检查 API 状态。")
            st.stop()

    with st.status("📊 第二步：Naver 查量...", expanded=True) as s2:
        pb = st.progress(0); txt = st.empty()
        df_market = fetch_naver_data(kw_list, pb, txt)
        if not df_market.empty:
            st.dataframe(df_market)
            s2.update(label="✅ 第二步完成", state="complete")
        else: st.error("Naver 无数据"); st.stop()

    with st.status("🧠 第三步：生成终极策略...", expanded=True) as s3:
        market_csv = df_market.to_csv(index=False)
        res3 = safe_generate_content([gen_file, PROMPT_STEP_3.format(market_data=market_csv)])
        if res3:
            st.markdown(res3.text)
            s3.update(label="✅ 第三步完成", state="complete")
            
    os.remove(temp_file_name)
    try: genai.delete_file(gen_file.name)
    except: pass
