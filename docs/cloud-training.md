# Google Colab 雲端 GPU 微調

使用者已選擇 Google Colab，先嘗試免費 GPU。資料整理與QC可在本環境做，模型微調在Colab GPU執行；Cloudflare只保留網站／房間功能。現有網站仍用WebSpeech；此LoRA產物之後需接入自有Whisper辨識服務，才會影響網站字幕。Colab不保證免費GPU、型號或連線時長，沒有自動建立付費機器。

[在 Colab 開啟 Notebook](https://colab.research.google.com/github/timo893131/Meeting-Live-Captions/blob/main/notebooks/cloud_whisper_lora.ipynb)

## 實作狀態

已準備 Notebook、固定版本依賴、雲端設定、資料gate、LoRA訓練及checkpoint續跑程式。資料gate測試與Notebook語法檢查已在本機完成；**GPU訓練、模型下載、checkpoint續跑與訓練成效尚未在Colab實跑**，不能宣稱雲端訓練流程已驗證成功。

目前收集的pilot沒有正式train-ready配對資料；先前教會腳本修訂也不是完整人工逐字稿。切換雲端只改變運算位置，不會把pending資料升格成訓練資料。Colab有獨立網路，Codex環境的proxy403不表示它一定同樣受阻，但也不保證來源可下載；Notebook提供預設啟用、受授權檢查與容量限制的15段收集cell。

## 執行順序

1. 開啟Notebook並選擇GPU執行階段；建議約16GiB可用顯存，實際以Notebook列出的硬體為準。
2. 複製repo、安裝 training/requirements-colab.txt，保留Colab已配對CUDA的PyTorch。首次run記錄實際程式commit、模型精確revision與主要套件版本；resume不得靜默換版本。
3. 掛載自己的Drive。預設 WORKFLOW_STAGE=collect，嘗試15段並將原音、工作副本與報告存到 `meeting-live-captions/pilots/taiwan-mandarin-v1`，完整檔cache可續抓。正式人工審核資料另放 `meeting-live-captions/data`，訓練輸出放 `meeting-live-captions/runs/<run-id>`；不互相覆寫。
4. 校對與分組完成後，將 WORKFLOW_STAGE 改為train並執行正式資料檢查；collect階段不提前檢查缺少的訓練manifest。通過後才將Notebook中的 `RUN_TRAINING` 改為True，預設只跑20 steps的smoke。沒有通過時，訓練CLI也會再次拒絕，不存在略過gate的選項。
5. checkpoint每10步保存到Drive，並在validation以CER選擇已保存候選；adapter／processor與報告分attempt保存。完成run不覆寫；中斷後指定原RUN_DIR及RESUME=True，且需已存在checkpoint。若尚未存第一個checkpoint，使用新的run目錄重跑。

目前雲端trainer使用原始 `openai/whisper-small`，不使用CTranslate2 int8作反向傳播。首次由HF解析commit並查模型license（MIT／Apache-2.0），固定後寫run-lock。Whisper 16k mono PCM16→feature extractor→small的80-bin log-mel及token labels，按模型token上限拒絕過長稿，不靜默截斷。全精度base保留於GPU，訓練採FP16 autocast，LoRA只更新q_proj/v_proj；不依賴bitsandbytes／4bit。

## 正式資料格式

`manifests/train.jsonl`、`validation.jsonl`、`test.jsonl` 每段一列，音檔路徑相對DATA_ROOT。[占位模板](../training/cloud-record.template.json)刻意不能通過；需先有實際授權、聽稿與去重證據，不能只照模板把旗標改成True。

每列須有 `id/audio_filepath/text/duration/sha256/recording_id/speaker_id/split`。原始繁中、台灣用語與姓名／數字保留，WAV必須16kHz、mono、PCM16、5–30秒。現有pilot schema的training_ready=false是刻意的，正式匯出需經人工審查後另建這三份manifest，不直接覆寫原始pilot檔。

- train：license_status=approved、allowed_uses含training、rights_evidence_ref非空，training_ready=true。
- validation／test：allowed_uses含internal_evaluation、同樣需權利依據，evaluation_ready=true；不要求它們有訓練用途。
- 所有集合：transcript_status=human_verified、local_reference_verified=true、near_duplicate_review=passed，非example_only。機器稿／腳本近似稿不可直接標記。
- 同recording、已知speaker、檔案／PCM hash及完全相同文字不可跨split。未知speaker預設拒絕；若明確改 require_known_speakers=false，報告會揭露speaker isolation未證明。
- 英文自然詞彙保留，但帶[EN]/[TAI]等額外annotation或language_spans目前會被擋下，需先完成annotation-aware adapter，不能把標記當成發音文字一起訓練。

資料gate只驗證檔案、格式、宣告及群組關係，不驗證授權證據真偽或代替人工聽稿。近似去重passed必須來自實際審查，不是這個gate自動算出的品質分數。

```sh
python scripts/cloud_training_data.py --config /content/cloud-training-config.json
python scripts/train_cloud_whisper.py \
  --config /content/cloud-training-config.json \
  --run-dir /content/drive/MyDrive/meeting-live-captions/runs/<new-run>
# 中斷後同一run，加 --resume；參數、manifest、程式及主要套件版本需吻合。
```

## 設定、評估與下一步

預設LoRA r=8、alpha16、dropout0.05、batch1、gradient accumulation4、LR1e-4、seed42，smoke最多32段train／16段validation，20 steps。另一個pilot設定為200 steps，但不會自動啟用。每次train呼叫有30分鐘的step邊界檢查；前置下載、基線／後測eval不含在這個時間內，不是硬性計費／連線時長保證。

先做原始模型validation CER，再用同一雲端 normalizer／jiwer版本比較候選。此normalizer標為cloud-nfc-punctuation-space-v1，不冒充其他實作版本；不以字形轉換隱藏辨識錯誤。test在訓練期間只作內部metadata洩漏審計，不返回給Trainer、不作early stopping。完成後另行對固定未參訓test評估；validation分數或loss下降不代表泛化／現場效果。

Notebook不輸出真實即時P50/P95；正式採用前仍需正常速度播放／真實麥克風測試。adapter之後須載入相同base revision合併、匯出，再用另一個已固定的轉換環境產生CTranslate2/int8並重測。當前Notebook不自動合併、上傳HF或部署Cloudflare；保留原模型fallback。

本機驗證命令：`python3 -m unittest discover -s test -p test_cloud_training_data.py`，涵蓋權利／標籤／重複與跨split、防錯hash／路徑、test不進Trainer資料。Notebook所有code cell可用Python AST檢查；這些測試不需要GPU，也不是GPU訓練驗證。

## 由上傳執行紀錄驗證與診斷

一份上傳的Colab執行檔已顯示套件安裝returncode=0、Tesla T4約14.56GiB、PyTorch 2.11.0+cu130／CUDA 13.0、Drive掛載成功。這是檔案中的歷史輸出，不是本工具直接連入GPU；該檔沒有訓練執行結果，也未測模型forward或訓練套件匯入，因此前述GPU訓練／resume未驗證狀態仍成立。

該檔的RUN_COLLECTION仍為False；資料預檢退出1，但舊版subprocess stdout未存進Notebook，只有CalledProcessError，不能由此確定Drive裡是哪個檔案／欄位有問題。新版改為逐行保存子程序stdout/stderr、列出缺少的manifest，資料未ready時顯示原因並維持訓練關閉；GPU格另加CUDA小矩陣與訓練套件import檢查，仍不下載模型或開始訓練。

新版安裝格會fetch遠端選定ref後checkout固定commit，避免已有main停在舊版；若repo有本地修改會停止保留內容。請重新開啟新版Notebook由上執行，首次蒐集時將RUN_COLLECTION改True，RUN_TRAINING保持False。15段下載不會自動變成人工稿或正式分組，預檢仍需實際審核manifest。


第二份上傳紀錄已確認：T4 CUDA矩陣測試通過，Transformers 4.46.3、PEFT 0.14.0、Accelerate 1.2.1、HF Hub 0.27.1匯入成功；Drive已掛載。資料收集仍為False，預檢明確列缺少三份manifests，沒有訓練。這將問題定位到尚未進行資料準備，而不是已完成微調。

為避免一直執行「關閉下載→缺訓練資料」的流程，新版將初始階段設為collect且RUN_COLLECTION=True，授權與下載上限仍在collector強制檢查；訓練維持False。collect完成只引導到聽稿／近似去重／正式分組，不自動生成已核准標籤。最後一格在collect階段顯示下載摘要；只有train階段才顯示訓練結果。第一格pip回傳值不再重複顯示整份log。

## 授權資料卡解析修正

若出現 `Expected dataset license was not verified`，表示下載尚未通過授權gate，不代表可以直接把gate關閉。舊版只用單行正規表示式比對，無法辨識等價的YAML清單或引號。新版本使用PyYAML SafeLoader，支援 `license: cc-by-4.0`、帶引號、`license: [cc-by-4.0]`、多行清單與CRLF/BOM等格式；只有解析後的license集合完全等於預期值才繼續。不同／混合授權、缺欄位、重複key、惡意YAML標籤或無法解析時維持pending。

每次會保留原始資料卡及SHA-256，寫入 `PILOT_ROOT/review/license-review.json`；collection-report也顯示實際declared_licenses、預期值與解析原因。這個修正沒有改來源設定中的授權預期，也不把格式修正當成實際資料卡已驗證的證據。根代理目前仍被HF proxy403擋下，尚無該次Colab資料卡內容，實際授權需以重跑後的報告確認。

既有Colab工作階段只需重跑第一格（fetch新版與確認PyYAML），再跑資料準備格即可；沿用Drive中的完整檔cache，不必重抓已保存的資料卡。GPU檢查與Drive掛載若已完成，可保留目前狀態，訓練仍關閉。若授權確實不同，新版會列出宣告值並停止下載，不自動放寬允許值。
