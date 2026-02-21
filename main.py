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
from google.api_core import exceptions

# ==========================================
# 0. 页面配置与多 Key 引擎初始化
# ==========================================
st.set_page_config(page_title="LxU 测品工厂 (多Key加强版)", layout="wide")

# 支持多 Key 轮换
raw_keys = st.secrets.get("GEMINI_API_KEY", "")
API_KEYS = [k.strip() for k in raw_keys.split(",") if k.strip()]
NAVER_API_KEY = st.secrets.get("API_KEY")
NAVER_SECRET_KEY = st.secrets.get("SECRET_KEY")
NAVER_CUSTOMER_ID = st.secrets.get("CUSTOMER_ID")

if not API_KEYS or not NAVER_API_KEY:
    st.error("⚠️ 密钥配置缺失，请检查 Secrets。")
    st.stop()

SECRET_KEY_BYTES = NAVER_SECRET_KEY.encode("utf-8")
NAVER_API_URL = "https://api.searchad.naver.com/keywordstool"

# 核心指令 (强制表格 + 纯中文隔离)
PROMPT_STEP_1 = """
你是一个精通韩国 Coupang 运营的 SEO 专家，品牌名为 LxU。你的整个运营团队都在中国，请遵守【语言隔离】：除韩文词外，所有分析文字必须 100% 使用简体中文。
第一，找出20个韩国搜索关键词。
【绝对强制格式】：必须输出为一个标准的 Markdown 表格，严禁使用列表。
表格列：| 序号 | 韩文关键词 | 中文翻译 | 纯中文策略解释 |
表格下方输出纯韩文逗号隔开的版本。
第二，去重汇总所有关键词放在 [LXU_KEYWORDS_START] 和 [LXU_KEYWORDS_END] 之间。
"""

PROMPT_STEP_3 = """
基于以下 Naver 数据生成终极策略：
{market_data}
所有输出必须为纯中文。必须包含一个汇总所有词的 Markdown 表格。
"""

# ==========================================
# 1. 自动轮询执行函数
# ==========================================
def safe_generate_content(content_list):
    """
    如果一个 Key 挂了，自动尝试下一个 Key
    """
    for i, key in enumerate(API_KEYS):
        try:
            genai.configure(api_key=key)
            # 使用兼容性最强的模型名称
            model = genai.GenerativeModel("gemini-1.5-flash")
            response = model.generate_content(content_list)
            return response
        except exceptions.ResourceExhausted:
            st.warning(f"⚠️ 第 {i+1} 个 Key 额度耗尽，正在尝试切换下一个...")
            continue
        except Exception as e:
            st.warning(f"⚠️ 第 {i+1} 个 Key 出错: {e}")
            continue
    return None

# Naver 函数保持不变
def make_signature(method, uri, timestamp):
    message = f"{timestamp}.{method}.{uri}".encode("utf-8")
    sig = hmac.new(SECRET_KEY_BYTES, message, hashlib.sha256).digest()
    return base64.b64encode(sig).decode("utf-8")

def fetch_naver_data(main_keywords, pb, st_text):
    all_rows = []
    for i, mk in enumerate(main_keywords, start=1):
        st_text.text(f"📊 Naver 查询中 [{i}/{len(main_keywords)}]: {mk}")
        pb.progress(i / len(main_keywords))
        try:
            ts = str(int(time.time() * 1000))
            headers = {"X-Timestamp": ts, "X-API-KEY": NAVER_API_KEY, "X-Customer": NAVER_CUSTOMER_ID, "X-Signature": make_signature("GET", "/keywordstool", ts)}
            res = requests.get(NAVER_API_URL, headers=headers, params={"hintKeywords": mk.replace(" ", ""), "showDetail": 1})
            if res.status_code == 200:
                for item in res.json().get("keywordList", [])[:8]:
                    pc = int(str(item.get("monthlyPcQcCnt", 0)).replace("<", "").replace(",", "")) if item.get("monthlyPcQcCnt") else 0
                    all_rows.append({"Naver词": item.get("relKeyword", ""), "搜索量": pc, "AI源词": mk})
        except: pass
        time.sleep(1)
    return pd.DataFrame(all_rows).drop_duplicates(subset=["Naver词"]) if all_rows else pd.DataFrame()

# ==========================================
# 2. UI 逻辑
# ==========================================
st.title("⚡ LxU 自动化工厂 (多Key保护版)")
file = st.file_uploader("📥 上传详情页", type=["pdf", "png", "jpg"])

if file and st.button("🚀 开始全自动流水线"):
    temp_path = f"temp_{file.name}"
    with open(temp_path, "wb") as f: f.write(file.getbuffer())
    
    with st.status("🔍 第一步：AI 提词...", expanded=True) as s1:
        gen_file = genai.upload_file(path=temp_path)
        while gen_file.state.name == "PROCESSING":
            time.sleep(2)
            gen_file = genai.get_file(gen_file.name)
        
        response = safe_generate_content([gen_file, PROMPT_STEP_1])
        if response:
            st.markdown(response.text)
            kw_match = re.search(r"\[LXU_KEYWORDS_START\](.*?)\[LXU_KEYWORDS_END\]", response.text, re.DOTALL)
            kw_list = [re.sub(r'[^가-힣\s]', '', l).strip() for l in kw_match.group(1).split('\n') if l.strip()] if kw_match else []
            s1.update(label="✅ 第一步完成", state="complete")
        else:
            st.error("❌ 所有 Key 的额度都已耗尽，请稍后再试或新增 Key。")
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
            
    os.remove(temp_path)
