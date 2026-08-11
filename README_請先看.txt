POWER AI Cloud v1.0 — 免費雲端測試版

目的
====
這個版本不需要 .BAT、不需要 PowerShell，也不需要使用者電腦執行伺服器。
部署完成後，所有人直接打開 https://xxxxx.onrender.com 即可使用。

包含功能
========
1. MLCC Voltage Checker
2. Power IC 替代料
3. Cloud Official Datasheet Compare
   - 雲端搜尋 IC 原廠官方網站
   - 只接受原廠官方網域
   - 自動取得官方 Datasheet PDF
   - 雲端自動解析 PDF
   - 自動抽取 VIN、Absolute Max VIN、Battery Cell、Charge Current、
     Charge Voltage、Topology、Interface、Switching Frequency、
     Package、Operating Temperature
   - 自動比較候選料
   - 提供官方 Datasheet 開啟 / 下載連結
   - 抓不到的欄位顯示「未取得」，不自行猜測
4. Circuit AI Review
5. 不含登入 / 帳號 / Email 授權功能

部署到 Render（第一次做而已）
=========================
步驟 1：建立一個 GitHub 帳號（如果已經有就跳過）。

步驟 2：在 GitHub 建立新的 Repository，例如：
Power-AI-Test

步驟 3：把這個資料夾內的 5 個檔案全部上傳到 Repository 根目錄：
- app.py
- app.html
- requirements.txt
- render.yaml
- README_請先看.txt

步驟 4：登入 Render，選 New → Blueprint，
連接剛才的 GitHub Repository。

步驟 5：Render 看到 render.yaml 後，按 Deploy Blueprint。

步驟 6：等待部署完成。
Render 會提供類似：
https://power-ai-cloud-test.onrender.com

之後只要開這個網址，不需要執行任何本機程式。

測試方式
========
開啟 Power IC 替代料：
1. 輸入 SY6969C
2. 按「尋找替代料」
3. 按「連線查詢官方 Datasheet 並比較規格」
4. 等待雲端搜尋與 PDF 解析完成
5. 查看官方規格比較與 Datasheet 按鈕

注意
====
- 免費 Render 測試服務閒置一段時間會休眠，第一次重新進入可能需要等待喚醒。
- 這是 PoC / 測試版本，不建議直接拿來處理未經公司允許上傳至公有雲的機密線路。
- EXP 與 Datasheet 在目前前端分析流程中不會被保存成永久資料庫。
