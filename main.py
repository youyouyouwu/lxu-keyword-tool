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
# 0. 核心配置与多 Key 轮换引擎
# ==========================================
st.set_page_config(page_title="LxU 测品工厂 (多Key自动切换版)", layout="wide")

# 自动解析多 Key 列表
raw_keys = st.secrets.get("GEMINI_API_KEY", "")
API_KEYS = [k.strip() for k in raw_keys.split(",") if k.strip()]
NAVER_API_KEY = st.secrets.get("API_KEY")
NAVER_SECRET_KEY = st.secrets.get("SECRET_KEY")
NAVER_CUSTOMER_ID = st.secrets.get("CUSTOMER_ID")

if not API_KEYS or not NAVER_API_KEY:
    st.error("⚠️ 密钥配置异常，请检查 Secrets 是否已按逗号隔开填入多个 Key。")
    st.stop()

SECRET_KEY_BYTES = NAVER_SECRET_KEY.encode("utf-8")
NAVER_API_URL = "https://api.searchad.naver.com/keywordstool"

# --- 智能切换执行器 ---
def call_gemini_with_rotation(content_payload):
    """
    如果当前 Key 额度耗尽，自动轮询下一个可用 Key
    """
    for i, current_key in enumerate(API_KEYS):
        try:
            genai.configure(api_key=current_key)
            # 采用兼容性最强的 1.5-flash 模型路径
            model = genai.GenerativeModel("models/gemini-1.5-flash")
            response = model.generate_content(content_payload)
            return response
        except exceptions.ResourceExhausted:
            st.warning(f"💡 系统提示：第 {i+1} 个账号额度暂耗尽，正在自动切换备用账号...")
            continue # 换下一个 Key
        except Exception as e:
            st.warning(f"⚠️ 第 {i+1} 个账号调用出错: {e}")
            continue
    return None

# ==========================================
# 1. 核心指令 (第一步强制表格输出 + 纯中文隔离)
# ==========================================
PROMPT_STEP_1 = """
你是一个精通韩国 Coupang 运营的 SEO 专家，品牌名为 LxU。你的团队在中国，除韩文词外，所有文字必须使用简体中文。
第一，找出20个符合韩国习惯的关键词。
【强制格式】：必须输出 Markdown 表格：| 序号 | 韩文关键词 | 中文翻译 | 纯中文策略解释 |
表格下方提供纯韩文逗号隔开的版本。
第二，生成广告分组、标题、好评（均须表格化）。
第三，去重汇总关键词放在 [LXU_KEYWORDS_START] 和 [LXU_KEYWORDS_END] 之间。
"""

PROMPT_STEP_3 = """
基于以下 Naver 数据输出终极策略：
{market_data}
所有分析文字必须纯中文，所有关键词建议必须放在一个统一的表格中输出。
"""

# Naver 函数
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
                    all_rows.append({"Naver词": item.get("relKeyword", ""), "搜索量": pc, "AI原词": mk})
        except: pass
        time.sleep(1) # API 频率保护
    return pd.DataFrame(all_rows).drop_duplicates(subset=["Naver词"]).sort_values(by="搜索量", ascending=False) if all_rows else pd.DataFrame()

# ==========================================
# 2. 自动化工作流
# ==========================================
st.title("⚡ LxU 自动化工厂 (多账号冗余版)")
st.sidebar.info(f"当前已挂载备用 Key 数量: {len(API_KEYS)}")

file = st.file_uploader("📥 上传详情页 (支持多 Key 自动切分)", type=["pdf", "png", "jpg"])

if file and st.button("🚀 启动流水线"):
    temp_path = f"temp_{file.name}"
    with open(temp_path, "wb") as f: f.write(file.getbuffer())
    
    with st.status("🔍 第一步：AI 提词 (全自动轮询中)...", expanded=True) as s1:
        gen_file = genai.upload_file(path=temp_path)
        while gen_file.state.name == "PROCESSING":
            time.sleep(2)
            gen_file = genai.get_file(gen_file.name)
        
        # 使用自动轮换函数
        res1 = call_gemini_with_rotation([gen_file, PROMPT_STEP_1])
        if res1:
            st.markdown(res1.text)
            kw_match = re.search(r"\[LXU_KEYWORDS_START\](.*?)\[LXU_KEYWORDS_END\]", res1.text, re.DOTALL)
            kw_list = [re.sub(r'[^가-힣\s]', '', l).strip() for l in kw_match.group(1).split('\n') if l.strip()] if kw_match else []
            s1.update(label=f"✅ 第一步完成", state="complete")
        else:
            st.error("❌ 所有账号额度均已耗尽，请稍后再试或新增 Key。")
            st.stop()

    with st.status("📊 第二步：Naver 查量...", expanded=True) as s2:
        pb = st.progress(0); txt = st.empty()
        df_market = fetch_naver_data(kw_list, pb, txt)
        if not df_market.empty:
            st.dataframe(df_market)
            s2.update(label=f"✅ 第二步完成 (衍生词：{len(df_market)})", state="complete")
        else: st.error("Naver 接口未返回有效数据"); st.stop()

    with st.status("🧠 第三步：生成终极决策...", expanded=True) as s3:
        market_csv = df_market.to_csv(index=False)
        # 再次调用轮换函数
        res3 = call_gemini_with_rotation([gen_file, PROMPT_STEP_3.format(market_data=market_csv)])
        if res3:
            st.markdown(res3.text)
            s3.update(label="✅ 第三步完成", state="complete")
            
    os.remove(temp_path)
    try: genai.delete_file(gen_file.name)
    except: pass
