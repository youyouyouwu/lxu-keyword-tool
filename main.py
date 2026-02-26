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
import zipfile
import markdown  # 🚀 新增：用于将文本渲染为极美网页排版

# ✅ 喂料包（切片+CSV）写入（先写到单独zip，再塞进master_zip）
from material_pack import PackConfig, write_feed_to_master_zip

# ==========================================
# 0. 页面与 Secrets 配置
# ==========================================
st.set_page_config(page_title="LxU 测品策略生成器", layout="wide")

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
# 1. 核心指令
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
- 标题中【绝对不要使用任何标点符号】，词语之间用空格自然隔开即可。
- 标题必须【语句通顺自然】，符合真实韩国本土买家的搜索和阅读习惯。

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

第三部分：基于锚点闭环的“付费推广查量种子词/模板”（此阶段无真实流量数据）

重要定位：
- 本阶段的输出用于下一步送入 Naver API 做扩展与查量（种子词/组合模板）。
- 不允许输出“最终可投结论”，不允许编造具体流量数值。
- “预估流量”只能填：高 / 中 / 低（代表查量优先级，不是实际流量）。

A) 先建立类目锚点闭环（必须先输出，且简洁）
1) 主体锚点（1~3个，韩文+中文）：必须是商品实体名词
2) 必须属性锚点（3~8个，韩文+中文）：决定类目边界（规格/结构/适配对象/接口等）
3) 排他红线（至少8个，中文即可）：与本产品绝对冲突或明显跨类目的方向
4) 高风险黑名单（至少10个，中文即可）：行业词/上位泛词/服务词（例：시공, 공사, 수리, 업체, 자재, 공구 등）

B) 关键词生成范围（强制约束）
你只能输出两类内容：
- 类1：详情页明确出现或可直接同义替换的“主体词/属性词”
- 类2：由【主体锚点 + 必须属性锚点】拼接形成的“查询组合模板”
禁止：
- 生成与主体无关的行业词/服务词/泛词
- 拆分关键词词根后再推导、再重组生成新语义
- 仅输出纯场景词而不含主体（如 욕실/주방 单独出现）

C) 三组广告结构（本阶段仅作为“查量优先级分组”，不是最终投放组）
广告组一：【核心出单词】（优先查量）
- 以主体锚点/主体同义词为主
- 若主体偏泛（如 수전/밸브 等），必须用“必须属性或适配对象”形成组合模板
- 输出 5~8 个

广告组二：【精准长尾关键词】（主力查量）
- 主体 + 必须属性（规格/结构/接口/适配对象/连接方式）
- 输出 8~15 个

广告组三：【长尾捡漏组】（补充查量）
- 主体 + 可选属性 + 场景（仅限详情页明确出现的场景）
- 输出 8~15 个

D) 输出格式（必须严格执行）
用 Markdown 表格输出，表头必须中文：

| 序号 | 广告组分类 | 韩文关键词（候选/模板） | 中文翻译 | 中文策略解释 | 预估流量（高/中/低） | 相关性评分(1-5) |

填写要求：
- 相关性评分只根据“锚点闭环匹配度”给分：完全命中主体+必须属性=高分
- 中文策略解释 ≤ 20字，说明该词属于主体词/主体+结构/主体+适配对象/主体+规格等
- 若某词为“主体泛词”，策略解释中必须标注“需属性组合”
- 禁止出现品牌名
- 禁止使用“/”连接关键词

第四部分：提供一个产品韩语名称用于内部管理（附带中文翻译）。

第五部分：按照产品卖点撰写5条商品韩文好评。
1. 先以 Markdown 表格形式排列：【序号 | 韩文评价原文 | 纯中文翻译 | 买家痛点分析】。
2. 表格下方，将这5条纯韩文评价原文按行隔开，单独放在 ``` 代码块中输出，方便一键复制。

第六部分：AI 主图生成建议：基于场景词用纯中文建议背景和构图。

【程序读取专属指令 - 极度重要】：
将上述所有生成的【韩文关键词】进行全面去重汇总，单列横向输出，并且**必须放在以下两个标记之间**！
⚠️ 警告：这里的关键词之间【必须使用英文逗号 (,) 隔开】！绝对不允许只用空格连在一起！
[LXU_KEYWORDS_START]
关键词1,关键词2,关键词3
[LXU_KEYWORDS_END]
"""

PROMPT_STEP_3 = """
【以下是市场核心搜索词及拓展词真实流量数据】：
{market_data}

=======================================================
你是一位拥有10年实战经验的韩国 Coupang 跨境电商高级广告操盘手。整个团队都在中国，除韩文关键词外，所有解释分析必须用纯中文输出。绝对不要出现 LxU 的品牌词！
请你基于我提供的【产品原图】，深度分析上方的【市场流量数据】，严格完成以下任务：

第一步：产品全维度深度解析与排雷（必须纯中文）
为了确保你对产品的理解绝对准确，并为后续广告词打分提供事实依据，请在报告最开头明确输出以下解析：
1. 产品核心属性：精准提取该产品的真实材质、外观形态、核心卖点及适用场景。
2. 买家痛点挖掘：深度分析目标人群购买该产品是为了解决什么痛点？
3. 绝对红线（排雷标准）：明确列出哪些属性、材质或场景是与本产品**绝对冲突**的（如产品是塑料，红线就是金属；或者不相关的功能词等），并在后续选词中坚决屏蔽它们！

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
        df = df.drop_duplicates(subset=["Naver实际搜索词"])

        seed_no_space = [str(k).replace(" ", "") for k in main_keywords]
        df['is_seed'] = df['Naver实际搜索词'].apply(lambda x: str(x).replace(" ", "") in seed_no_space)

        df.insert(1, '词组属性', df['is_seed'].apply(lambda x: '🎯 目标原词' if x else '💡 衍生拓展词'))
        df = df.sort_values(by=["is_seed", "月总搜索量"], ascending=[False, False])
        df = df.drop(columns=['is_seed'])

    return df

# ==========================================
# 3. 主 UI 与全自动工作流
# ==========================================
st.title("⚡ LxU 测品策略生成器")
st.info("💡 提示：运行中如需紧急终止，请点击页面右上角自带的圆形 Stop 按钮。")

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

    master_zip_buffer = io.BytesIO()
    master_zip = zipfile.ZipFile(master_zip_buffer, 'w', zipfile.ZIP_DEFLATED)

    for file in files:
        st.divider()
        st.header(f"📦 正在自动处理产品：{file.name}")
        temp_path = f"temp_{file.name}"
        with open(temp_path, "wb") as f:
            f.write(file.getbuffer())

        res1_text = ""
        res3_text = ""
        kw_list = []
        market_csv = ""
        folder_name = os.path.splitext(file.name)[0]

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

                match = re.search(r"\[LXU_KEYWORDS_START\](.*?)\[LXU_KEYWORDS_END\]", res1_text, re.DOTALL | re.IGNORECASE)
                if match:
                    raw_block = match.group(1)
                    raw_block = re.sub(r'[，\n、|]', ',', raw_block)
                    for kw in raw_block.split(','):
                        clean_word = re.sub(r'[^가-힣a-zA-Z0-9\s]', '', kw).strip()
                        clean_word = re.sub(r'\s+', ' ', clean_word)
                        if clean_word and clean_word not in kw_list:
                            kw_list.append(clean_word)
                else:
                    tail_text = res1_text[-800:]
                    tail_text = re.sub(r'[，\n、|]', ',', tail_text)
                    for kw in tail_text.split(','):
                        clean_word = re.sub(r'[^가-힣a-zA-Z0-9\s]', '', kw).strip()
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
                seed_df = df_market[df_market["词组属性"] == '🎯 目标原词']
                expanded_df = df_market[df_market["词组属性"] == '💡 衍生拓展词'].head(250)

                final_df = pd.concat([
                    seed_df.sort_values(by="月总搜索量", ascending=False),
                    expanded_df.sort_values(by="月总搜索量", ascending=False)
                ]).drop_duplicates(subset=["Naver实际搜索词"])

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

        # ------------------ 收尾与文件生成 (🚀 升级为高定网页版报告) ------------------
        os.remove(temp_path)
        try:
            genai.delete_file(gen_file.name)
        except:
            pass

        try:
            # === 解析与提炼 ===
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
                    if cols and not cols[0]:
                        cols = cols[1:]
                    if cols and not cols[-1]:
                        cols = cols[:-1]
                    parsed_rows.append(cols)
                if len(parsed_rows) > 1:
                    return pd.DataFrame(parsed_rows[1:], columns=parsed_rows[0])
                return pd.DataFrame()

            raw_titles = []
            for line in res1_text.split('\n'):
                line_clean = line.strip()
                if 'LxU' in line_clean and not any(x in line_clean for x in ['公式', '规则', '卖点', '核心词', '翻译', '中文']):
                    clean_t = re.sub(r'```[a-zA-Z]*', '', line_clean)
                    clean_t = clean_t.strip('`*>- \t')
                    if clean_t.startswith('LxU') and clean_t not in raw_titles:
                        raw_titles.append(clean_t)

            coupang_title = raw_titles[0] if len(raw_titles) > 0 else "未提取到 Coupang 标题，请查阅全景报告"
            naver_title = raw_titles[1] if len(raw_titles) > 1 else "未提取到 Naver 标题，请查阅全景报告"

            kw_lines = []
            for line in res1_text.split('\n'):
                if ('，' in line or ',' in line) and '|' not in line and re.search(r'[가-힣]', line):
                    if line.count(',') + line.count('，') >= 5:
                        clean_kw = re.sub(r'```[a-zA-Z]*', '', line).strip()
                        clean_kw = clean_kw.strip('`').strip()
                        if clean_kw and clean_kw not in kw_lines:
                            kw_lines.append(clean_kw)

            coupang_kws = kw_lines[0] if len(kw_lines) > 0 else "未提取到 Coupang 关键词，请查阅全景报告"
            naver_kws = kw_lines[1] if len(kw_lines) > 1 else "未提取到 Naver 关键词，请查阅全景报告"

            df_sheet1 = pd.DataFrame({
                "信息维度": ["Coupang 标题", "Coupang 后台关键词", "Naver 标题", "Naver 后台关键词"],
                "提炼内容": [coupang_title, coupang_kws, naver_title, naver_kws]
            })

            df_comments = parse_md_table(res1_text, "韩文评价原文")
            df_ads = parse_md_table(res3_text, "广告组分类")

            # === 写入 Excel (内存) ===
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
                df_sheet1.to_excel(writer, index=False, sheet_name='登品标题')
                if not df_comments.empty:
                    df_comments.to_excel(writer, index=False, sheet_name='评论区内容')
                else:
                    pd.DataFrame([{"提示": "未找到规范的评价表格"}]).to_excel(writer, index=False, sheet_name='评论区内容')
                if not df_ads.empty:
                    df_ads.to_excel(writer, index=False, sheet_name='广告投放关键词')
                else:
                    pd.DataFrame([{"提示": "未找到规范的广告策略表"}]).to_excel(writer, index=False, sheet_name='广告投放关键词')
            excel_data = excel_buffer.getvalue()

            # === 🚀 写入精美 HTML 网页报告 (完美替代容易乱码的 Word) ===
            css_style = """
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Malgun Gothic", "Microsoft YaHei", sans-serif; padding: 40px; max-width: 1000px; margin: auto; line-height: 1.6; color: #333; background-color: #f4f6f9; }
                .container { background: #ffffff; padding: 40px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
                h1 { color: #1E3A8A; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; text-align: center; }
                h2 { color: #2563eb; margin-top: 30px; }
                h3 { color: #475569; }
                table { border-collapse: collapse; width: 100%; margin: 20px 0; font-size: 14px; border-radius: 8px; overflow: hidden; }
                th, td { border: 1px solid #e2e8f0; padding: 12px 15px; text-align: left; }
                th { background-color: #f8fafc; color: #1e293b; font-weight: 600; }
                tr:nth-child(even) { background-color: #f1f5f9; }
                pre { background-color: #1e293b; padding: 20px; border-radius: 8px; overflow-x: auto; color: #f8fafc; font-family: monospace; }
                code { background-color: #e2e8f0; padding: 2px 6px; border-radius: 4px; color: #b91c1c; font-size: 0.9em; }
                .print-btn { display: block; width: 200px; margin: 20px auto; padding: 10px; background-color: #2563eb; color: white; text-align: center; text-decoration: none; border-radius: 5px; font-weight: bold; cursor: pointer; border: none; }
                @media print { .print-btn { display: none; } body { background-color: white; } .container { box-shadow: none; padding: 0; } }
            </style>
            """

            html_part1 = markdown.markdown(res1_text, extensions=['tables', 'fenced_code'])
            html_part3 = markdown.markdown(res3_text, extensions=['tables', 'fenced_code'])

            html_content = f"""
            <!DOCTYPE html>
            <html lang="zh-CN">
            <head>
                <meta charset="utf-8">
                <title>LxU 测品全景报告 - {folder_name}</title>
                {css_style}
            </head>
            <body>
                <div class="container">
                    <button class="print-btn" onclick="window.print()">🖨️ 保存为高质量 PDF</button>
                    <h1>📊 LxU 测品全景报告</h1>
                    <p style="text-align: center; color: #64748b;">报告归属产品：{folder_name} | 生成日期：自动记录</p>

                    <h2>🔍 第一步：AI 视觉提炼与本地化分析</h2>
                    {html_part1}

                    <hr style="border: 1px dashed #cbd5e1; margin: 40px 0;">

                    <h2>🧠 第三步：产品深度解析与终极广告策略</h2>
                    {html_part3}
                </div>
            </body>
            </html>
            """

            # ✅ 生成 FEED_{folder}.zip（在内存里先打一个zip，再写入 master_zip）
            feed_buffer = io.BytesIO()
            feed_zip = zipfile.ZipFile(feed_buffer, 'w', zipfile.ZIP_DEFLATED)

            pack_cfg = PackConfig(
                target_w=1400,
                max_h=1600,
                min_h=900,
                overlap=0.12,
                skip_blank=True,
                pdf_scale=2.0
            )

            write_feed_to_master_zip(
                master_zip=feed_zip,  # ⚠️ 这里是 feed_zip，不是 master_zip
                folder_name=folder_name,
                uploaded_filename=file.name,
                uploaded_bytes=file.getvalue(),
                cfg=pack_cfg,
                kw_list=kw_list,
                df_market=df_market,
                final_df=final_df,
                res1_text=res1_text,
                res3_text=res3_text
            )

            feed_zip.close()

            master_zip.writestr(
                f"{folder_name}/FEED_{folder_name}.zip",
                feed_buffer.getvalue()
            )

            # === 将生成的 Excel 和 HTML 网页写入主 ZIP 包 ===
            master_zip.writestr(f"{folder_name}/LxU_数据表_{folder_name}.xlsx", excel_data)
            master_zip.writestr(f"{folder_name}/LxU_视觉报告_{folder_name}.html", html_content.encode('utf-8'))

            st.success(f"📦 【{file.name}】 处理完毕！已打包存入内存。")

        except Exception as e:
            st.error(f"处理 {file.name} 构建导出文件时发生错误: {e}")

    # ==========================================
    # 4. 循环结束后，提供统一大压缩包下载
    # ==========================================
    master_zip.close()
    if files:
        st.divider()
        st.markdown("### 🎉 全部产品处理完成！")
        st.download_button(
            label="📥 一键下载全部结果 (ZIP 压缩包)",
            data=master_zip_buffer.getvalue(),
            file_name="LxU_批量测品结果合集.zip",
            mime="application/zip",
            use_container_width=True
        )
