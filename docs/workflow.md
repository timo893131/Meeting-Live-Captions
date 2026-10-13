# 開發工作流與 Agent／Skill 分工

這是本專案的可重用工作程序。AGENTS.md 是共通規則與路由；.agents/skills/ 中的七個 Skill 是按需求載入的程序。Skill 不會自行安裝模型、爬取資料、建立其他代理或發布網站。

## 現況與優先順序

目前已有個人／廣播字幕、密碼／邀請／QR 加入、詞彙校正與 Cloudflare 版本；使用者回報一般真實語音辨識效果不錯。功能雛型與公開房間 smoke 曾通過，但尚沒有代表性固定音訊資料集或量化的 CER baseline，不能把「感覺準」當作已達特定準確率。

優先順序預設如下；新的明確需求優先於本排序：

| 階段 | 工作 | 完成條件 |
| --- | --- | --- |
| P0 現場可用 | 字幕閱讀、觀眾加入、錯誤狀態、重連及房間權限 | 核心角色能完成操作，受影響的功能證據通過 |
| P1 可量測 | 小型授權評估集、詞彙正確／誤改與延遲 baseline | 固定資料版本、指標定義及可重跑報告 |
| P2 低成本改善 | 詞彙表、prompt／音源改善，或比較輕量 ASR | 對 validation 有改善，一般中文及延遲沒有超出既定退步門檻 |
| P3 模型實驗 | 在 P2 仍有明確不足時考慮 Whisper／LoRA | 訓練資料、算力、預算、baseline 齊全且候選通過回測 |
| P4 發布與監測 | 小規模真人試用、正式驗證、回退與後續評估 | 有部署版本、實際網站證據、問題記錄與上一版回退資訊 |

不要求所有任務走完所有階段。UI 修正不等待訓練資料；來源登錄不會自動觸發爬蟲或 GPU 訓練。

## 任務分類與依賴

| 類別／主 Skill | 典型需求 | 輸入 | 產物 | 完成／移交依據 |
| --- | --- | --- | --- | --- |
| UI／meeting-ui-ux | 大字、深色、長輩操作、手機字幕、無障礙 | 使用角色、情境、問題 | 前端 diff、代表性流程／畫面 | 包含受影響的錯誤、離線、長文、鍵盤狀態 |
| REALTIME／meeting-realtime | 權限、同步、斷線、重複字幕、房間保存 | runtime、事件、重現案例 | 程式、契約、功能案例 | 受影響的 Node／Workers 行為與負向案例 |
| ACQUIRE／church-data-acquisition | 爬取詞彙、匯入講道、取得授權音檔 | 來源、用途、規模、權利 | source register、原始 manifest | 非空樣本、來源／hash／權利範圍可查 |
| PREPARE／speech-data-preparation | resample、分段、逐字稿、去重、split | 合法來源資料、引擎規格 | 轉換版本、人工稿、split／品質報告 | 權利符合用途、schema／對齊／洩漏檢查通過 |
| EVALUATE／speech-evaluation | 詞彙回測、模型比較、歷史講道測試 | 固定資料、baseline、候選、門檻 | 評估 report、run metadata | 分組指標、限制、是否採用候選的理由 |
| TRAIN／speech-finetuning | Whisper 全微調、LoRA、量化匯出 | 訓練集、隔離評估、GPU／預算 | 配置、checkpoint、模型卡 | 不是僅 loss 下降；匯出模型也需評估 |
| RELEASE／meeting-verification-release | 功能驗證、部署、事故處理、回退 | diff、範圍、版本、目標 | 驗證／發布證據、回退資訊 | 本機、打包、部署、真人 ASR 證據分開 |

依賴流程通常是 ACQUIRE → PREPARE → EVALUATE。TRAIN 需要前述基準與明確訓練要求；TRAIN 的結果再回到 EVALUATE。UI／REALTIME 可獨立進行，跨事件契約時協作。驗證按變更風險執行，不是在每個步驟重跑全套。

## 共通生命周期

1. **定位**：讀使用者目標、git status、相關程式；說明交付範圍與合理預設。
2. **分類**：選一個主 Skill，只有實際跨界才讀第二個；先前已讀且未變更的內容不用反覆讀。
3. **驗收**：決定能證明工作有效的案例、資料／版本、指標與門檻。大型任務用 task-card，簡單任務用短說明即可。
4. **執行**：先做便宜、能排除錯誤的檢查；再進入完整轉換／訓練。需要外部前置條件時完成不受阻部分。
5. **驗證**：原命令的退出狀態、有效測試數及產物，區分失敗原因。停在首個失敗或只保存計畫，不是完成。
6. **交付**：簡短結果＋證據；有真正需要延續的決策才保存文件／交接。已有授權的工作持續完成，不為可逆例行任務新增批准門檻。

工作狀態：ready、in_progress、blocked、verified、released。blocked 必須寫出具體缺少的前置條件；verified 是指定範圍通過，不代表已發布。另以 passed／failed／skipped／unrun 記錄每個檢查。

## token 與 context 使用

| 控制 | 具體方式 | 避免 |
| --- | --- | --- |
| 一次定位 | rg 找檔案／符號，再讀相關函式及上下文 | 每次 cat 全專案 |
| 漸進載入 | AGENTS＋主 Skill；相關 reference 有需要才讀 | 一開始讀七個 Skills／所有文檔 |
| 成果重用 | 引用既有命令與對應版本、只補受影響檢查 | 沒有新資訊就重跑／重讀 |
| 輸出精簡 | 工具输出限定必要片段，完整資料留在 artifact | 將整個語料、音訊、完整日誌或 lockfile 加入對話 |
| 任務拆分 | 按可驗證成果分段，留短的決策與交接摘要 | 反覆改寫長計畫，或用多代理處理一句文案 |
| 可追踪成本 | 有 tool metadata 就記 token／時間／費用與來源；否則 unavailable | 用猜的數字宣稱 token 節省 |

多代理只有明確授權才使用，並要求獨立子任務、清楚檔案擁有範圍與短成果摘要。多代理可能增加總 token；以品質／總成本測量，而不是假定越多越快。

建議觀察：有效交付的總 token／時間、重複讀檔／重跑次數、一次驗收率與返工原因。最初沒有歷史數值，先記錄可取得數據，不設定虛假的百分比目標。

## 資料契約、爬取與轉換

本機預設 data/raw、data/processed、data/manifests；實驗產物 artifacts/<run_id>；模型 models/<model_version>。這些路徑預設不提交 Git，不代表自動獲准存入雲端。真實資料要依核准儲存位置、用途與期限處理，Git 僅提交去識別的流程／schema／必要摘要。

- source register 至少記 source_id、來源／版本、license／權利依據、同意記錄、允許用途、取得方法、保存期限。robots 是爬取規則，不是著作權或訓練同意。
- 純文字／詞彙來源使用 source-register.example.csv；glossary-candidate.example.json 是待審查候選，不會直接取代目前 glossary.js／瀏覽器校正表。正反例、來源與回測通過後才套用規則。
- 音訊 manifest 一段一列 JSONL，採 docs/schemas/audio-segment.schema.json 的結構。每段可追溯 source／原始 hash／群組／轉換／reference。
- schema 只驗證格式，不能證明音檔存在、hash 正確、duration／timestamp 對齊、權利合法、逐字稿真實或沒有資料洩漏；這些需獨立檢查。
- 範例 JSON 是占位示範，hash、權利和時間可以 null／pending，不是可直接訓練的真實 manifest。
- 同場／同來源衍生資料同一 split。若要宣稱對新講員有效，需 speaker-disjoint 評估；split 策略與例外必須明寫。
- 驗收排除資料必須有原因及數量；增強不寫回 raw。訓練用轉換、評估正規化與對外繁體字幕處理分開版本化。

## 詞彙／ASR 指標與回測

| 指標 | 定義與證據 | 注意事項 |
| --- | --- | --- |
| CER | (替換 S＋刪除 D＋插入 I)／reference 字符數 N；報 aggregate 與 cohort | 固定 normalizer，N=0 標 undefined；不能任意平均每段百分比 |
| 詞彙正確率 | reference 標註詞彙出現位置中，候選對齊辨識正確的次數／可評出現次數 | 聖經人名、書卷、經文數字分組；不只做全文 contains |
| 校正誤改率 | 原先正確而被詞彙表改錯的已標註位置／原先正確的可評位置 | 保存 raw／corrected，納入一般中文同音情境 |
| 暫定／確定延遲 | 先定義音訊起點／結尾至字幕產生的測量點，再報 p50／p95 | 記清同一／校正時鐘、browser 與測量方式 |
| 同步延遲 | 房主發送至觀眾收到的差值 | 不同步時鐘不可直接相減；記 network 與裝置 |
| RTF | 辨識運算時間／音訊時長 | RTF<1 是不累積音訊處理落後的必要參考，不代表達到端到端延遲要求 |
| 靜音幻覺／資源 | 固定無語音樣本的錯誤輸出、記憶體、RTF／用量及費用 | 只報測量得到的值；Workers 免費額度與 ASR 費用分開 |

固定回測集覆蓋一般國語、教會詞彙、不同講員／收音、噪音、重疊、靜音、較長經文／數字。初期由少量人工核對開始，資料數不足時明說不確定性。

候選只在事先約定的品質／誤改／延遲／資源門檻內採用；門檻由真實 baseline、使用情境和預算決定，不預先聲稱 99% 或憑空設定品質。詞彙、提示、VAD／chunk 和量化都是候選變因，需保存版本。

開發／調参使用 validation。最終 sealed test 只做已選定候選驗收；若用結果改詞彙或挑 checkpoint，該集已不再是未見測試，需記錄並換新封存集。歷史聚會回測不是拿訓練場次重算一次。

## 發布、事故與回退

- 發布記錄 actual repo／branch、commit、Worker 名稱、公開 URL、deployment ID（可取得時）、時間及檢查結果。一鍵部署可能是副本，不靠原 repo 的 main 推定正式版。
- local check、deploy dry-run、Cloudflare build、公開房間 smoke、真人語音是不同證據。前項通過不能替代後項。
- 雲端環境可能需平台代理；WSS 也需相對應 agent。保留 TLS，不輸出代理認證。未知網路政策不直接取代 allowlist。
- 公開驗證先用合成字幕，測完刪房；壓力測試、私人音檔上傳或收費算力需在任務既有授權與範圍內。
- 嚴重權限／同步／品質回歸保留 baseline 或回退。Workers 儲存／migration 與模型格式變更需先核對上一版相容性。
- 監測只記必要狀態、時間及計數，預設不記音訊、私人字幕、密碼或邀請憑證。故障先提供可繼續使用的清楚狀態，再診斷原因。

## 文件與模板的使用方式

| 文件 | 何時使用 |
| --- | --- |
| AGENTS.md | 共通規則；進入專案及新任務 |
| .agents/skills/*/SKILL.md | 匹配任務的可操作流程；不必全讀 |
| docs/templates/task-card.md | 跨步驟／需交接的任務 |
| docs/templates/evaluation-report.md、eval-run.example.json | 詞彙／模型候選比較與回測 |
| docs/templates/source-register.example.csv、glossary-candidate.example.json | 純文字／詞彙的來源與候選整理 |
| docs/templates/audio-segment.example.json、docs/schemas/audio-segment.schema.json | 資料 manifest 的占位範例與格式 |
| docs/templates/model-card.md | 實際訓練／模型候選的用途與限制 |

第一次加入專案時，支援 repo .agents/skills 的 Codex 應可發現這七個技能；已開啟會話的列表不一定立即更新。可在新任務確認是否列出；若未自動發現，依 AGENTS 路由直接讀相對路徑，不假裝技能已被平台註冊。

範例需求：「用 $meeting-ui-ux 改善手機觀看字幕」、「用 $speech-evaluation 比較新詞彙表與基準」、「用 $church-data-acquisition 整理可供內部評估的授權來源」。實際訓練需明確指定資料、環境與預算，不能只寫「優化準確率」就啟動付費訓練。
