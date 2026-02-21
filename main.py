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
# 0. 配置与多 Key 初始化
# ==========================================
st.set_page_config(page_title="LxU 测品工厂 (终极修复版)", layout="wide")

# 从 Secrets 读取多 Key (用逗号隔开)
raw_keys = st.secrets.get("GEMINI_API_KEY", "")
API_KEYS = [k.strip() for k in raw_keys.split(",") if k.strip()]

NAVER_API_KEY = st.secrets.get("API_KEY")
NAVER_SECRET_KEY = st.secrets.get("SECRET_KEY")
NAVER_CUSTOMER_ID = st.secrets.get("CUSTOMER_ID")

if not API_KEYS or not NAVER_API_KEY:
    st.error("⚠️ 密钥配置缺失，请检查 Secrets 里的 GEMINI_API_KEY。")
    st.stop()

SECRET_KEY_BYTES = NAVER_SECRET_KEY.encode("utf-8")
NAVER_API_URL = "https://api.searchad.naver.com/keywordstool"

# 侧边栏清理工具
with st.sidebar:
    st.header("🛠️ 维护工具")
    if st.button("🗑️ 清理云端垃圾文件"):
        for k in API_KEYS:
            try:
                genai.configure(api_key=k)
                for f in genai.list_files():
                    genai.delete_file(f.name)
                st.success(f"Key[{k[:5]}...] 清理完成")
            except: pass

# ==========================================
# 1. 核心指令 (强制表格输出)
# ==========================================
PROMPT_STEP_1 = """
你是一个精通韩国 Coupang 运营的 SEO 专家，品牌名为 LxU。你的团队在中国，除韩文词外，所有分析文字必须 100% 使用简体中文。

第一，找出20个韩国搜索关键词。
【绝对强制格式】：必须输出为一个标准的 Markdown 表格，严禁使用列表。
表格列：| 序号 | 韩文关键词 | 中文翻译 | 纯中文策略解释 |

第二，生成高点击率标题方案、内部管理名称、5条商品好评（均须表格形式且附翻译）。

第三，将所有关键词汇总去重，放在 [LXU_KEYWORDS_START] 和 [LXU_KEYWORDS_END] 之间。
"""

PROMPT_STEP_3 = """
你是一位拥有10年经验的 Coupang 专家。基于以下 Naver 数据，输出终极策略：
{market_data}
所有分析必须纯中文。所有关键词必须放在一个统一的 Markdown 表格中输出。
表头：| 序号 | 广告组分类 | 韩文关键词 | 中文翻译 | 月总搜索量 | 竞争度 | 推荐策略 |
"""

# ==========================================
# 2. 核心执行逻辑 (支持自动换 Key)
# ==========================================
def safe_generate_content(content_payload):
    """
    尝试使用不同的 Key 调用 AI，解决 404 或限流问题
    """
    for i, key in enumerate(API_KEYS):
        try:
            genai.configure(api_key=key)
            # 🚀 使用最标准的模型路径，解决 404 问题
            model = genai.GenerativeModel("models/gemini-1.5-flash")
            response = model.generate_content(content_payload)
            return response
        except exceptions.NotFound:
            st.warning(f"⚠️ Key {i+1} 提示模型不存在，尝试兼容模式...")
            try:
                model = genai.GenerativeModel("gemini-pro-vision") # 备用老版本模型名
                return model.generate_content(content_payload)
            except: continue
        except exceptions.ResourceExhausted:
            st.warning(f"⚠️ Key {i+1} 额度用光，切换中...")
            continue
        except Exception as e:
            st.warning(f"⚠️ Key {i+1} 出错: {e}")
            continue
    return None

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
# 3. 页面渲染
# ==========================================
st.title("🚀 LxU 自动化工厂 (终极修复版)")

file = st.file_uploader("📥 上传产品详情页 (建议压到 2MB 以内)", type=["pdf", "png", "jpg"])

if file and st.button("开始全自动流水线"):
    temp_path = f"temp_{file.name}"
    with open(temp_path, "wb") as f: f.write(file.getbuffer())
    
    with st.status("🔍 第一步：AI 提词 (正在尝试可用 Key)...", expanded=True) as s1:
        gen_file = genai.upload_file(path=temp_path)
        while gen_file.state.name == "PROCESSING":
            time.sleep(2)
            gen_file = genai.get_file(gen_file.name)
        
        response = safe_generate_content([gen_file, PROMPT_STEP_1])
        if response:
            st.markdown(response.text)
            kw_match = re.search(r"\[LXU_KEYWORDS_START\](.*?)\[LXU_KEYWORDS_END\]", response.text, re.DOTALL)
            kw_list = [re.sub(r'[^가-힣\s]', '', l).strip() for l in kw_match.group(1).split('\n') if l.strip()] if kw_match else []
            s1.update(label=f"✅ 第一步完成 (提取 {len(kw_list)} 词)", state="complete")
        else:
            st.error("❌ 所有 Key 都不可用或额度耗尽。请检查 Secrets 或压缩图片体积。")
            st.stop()

    with st.status("📊 第二步：Naver 查量...", expanded=True) as s2:
        pb = st.progress(0); txt = st.empty()
        df_market = fetch_naver_data(kw_list, pb, txt)
        if not df_market.empty:
            st.dataframe(df_market)
            s2.update(label=f"✅ 第二步完成 (衍生 {len(df_market)} 词)", state="complete")
        else: st.error("Naver 接口未返回数据"); st.stop()

    with st.status("🧠 第三步：生成终极策略...", expanded=True) as s3:
        market_csv = df_market.to_csv(index=False)
        res3 = safe_generate_content([gen_file, PROMPT_STEP_3.format(market_data=market_csv)])
        if res3:
            st.markdown(res3.text)
            s3.update(label="✅ 第三步完成", state="complete")
            
    os.remove(temp_path)
