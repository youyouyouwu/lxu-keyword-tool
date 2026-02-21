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
st.set_page_config(page_title="LxU 测品工厂 (单账号纯净版)", layout="wide")

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")
NAVER_API_KEY = st.secrets.get("API_KEY")
NAVER_SECRET_KEY = st.secrets.get("SECRET_KEY")
NAVER_CUSTOMER_ID = st.secrets.get("CUSTOMER_ID")

if not all([GEMINI_API_KEY, NAVER_API_KEY, NAVER_SECRET_KEY, NAVER_CUSTOMER_ID]):
    st.error("⚠️ 缺少 API 密钥！请确保 Secrets 中配置了所有必需的 Key。")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)
SECRET_KEY_BYTES = NAVER_SECRET_KEY.encode("utf-8")
NAVER_API_URL = "https://api.searchad.naver.com/keywordstool"

# ==========================================
# 1. 核心指令 (强制表格输出)
# ==========================================
PROMPT_STEP_1 = """
你是一个精通韩国 Coupang 运营的 SEO 专家，品牌名为 LxU。注意：你的整个运营团队都在中国，所以你必须遵守以下极其严格的【语言输出隔离规范】：
1. 所有的“分析过程”、“策略解释”、“使用原因”、“主图建议”等任何沟通描述性质的文字，必须 100% 使用【简体中文】！绝对禁止使用韩文解释！
2. 只有“韩文关键词本身”、“韩语标题”和“商品好评的韩文原文”这三个部分允许出现韩文，且必须全部附带对应的【中文翻译】。

--- 核心任务 ---
第一，我是一个在韩国做coupang平台的跨境电商卖家，这是我的产品详情页，我现在需要后台找出20个产品关键词输入到后台。请帮我找到或者推测出这些符合本地搜索习惯的韩文关键词。
【强制输出格式】：
1. 必须将这20个关键词以 Markdown 表格形式输出，绝对不允许使用竖版圆点列表！
表格骨架严格如下：
| 序号 | 韩文关键词 | 中文翻译 | 纯中文策略解释 |
|---|---|---|---|
| 1 | ... | ... | ... |
2. 在表格下方，单独输出一款纯韩文、逗号隔开的版本，方便在coupang后台录入。

第二，找精准长尾词做付费推广。
输出格式：Markdown 表格形式，表头固定为：【序号 | 广告组分类 | 韩文关键词 | 中文翻译 | 中文策略解释 | 预估流量(High/Medium/Low) | 相关性评分(1-5)】。

第三，生成一个高点击率 (High CTR) 韩文标题方案：公式 [品牌名] + [直击痛点形容词] + [核心差异化卖点] + [核心大词] + [核心属性/材质] + [场景/功能]。20个字以内，符合韩国人可读性（需附带中文翻译）。

第四，提供一个产品韩语名称用于内部管理（附带中文翻译）。

第五，按照产品卖点撰写5条商品韩文好评，语法自然，必须以 Markdown 表格形式排列。表头固定为：【序号 | 韩文评价原文 | 纯中文翻译 | 纯中文的买家痛点分析】。

第六，将上述三个广告组的所有关键词进行去重汇总，单列纵向列表输出。

第七，AI 主图生成建议：基于场景词用纯中文建议背景和构图，主图严禁带文字。

【程序读取专属指令 - 极度重要】：
为了方便我的系统自动抓取，请务必将“第六部分”的最终去重汇总关键词，放在以下两个标记之间输出！每行只写一个韩文关键词，尽量不要带中文或序号。
[LXU_KEYWORDS_START]
(在这里填入纯韩文关键词)
[LXU_KEYWORDS_END]
"""

PROMPT_STEP_3 = """
你是一位拥有10年实战经验的韩国 Coupang 跨境电商运营专家，精通韩语语义分析、VOC挖掘以及“精铺快速测品”的高 ROAS 广告策略。整个团队都在中国，所以除韩文关键词外，所有解释分析必须用纯中文输出。

**核心任务：**
基于产品详情页原图及以下 Naver 关键词真实搜索量数据（CSV格式），输出精准广告分组、否定词表。不要含有 LxU 的品牌词。

【市场数据】：
{market_data}

第一步：全维度分析 (视觉属性识别、痛点挖掘、排除逻辑) - 必须纯中文。
第二步：关键词清洗与打分。
第三步：输出二大模块
模块一：付费广告投放策略表。
【强制格式指令】：必须严格合并输出为一个统一的 Markdown 表格！绝对不允许改变表头格式或拆分表格。请将“核心出单词”、“精准长尾词”、“捡漏与痛点组”全部放入此表中，按总搜索量降序排列。
骨架严格如下：
| 序号 | 广告组分类 | 韩文关键词 | 中文翻译 | 月总搜索量 | 竞争度 | 推荐策略与说明 |
|---|---|---|---|---|---|---|
| 1 | 核心出单词 | ... | ... | ... | ... | ... |

模块二：否定关键词列表 (纯中文简述屏蔽的原因，并列出建议屏蔽的韩文词)。
"""

# ==========================================
# 2. Naver 数据抓取函数
# ==========================================
def clean_for_api(keyword: str) -> str:
    return re.sub(r"\s+", "", keyword)

def make_signature(method: str, uri: str, timestamp: str) -> str:
    message = f"{timestamp}.{method}.{uri}".encode("utf-8")
    signature = hmac.new(SECRET_KEY_BYTES, message, hashlib.sha256).digest()
    return base64.b64encode(signature).decode("utf-8")

def normalize_count(raw):
    if isinstance(raw, int): return raw
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith("<"): return 5
        if s.startswith(">"):
            num = s[1:].strip()
            return int(num) if num.isdigit() else 0
        s = s.replace(",", "")
        if s.isdigit(): return int(s)
    return 0

def fetch_naver_data(main_keywords, pb, st_text):
    all_rows = []
    total = len(main_keywords)
    for i, mk in enumerate(main_keywords, start=1):
        st_text.text(f"📊 Naver 拓词查询进度 [{i}/{total}]: {mk}")
        pb.progress(i / total)
        try:
            timestamp = str(int(time.time() * 1000))
            sig = make_signature("GET", "/keywordstool", timestamp)
            headers = {"X-Timestamp": timestamp, "X-API-KEY": NAVER_API_KEY, "X-Customer": NAVER_CUSTOMER_ID, "X-Signature": sig}
            res = requests.get(NAVER_API_URL, headers=headers, params={"hintKeywords": clean_for_api(mk), "showDetail": 1})
            if res.status_code == 200:
                data = res.json()
                for item in data.get("keywordList", [])[:8]: 
                    pc = normalize_count(item.get("monthlyPcQcCnt", 0))
                    mob = normalize_count(item.get("monthlyMobileQcCnt", 0))
                    
                    all_rows.append({
                        "Naver实际搜索词": item.get("relKeyword", ""),
                        "月总搜索量": pc + mob,
                        "竞争度": item.get("compIdx", "-"),
                        "AI溯源(原词)": mk
                    })
        except Exception:
            pass
        time.sleep(1) # API 频率保护
        
    df = pd.DataFrame(all_rows)
    if not df.empty:
        df = df.drop_duplicates(subset=["Naver实际搜索词"]).sort_values(by="月总搜索量", ascending=False)
    return df

# ==========================================
# 3. 主 UI 与全自动工作流
# ==========================================
st.title("⚡ LxU 自动化测品工厂 (单账号纯净版)")
st.info("💡 提示：如果遇到额度耗尽，请稍作等待，或手动在 Secrets 中更换 API Key。")

# 清理缓存按钮
if st.sidebar.button("🗑️ 清理云端垃圾文件"):
    try:
        count = 0
        for f in genai.list_files():
            genai.delete_file(f.name)
            count += 1
        st.sidebar.success(f"清理了 {count} 个缓存文件！")
    except Exception as e:
        st.sidebar.error(f"清理失败: {e}")

files = st.file_uploader("📥 请上传产品详情页 (强烈建议截图，保持在2MB内)", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)

if files and st.button("🚀 启动全自动闭环"):
    # 为了防止 404，使用标准的 1.5-flash 模型名称
    model = genai.GenerativeModel("models/gemini-1.5-flash")
    
    for file in files:
        st.divider()
        st.header(f"📦 正在自动处理产品：{file.name}")
        temp_path = f"temp_{file.name}"
        with open(temp_path, "wb") as f: f.write(file.getbuffer())
        
        # ------------------ 第一步：自动识图与提取 ------------------
        with st.status("🔍 第一步：AI 视觉提炼与本地化分析...", expanded=True) as s1:
            try:
                gen_file = genai.upload_file(path=temp_path)
                while gen_file.state.name == "PROCESSING":
                    time.sleep(2)
                    gen_file = genai.get_file(gen_file.name)
                
                res1 = model.generate_content([gen_file, PROMPT_STEP_1])
                with st.expander("👉 查看第一步完整报告 (已强制纯中文隔离)", expanded=False):
                    st.write(res1.text)
                
                # 强化版韩文长尾词提取（保留空格）
                match = re.search(r"\[LXU_KEYWORDS_START\](.*?)\[LXU_KEYWORDS_END\]", res1.text, re.DOTALL | re.IGNORECASE)
                kw_list = []
                if match:
                    raw_block = match.group(1)
                    raw_block = re.sub(r'[,，]', '\n', raw_block)
                    for line in raw_block.split('\n'):
                        clean_word = re.sub(r'[^가-힣\s]', '', line).strip()
                        clean_word = re.sub(r'\s+', ' ', clean_word)
                        if clean_word and clean_word not in kw_list:
                            kw_list.append(clean_word)
                else:
                    tail_text = res1.text[-800:]
                    for line in tail_text.split('\n'):
                        clean_word = re.sub(r'[^가-힣\s]', '', line).strip()
                        clean_word = re.sub(r'\s+', ' ', clean_word)
                        if clean_word and clean_word not in kw_list:
                            kw_list.append(clean_word)
                    kw_list = kw_list[:25]
                
                if kw_list:
                    s1.update(label=f"✅ 第一步完成！成功截获 {len(kw_list)} 个纯正韩文词组", state="complete")
                else:
                    s1.update(label="❌ 第一步提取失败，未能找到韩文", state="error")
                    continue 
            except Exception as e:
                s1.update(label=f"❌ AI 请求失败: {e}", state="error")
                st.error("请检查额度是否耗尽，或点击左侧清理云端缓存。")
                continue

        # ------------------ 第二步：自动触发 Naver 流量回测 ------------------
        with st.status("📊 第二步：连接 Naver 获取真实搜索数据 (自动跳转)...", expanded=True) as s2:
            pb = st.progress(0)
            status_txt = st.empty()
            
            df_market = fetch_naver_data(kw_list, pb, status_txt)
            
            if not df_market.empty:
                st.dataframe(df_market)
                target_count = len(kw_list)
                derived_count = len(df_market)
                s2.update(label=f"✅ 第二步完成！(目标词：{target_count} 个 ➡️ 衍生词：{derived_count} 个)", state="complete")
            else:
                s2.update(label="❌ 第二步失败，Naver 未返回有效数据", state="error")
                continue 

        # ------------------ 第三步：自动触发终极策略推演 ------------------
        with st.status("🧠 第三步：主客观数据融合，生成终极策略 (自动跳转)...", expanded=True) as s3:
            try:
                market_csv = df_market.to_csv(index=False)
                final_prompt = PROMPT_STEP_3.format(market_data=market_csv)
                
                res3 = model.generate_content([gen_file, final_prompt])
                st.markdown("### 🏆 LxU 终极测品策略报告")
                st.success(res3.text)
                
                s3.update(label="✅ 第三步完成！终极排兵布阵已生成", state="complete")
            except Exception as e:
                s3.update(label=f"❌ 第三步失败: {e}", state="error")

        # ------------------ 收尾与导出 ------------------
        os.remove(temp_path)
        try:
            genai.delete_file(gen_file.name)
        except:
            pass
            
        try:
            final_report = f"【LxU 产品测品全景报告：{file.name}】\n\n" + "="*40 + "\n[第一步：AI 视觉提炼 (纯中文)]\n" + res1.text + "\n\n" + "="*40 + "\n[第二步：Naver 客观搜索量]\n" + market_csv + "\n\n" + "="*40 + "\n[第三步：终极策略与广告分组]\n" + res3.text
            
            st.download_button(
                label=f"📥 一键下载 {file.name} 完整测品报告 (TXT)", 
                data=final_report, 
                file_name=f"LxU_自动测品全记录_{file.name}.txt"
            )
        except:
            pass
