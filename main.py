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

# ==========================================
# 0. 页面与 Secrets 配置
# ==========================================
st.set_page_config(page_title="LxU 测品工厂 (终极修正版)", layout="wide")

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")
NAVER_API_KEY = st.secrets.get("API_KEY")
NAVER_SECRET_KEY = st.secrets.get("SECRET_KEY")
NAVER_CUSTOMER_ID = st.secrets.get("CUSTOMER_ID")

if not all([GEMINI_API_KEY, NAVER_API_KEY, NAVER_SECRET_KEY, NAVER_CUSTOMER_ID]):
    st.error("⚠️ 密钥未配齐，请检查 Secrets。")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)
SECRET_KEY_BYTES = NAVER_SECRET_KEY.encode("utf-8")
NAVER_API_URL = "https://api.searchad.naver.com/keywordstool"

# 侧边栏急救
with st.sidebar:
    st.header("🛠️ 系统维护")
    if st.button("🗑️ 清理云端积压垃圾"):
        try:
            for f in genai.list_files():
                genai.delete_file(f.name)
            st.success("清理成功！")
        except: st.error("清理失败或空间已空")

# ==========================================
# 1. 核心指令 (第一步强制表格输出 + 纯中文隔离)
# ==========================================
PROMPT_STEP_1 = """
你是一个精通韩国 Coupang 运营的 SEO 专家，品牌名为 LxU。你的整个运营团队都在中国，请遵守【语言隔离】：除韩文词外，所有分析文字必须 100% 使用简体中文。

--- 任务 ---
第一，分析详情页找出20个符合韩国搜索习惯的关键词。
【绝对强制格式】：必须输出为一个标准的 Markdown 表格，严禁使用子弹头列表。
表格骨架：| 序号 | 韩文关键词 | 中文翻译 | 纯中文策略解释 |
表格下方输出纯韩文逗号隔开的版本。

第二，输出广告分组建议，必须以 Markdown 表格排列。
表格骨架：| 序号 | 广告组分类 | 韩文关键词 | 中文翻译 | 中文策略解释 | 预估流量 | 相关性评分 |

第三，生成高点击率韩文标题方案（附中文翻译）。
第四，产品韩语管理名称（附中文翻译）。
第五，撰写5条商品韩文好评（必须表格形式，含翻译和买家痛点分析）。
第六，将所有关键词去重汇总，放在 [LXU_KEYWORDS_START] 和 [LXU_KEYWORDS_END] 之间，每行一个。
第七，AI 主图建议（纯中文）。
"""

PROMPT_STEP_3 = """
你是一位拥有10年实战经验的韩国 Coupang 专家。整个团队都在中国，请用纯中文输出分析。
基于详情页原图及以下 Naver 数据，输出策略：
{market_data}

第一步：视觉/痛点分析（纯中文）。
第二步：输出统一的 Markdown 表格！包含所有广告分组词汇。
表头：| 序号 | 广告组分类 | 韩文关键词 | 中文翻译 | 月总搜索量 | 竞争度 | 推荐策略 |
第三步：否定关键词列表及原因（纯中文）。
"""

# ==========================================
# 2. 核心函数 (API 调用)
# ==========================================
def clean_for_api(keyword: str): return re.sub(r"\s+", "", keyword)

def make_signature(method, uri, timestamp):
    message = f"{timestamp}.{method}.{uri}".encode("utf-8")
    sig = hmac.new(SECRET_KEY_BYTES, message, hashlib.sha256).digest()
    return base64.b64encode(sig).decode("utf-8")

def normalize_count(raw):
    if isinstance(raw, int): return raw
    if isinstance(raw, str):
        s = raw.strip().replace(",", "")
        if s.startswith("<"): return 5
        return int(s) if s.isdigit() else 0
    return 0

def fetch_naver_data(main_keywords, pb, st_text):
    all_rows = []
    total = len(main_keywords)
    for i, mk in enumerate(main_keywords, start=1):
        st_text.text(f"📊 Naver 查询中 [{i}/{total}]: {mk}")
        pb.progress(i / total)
        try:
            ts = str(int(time.time() * 1000))
            headers = {"X-Timestamp": ts, "X-API-KEY": NAVER_API_KEY, "X-Customer": NAVER_CUSTOMER_ID, "X-Signature": make_signature("GET", "/keywordstool", ts)}
            res = requests.get(NAVER_API_URL, headers=headers, params={"hintKeywords": clean_for_api(mk), "showDetail": 1})
            if res.status_code == 200:
                for item in res.json().get("keywordList", [])[:8]:
                    pc = normalize_count(item.get("monthlyPcQcCnt", 0))
                    mob = normalize_count(item.get("monthlyMobileQcCnt", 0))
                    all_rows.append({"Naver词": item.get("relKeyword", ""), "搜索量": pc + mob, "竞争度": item.get("compIdx", "-"), "源自AI词": mk})
        except: pass
        time.sleep(1)
    df = pd.DataFrame(all_rows)
    return df.drop_duplicates(subset=["Naver词"]).sort_values(by="搜索量", ascending=False) if not df.empty else df

# ==========================================
# 3. 运行工作流
# ==========================================
st.title("⚡ LxU 自动化测品工厂")
files = st.file_uploader("📥 上传详情页", type=["pdf", "png", "jpg"], accept_multiple_files=True)

if files and st.button("🚀 启动全自动闭环"):
    # 使用通用性最强的名称，解决 404 报错
    model = genai.GenerativeModel("gemini-1.5-flash-latest")
    
    for file in files:
        st.divider()
        st.header(f"📦 处理产品：{file.name}")
        temp_path = f"temp_{file.name}"
        with open(temp_path, "wb") as f: f.write(file.getbuffer())
        
        with st.status("🔍 第一步：AI 提词...", expanded=True) as s1:
            try:
                gen_file = genai.upload_file(path=temp_path)
                while gen_file.state.name == "PROCESSING":
                    time.sleep(2)
                    gen_file = genai.get_file(gen_file.name)
                
                # 执行 AI 生成 (加上错误捕获)
                res1 = model.generate_content([gen_file, PROMPT_STEP_1])
                st.markdown(res1.text)
                
                kw_match = re.search(r"\[LXU_KEYWORDS_START\](.*?)\[LXU_KEYWORDS_END\]", res1.text, re.DOTALL | re.IGNORECASE)
                kw_list = []
                if kw_match:
                    for line in kw_match.group(1).split('\n'):
                        word = re.sub(r'[^가-힣\s]', '', line).strip()
                        if word: kw_list.append(word)
                
                if kw_list: s1.update(label=f"✅ 第一步完成，捕获 {len(kw_list)} 词", state="complete")
                else: s1.update(label="❌ 提取失败", state="error"); continue
            except Exception as e:
                st.error(f"AI 故障: {e}. 请等待 1 分钟或清理云端。"); continue

        with st.status("📊 第二步：Naver 查量...", expanded=True) as s2:
            pb = st.progress(0); txt = st.empty()
            df_market = fetch_naver_data(kw_list, pb, txt)
            if not df_market.empty:
                st.dataframe(df_market)
                s2.update(label=f"✅ 第二步完成 (目标：{len(kw_list)} -> 衍生：{len(df_market)})", state="complete")
            else: st.error("Naver 数据为空"); continue

        with st.status("🧠 第三步：生成终极策略...", expanded=True) as s3:
            market_csv = df_market.to_csv(index=False)
            res3 = model.generate_content([gen_file, PROMPT_STEP_3.format(market_data=market_csv)])
            st.markdown(res3.text)
            s3.update(label="✅ 第三步完成！", state="complete")

        os.remove(temp_path)
        try: genai.delete_file(gen_file.name)
        except: pass
