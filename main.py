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
# 0. 核心配置
# ==========================================
st.set_page_config(page_title="LxU 测品工厂 (终极双修版)", layout="wide")

raw_keys = st.secrets.get("GEMINI_API_KEY", "")
API_KEYS = [k.strip() for k in raw_keys.split(",") if k.strip()]
NAVER_API_KEY = st.secrets.get("API_KEY")
NAVER_SECRET_KEY = st.secrets.get("SECRET_KEY")
NAVER_CUSTOMER_ID = st.secrets.get("CUSTOMER_ID")

if not API_KEYS or not NAVER_API_KEY:
    st.error("⚠️ 密钥配置异常，请检查 Secrets。")
    st.stop()

SECRET_KEY_BYTES = NAVER_SECRET_KEY.encode("utf-8")
NAVER_API_URL = "https://api.searchad.naver.com/keywordstool"

# ==========================================
# 1. 独立任务引擎 (彻底解决 HttpError 文件权限冲突)
# ==========================================
def run_gemini_task(file_path, prompt_text):
    """
    独立封装的 AI 任务：自己传文件，自己生结果，自己删文件，失败自动换 Key
    """
    for i, key in enumerate(API_KEYS):
        try:
            # 1. 挂载当前 Key
            genai.configure(api_key=key)
            
            # 2. 用当前 Key 上传文件
            gen_file = genai.upload_file(path=file_path)
            while gen_file.state.name == "PROCESSING":
                time.sleep(2)
                gen_file = genai.get_file(gen_file.name)
                
            # 3. 执行生成
            model = genai.GenerativeModel("gemini-1.5-flash")
            response = model.generate_content([gen_file, prompt_text])
            
            # 4. 阅后即焚，释放当前 Key 的云端空间
            try: genai.delete_file(gen_file.name) 
            except: pass
            
            return response.text
            
        except exceptions.ResourceExhausted:
            st.warning(f"⚠️ 第 {i+1} 个账号额度耗尽，自动切换备用账号...")
            continue
        except Exception as e:
            # 兜底：如果环境还是太老报 404，尝试老名字
            try:
                model = genai.GenerativeModel("models/gemini-1.5-flash")
                res = model.generate_content([gen_file, prompt_text])
                try: genai.delete_file(gen_file.name) 
                except: pass
                return res.text
            except Exception as inner_e:
                st.warning(f"⚠️ 第 {i+1} 个账号出错: {inner_e}")
                continue
    return None

# ==========================================
# 2. 核心指令 (严格表格锁定)
# ==========================================
PROMPT_STEP_1 = """
你是一个精通韩国 Coupang 运营的 SEO 专家，品牌名为 LxU。除韩文词外，所有分析文字必须纯中文。
第一，找出20个符合韩国习惯的关键词。
【强制格式】：必须输出为一个 Markdown 表格：| 序号 | 韩文关键词 | 中文翻译 | 纯中文策略解释 |
表格下方提供纯韩文逗号隔开的版本。
第二，生成广告分组、标题、好评（均须表格化）。
第三，去重汇总关键词放在 [LXU_KEYWORDS_START] 和 [LXU_KEYWORDS_END] 之间。
"""

PROMPT_STEP_3 = """
基于以下 Naver 数据输出终极策略：
{market_data}
所有分析文字必须纯中文，所有广告策略建议必须整合放在一个统一的 Markdown 表格中输出。
"""

# ==========================================
# 3. Naver API 查量引擎
# ==========================================
def fetch_naver_data(main_keywords, pb, st_text):
    all_rows = []
    for i, mk in enumerate(main_keywords, start=1):
        st_text.text(f"📊 Naver 查询中 [{i}/{len(main_keywords)}]: {mk}")
        pb.progress(i / len(main_keywords))
        try:
            ts = str(int(time.time() * 1000))
            sig = base64.b64encode(hmac.new(SECRET_KEY_BYTES, f"{ts}.GET./keywordstool".encode("utf-8"), hashlib.sha256).digest()).decode("utf-8")
            headers = {"X-Timestamp": ts, "X-API-KEY": NAVER_API_KEY, "X-Customer": NAVER_CUSTOMER_ID, "X-Signature": sig}
            res = requests.get(NAVER_API_URL, headers=headers, params={"hintKeywords": mk.replace(" ", ""), "showDetail": 1})
            if res.status_code == 200:
                for item in res.json().get("keywordList", [])[:8]:
                    pc = int(str(item.get("monthlyPcQcCnt", 0)).replace("<", "").replace(",", "")) if item.get("monthlyPcQcCnt") else 0
                    all_rows.append({"Naver词": item.get("relKeyword", ""), "搜索量": pc, "AI原词": mk})
        except: pass
        time.sleep(1) 
    return pd.DataFrame(all_rows).drop_duplicates(subset=["Naver词"]).sort_values(by="搜索量", ascending=False) if all_rows else pd.DataFrame()

# ==========================================
# 4. 全自动工作流 UI
# ==========================================
st.title("⚡ LxU 自动化工厂 (终极防线版)")

file = st.file_uploader("📥 上传详情页", type=["pdf", "png", "jpg"])

if file and st.button("🚀 启动流水线"):
    temp_path = f"temp_{file.name}"
    with open(temp_path, "wb") as f: f.write(file.getbuffer())
    
    with st.status("🔍 第一步：AI 提词 (物理隔离执行中)...", expanded=True) as s1:
        res1_text = run_gemini_task(temp_path, PROMPT_STEP_1)
        
        if res1_text:
            st.markdown(res1_text)
            kw_match = re.search(r"\[LXU_KEYWORDS_START\](.*?)\[LXU_KEYWORDS_END\]", res1_text, re.DOTALL)
            kw_list = [re.sub(r'[^가-힣\s]', '', l).strip() for l in kw_match.group(1).split('\n') if l.strip()] if kw_match else []
            s1.update(label=f"✅ 第一步完成", state="complete")
        else:
            st.error("❌ 任务失败：账号额度耗尽或环境依旧不兼容。请确保已添加 requirements.txt！")
            os.remove(temp_path)
            st.stop()

    with st.status("📊 第二步：Naver 查量...", expanded=True) as s2:
        pb = st.progress(0); txt = st.empty()
        df_market = fetch_naver_data(kw_list, pb, txt)
        if not df_market.empty:
            st.dataframe(df_market)
            s2.update(label=f"✅ 第二步完成 (衍生词：{len(df_market)})", state="complete")
        else: 
            st.error("Naver 接口未返回有效数据"); os.remove(temp_path); st.stop()

    with st.status("🧠 第三步：生成终极决策...", expanded=True) as s3:
        market_csv = df_market.to_csv(index=False)
        res3_text = run_gemini_task(temp_path, PROMPT_STEP_3.format(market_data=market_csv))
        
        if res3_text:
            st.markdown(res3_text)
            s3.update(label="✅ 第三步完成", state="complete")
        else:
            st.error("❌ 第三步策略生成失败。")
            
    # 全局清理本地缓存
    os.remove(temp_path)
