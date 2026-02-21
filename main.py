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
import concurrent.futures
import io 

# ==========================================
# 0. 页面与 Secrets 配置
# ==========================================
st.set_page_config(page_title="LxU 测品工作流 (终极稳定版)", layout="wide")

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
# 1. 核心指令 (🚀 修复标题逗号与割裂断句问题)
# ==========================================
PROMPT_STEP_1 = """
你是一个在韩国市场拥有多年实战经验的电商运营专家，熟悉 Coupang 与 Naver SmartStore 的搜索机制和用户点击行为。你的整个运营团队都在中国，所以你必须遵守以下极其严格的【语言输出隔离规范】：
1. 所有的“分析过程”、“策略解释”等描述性质的文字，必须 100% 使用【简体中文】！绝对禁止使用韩文解释！
2. 只有“韩文关键词本身”、“韩语标题”和“商品好评的韩文原文”允许出现韩文，且必须全部附带对应的【中文翻译】。

--- 核心任务 ---
基于我提供的商品图片，生成能够提高点击率、语义自然、本土化表达强、突出卖点的商品标题，同时兼顾搜索匹配。

【品牌与通用规则】：
- 品牌名全部默认固定为：LxU
- 严禁使用夸张营销词（如 최고, 1위, 완벽 等）。
- 严禁在标题中使用任何标点符号断句（绝对不允许出现逗号 `,` 或 `，`、斜杠 `/`、加号 `+`、连字符 `-` 等）。
- 标题必须是一个一气呵成的、自然的【单一名词性短语】。绝对不允许把标题写成两个半句，也不能生硬地把“痛点词”和“产品词”用逗号割裂开来！
- 必须语义通顺，符合真实的韩国人搜索阅读习惯，避免机械堆砌关键词。

【💡 极度重要排版要求：一键复制功能】：
你生成的“纯韩文逗号隔开的后台关键词”以及“纯韩文评价”，必须单独放在 Markdown 代码块里面！
**警告：代码块开头只允许写三个反引号 ``` ，绝对不允许出现 ```text 或任何字母！代码块内只有纯韩文（如果是关键词加逗号），不允许有其他多余解释！**

第一部分：Coupang 专属优化 (偏转化与清晰表达)
1. 标题公式：LxU + 核心卖点 + 关键规格或属性 + 使用场景或解决问题点。核心词必须放前面。
-> 输出带中文翻译的标题（韩文标题务必放在上述要求的代码块里）。
2. 挖掘 20 个 Coupang 后台精准关键词（2~20字符）。
-> 必须以 Markdown 表格输出：【序号 | Coupang韩文关键词 | 中文翻译 | 纯中文策略解释】。
-> 表格下方，单独把这20个纯韩文词用逗号隔开，并务必放在上述要求的代码块里输出。

第二部分：Naver 专属优化 (偏搜索覆盖与曝光)
1. 标题规则：LxU + 核心词 + 修饰词与长尾词，加入更多用户搜索表达。
-> 输出带中文翻译的标题（韩文标题务必放在代码块里）。
2. 挖掘 20 个 Naver 后台扩展关键词（偏搜索扩展）。
-> 必须以 Markdown 表格输出：【序号 | Naver韩文关键词 | 中文翻译 | 纯中文策略解释】。
-> 表格下方，单独把这20个纯韩文词用逗号隔开，并务必放在代码块里输出。

第三部分：找精准长尾词做付费推广
广告组一为【核心出单词】，广告组二为【精准长尾关键词】，广告组三为【长尾捡漏组】。
输出格式为 Markdown 表格：【序号 | 广告组分类 | 韩文关键词 | 中文翻译 | 中文策略解释 | 预估流量 | 相关性评分(1-5)】。

第四部分：提供一个产品韩语名称用于内部管理（附带中文翻译）。

第五部分：按照产品卖点撰写10条商品韩文好评。
1. 先以 Markdown 表格形式排列：【序号 | 韩文评价原文 | 纯中文翻译 | 买家痛点分析】。
2. 表格下方，将这10条纯韩文评价原文按行隔开，单独放在 ``` 代码块中输出，方便一键复制。

第六部分：AI 主图生成建议：基于场景词用纯中文建议背景和构图。

【程序读取专属指令 - 极度重要】：
将上述所有生成的【韩文关键词】进行全面去重汇总，单列纵向列表输出，并且**必须放在以下两个标记之间**！每行只写一个韩文关键词，尽量不要带中文或序号。
[LXU_KEYWORDS_START]
(在这里填入去重后的纯韩文关键词)
[LXU_KEYWORDS_END]
"""

PROMPT_STEP_3 = """
【以下是市场核心搜索词及拓展词真实流量数据（按搜索量降序排列）】：
{market_data}

=======================================================
你是一位拥有10年实战经验的韩国 Coupang 跨境电商高级广告操盘手。整个团队都在中国，除韩文关键词外，所有解释分析必须用纯中文输出。绝对不要出现 LxU 的品牌词！
请你基于我提供的【产品原图】，深度分析上方的【市场流量数据】，严格完成以下任务：

第一步：建立“排雷标准”（必须纯中文）
简述该产品的真实材质、核心功能，并明确指出哪些词是绝对不能碰的红线（如材质相反、场景错误）。

第二步：基于第一步原词的“深化分类与提取”（极度重要，绝对不许偷懒！）
上方的流量数据中，包含了我们在最初期为你提供的【目标原词】（也就是你认为最符合图片的词）以及 Naver 拓展出的大词。
你**必须以第一步提炼的【目标原词】为核心基石进行深化**，结合高质量的 Naver 拓展词，挑选出 40-60 个最具转化价值的词。
你**必须、绝对**要把这些词分配到以下三个【明确的广告组】中，任何一组都绝对不允许为空！
- 【核心出单词】(1分)
- 【精准长尾词】(2分)
- 【捡漏与痛点组】(3分)

第三步：高价值付费广告投放策略表（直接填写真实数据，绝对不要输出省略号）
【强制表格格式】：
请严格使用以下 Markdown 表头结构输出表格。
**警告：不要输出任何省略号“...”或干扰虚线，请直接将挑选出的真实关键词数据一行一行填满表格！**
必须按三大分类的顺序展示（核心出单词 ➡️ 精准长尾词 ➡️ 捡漏与痛点组），且每个分类内部按“月总搜索量”降序排列！

| 序号 | 广告组分类 | 相关性评分 | 韩文关键词 | 月总搜索量 | 中文翻译 | 竞争度 | 推荐策略与说明 |
|---|---|---|---|---|---|---|---|

第四步：否定关键词列表 (Negative Keywords)
- 建议屏蔽的词：[用逗号隔开，从数据中挑出那些触碰红线、无购物意图的垃圾拓展词。必须至少列出 10 个真实的过滤词！]
- 屏蔽原因：[纯中文简述理由]
"""

# ==========================================
# 2. 强力引擎：安全生成与数据抓取
# ==========================================

def safe_generate(model, contents, max_retries=3):
    """包裹了重试逻辑的安全生成函数，彻底防止程序因 API 抽风卡死"""
    for attempt in range(1, max_retries + 1):
        try:
            res = model.generate_content(contents)
            return res.text 
        except Exception as e:
            if attempt < max_retries:
                time.sleep(3) 
            else:
                return f"❌ 严重错误：API 连续 {max_retries} 次无响应或被安全拦截，无法生成内容。详情：{str(e)}"

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

    def fetch_single(mk):
        rows = []
        try:
            timestamp = str(int(time.time() * 1000))
            sig = make_signature("GET", "/keywordstool", timestamp)
            headers = {"X-Timestamp": timestamp, "X-API-KEY": NAVER_API_KEY, "X-Customer": NAVER_CUSTOMER_ID, "X-Signature": sig}
            res = requests.get(NAVER_API_URL, headers=headers, params={"hintKeywords": clean_for_api(mk), "showDetail": 1}, timeout=8)
            if res.status_code == 200:
                data = res.json()
                for item in data.get("keywordList", []): 
                    pc = normalize_count(item.get("monthlyPcQcCnt", 0))
                    mob = normalize_count(item.get("monthlyMobileQcCnt", 0))
                    rows.append({
                        "Naver实际搜索词": item.get("relKeyword", ""),
                        "月总搜索量": pc + mob,
                        "竞争度": item.get("compIdx", "-"),
                        "AI溯源(原词)": mk
                    })
        except Exception:
            pass
        return rows

    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_mk = {executor.submit(fetch_single, mk): mk for mk in main_keywords}
        for future in concurrent.futures.as_completed(future_to_mk):
            mk = future_to_mk[future]
            completed += 1
            st_text.text(f"📊 Naver 极速并发拓词中 [{completed}/{total}]: {mk}")
            pb.progress(completed / total)
            try:
                all_rows.extend(future.result())
            except Exception:
                pass
            time.sleep(0.05) 
            
    df = pd.DataFrame(all_rows)
    if not df.empty:
        df = df.drop_duplicates(subset=["Naver实际搜索词"]).sort_values(by="月总搜索量", ascending=False)
    return df

# ==========================================
# 3. 主 UI 与全自动工作流
# ==========================================
st.title("⚡ LxU 自动化测品工厂 (终极防崩溃版)")
st.info("💡 提示：运行中如需紧急终止，请点击页面右上角自带的圆形 Stop 按钮。")

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

if files and st.button("🚀 启动全自动闭环", use_container_width=True):
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    for file in files:
        st.divider()
        st.header(f"📦 正在自动处理产品：{file.name}")
        temp_path = f"temp_{file.name}"
        with open(temp_path, "wb") as f: f.write(file.getbuffer())
        
        # 定义存储返回结果的变量，防崩溃保护
        res1_text = ""
        res3_text = ""
        kw_list = []
        market_csv = ""

        # ------------------ 第一步：自动识图与提取 ------------------
        with st.status("🔍 第一步：AI 视觉提炼与本地化分析...", expanded=True) as s1:
            try:
                gen_file = genai.upload_file(path=temp_path)
                while gen_file.state.name == "PROCESSING":
                    time.sleep(2)
                    gen_file = genai.get_file(gen_file.name)
                
                res1_text = safe_generate(model, [gen_file, PROMPT_STEP_1])
                
                if res1_text.startswith("❌"):
                    s1.update(label="❌ 第一步 AI 生成彻底失败", state="error")
                    st.error(res1_text)
                    continue
                
                with st.expander("👉 查看第一步完整报告 (已强制纯中文隔离)", expanded=False):
                    st.write(res1_text)
                
                # 强化版韩文长尾词提取（保留空格）
                match = re.search(r"\[LXU_KEYWORDS_START\](.*?)\[LXU_KEYWORDS_END\]", res1_text, re.DOTALL | re.IGNORECASE)
                if match:
                    raw_block = match.group(1)
                    raw_block = re.sub(r'[,，]', '\n', raw_block)
                    for line in raw_block.split('\n'):
                        clean_word = re.sub(r'[^가-힣\s]', '', line).strip()
                        clean_word = re.sub(r'\s+', ' ', clean_word)
                        if clean_word and clean_word not in kw_list:
                            kw_list.append(clean_word)
                else:
                    tail_text = res1_text[-800:]
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
                s1.update(label=f"❌ 本地系统逻辑错误: {e}", state="error")
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
                s2.update(label=f"✅ 第二步完成！已获取最新韩国市场客观数据 (目标词：{target_count} 个 ➡️ 衍生词：{derived_count} 个)", state="complete")
            else:
                s2.update(label="❌ 第二步失败，Naver 未返回有效数据", state="error")
                continue 

        # ------------------ 第三步：自动触发终极策略推演 ------------------
        with st.status("🧠 第三步：主客观数据融合，生成终极策略 (自动跳转)...", expanded=True) as s3:
            try:
                # 分离原词和拓展词，确保第一步的原词存活
                seed_df = df_market[df_market["Naver实际搜索词"].isin(kw_list)]
                expanded_df = df_market[~df_market["Naver实际搜索词"].isin(kw_list)].head(250)
                
                final_df = pd.concat([seed_df, expanded_df]).drop_duplicates(subset=["Naver实际搜索词"]).sort_values(by="月总搜索量", ascending=False)
                
                market_csv = final_df.to_csv(index=False)
                final_prompt = PROMPT_STEP_3.format(market_data=market_csv)
                
                res3_text = safe_generate(model, [gen_file, final_prompt])
                
                if res3_text.startswith("❌"):
                    s3.update(label="❌ 第三步 AI 生成彻底失败", state="error")
                    st.error(res3_text)
                else:
                    st.markdown("### 🏆 LxU 终极测品策略报告")
                    st.success(res3_text)
                    s3.update(label="✅ 第三步完成！终极排兵布阵已生成", state="complete")
            except Exception as e:
                s3.update(label=f"❌ 第三步系统逻辑错误: {e}", state="error")

        # ------------------ 收尾与导出 ------------------
        os.remove(temp_path)
        try:
            genai.delete_file(gen_file.name)
        except:
            pass
            
        try:
            # 1. 组装最终的 TXT 长文本报告
            final_report = f"【LxU 产品测品全景报告：{file.name}】\n\n" + "="*40 + "\n[第一步：AI 视觉提炼 (纯中文)]\n" + res1_text + "\n\n" + "="*40 + "\n[第二步：Naver 客观搜索量 (精炼合集)]\n" + market_csv + "\n\n" + "="*40 + "\n[第三步：终极策略与广告分组]\n" + res3_text
            
            # 2. Markdown 表格智能提取函数
            def parse_md_table(md_text, keyword):
                lines = md_text.split('\n')
                table_data = []
                is_table = False
                for line in lines:
                    line = line.strip()
                    if '|' in line and keyword in line:
                        is_table = True
                        table_data.append(line)
                        continue
                    if is_table:
                        if line.startswith('|') or line.endswith('|') or '|' in line:
                            if '---' not in line:
                                table_data.append(line)
                        else:
                            if len(line.strip()) > 0: 
                                break
                if not table_data:
                    return pd.DataFrame()
                parsed_rows = []
                for row in table_data:
                    cols = [col.strip() for col in row.split('|')]
                    if cols and not cols[0]: cols = cols[1:]   
                    if cols and not cols[-1]: cols = cols[:-1] 
                    parsed_rows.append(cols)
                if len(parsed_rows) > 1:
                    return pd.DataFrame(parsed_rows[1:], columns=parsed_rows[0])
                return pd.DataFrame()

            # 📌 Sheet 1：登品标题精准提取 
            raw_titles = []
            for line in res1_text.split('\n'):
                line_clean = line.strip()
                # 必须包含LxU，且绝不包含这些干扰词
                if 'LxU' in line_clean and not any(x in line_clean for x in ['公式', '规则', '卖点', '核心词', '翻译', '中文']):
                    # 清理掉可能存在的 markdown 符号，如 ` 或 *
                    clean_t = re.sub(r'```[a-zA-Z]*', '', line_clean)
                    clean_t = clean_t.strip('`*>- \t')
                    # 终极校验：清理完符号后，它必须是以 LxU 开头的！
                    if clean_t.startswith('LxU') and clean_t not in raw_titles:
                        raw_titles.append(clean_t)
            
            coupang_title = raw_titles[0] if len(raw_titles) > 0 else "未提取到 Coupang 标题，请查阅完整TXT"
            naver_title = raw_titles[1] if len(raw_titles) > 1 else "未提取到 Naver 标题，请查阅完整TXT"

            kw_lines = []
            for line in res1_text.split('\n'):
                if ('，' in line or ',' in line) and '|' not in line and re.search(r'[가-힣]', line):
                    if line.count(',') + line.count('，') >= 5: 
                        clean_kw = re.sub(r'```[a-zA-Z]*', '', line).strip()
                        clean_kw = clean_kw.strip('`').strip()
                        if clean_kw and clean_kw not in kw_lines:
                            kw_lines.append(clean_kw)
            
            coupang_kws = kw_lines[0] if len(kw_lines) > 0 else "未提取到 Coupang 关键词，请查阅完整TXT"
            naver_kws = kw_lines[1] if len(kw_lines) > 1 else "未提取到 Naver 关键词，请查阅完整TXT"

            df_sheet1 = pd.DataFrame({
                "信息维度": ["Coupang 标题", "Coupang 后台关键词", "Naver 标题", "Naver 后台关键词"],
                "提炼内容": [coupang_title, coupang_kws, naver_title, naver_kws]
            })

            # 📌 Sheet 2 & 3：提取表格
            df_comments = parse_md_table(res1_text, "韩文评价原文")
            df_ads = parse_md_table(res3_text, "广告组分类")

            # 3. 写入内存 Excel
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
                df_sheet1.to_excel(writer, index=False, sheet_name='登品标题')
                
                if not df_comments.empty:
                    df_comments.to_excel(writer, index=False, sheet_name='评论区内容')
                else:
                    pd.DataFrame([{"提示": "未找到规范的评价表格，请查阅下方TXT报告"}]).to_excel(writer, index=False, sheet_name='评论区内容')
                
                if not df_ads.empty:
                    df_ads.to_excel(writer, index=False, sheet_name='广告投放关键词')
                else:
                    pd.DataFrame([{"提示": "未找到规范的广告策略表，请查阅下方TXT报告"}]).to_excel(writer, index=False, sheet_name='广告投放关键词')

            excel_data = excel_buffer.getvalue()

            # 4. 在界面底部显示双下载按钮 (TXT 和 Excel)
            st.divider()
            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    label=f"📝 下载完整分析报告 (TXT)", 
                    data=final_report, 
                    file_name=f"LxU_自动测品全记录_{file.name}.txt",
                    use_container_width=True
                )
            with col2:
                st.download_button(
                    label=f"📊 下载结果表格 (Excel)", 
                    data=excel_data, 
                    file_name=f"LxU_自动测品数据表_{file.name}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
        except Exception as e:
            st.error(f"构建导出文件时发生错误: {e}")
