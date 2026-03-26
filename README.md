# genomics-mcp

がんゲノム診療支援用 MCPサーバー群

## 概要

Cancer genomics expert panel業務を支援するMCPサーバーの詰め合わせです。
Claude Desktop / Claude Code から PubMed, ClinVar, CIViC, OncoKB,
Semantic Scholar, ClinicalTrials.gov のAPIを直接利用できます。

## 含まれるサーバー

| サーバー | 主な機能 |
|---|---|
| **PubMed** | 論文検索（PubMed構文対応）、メタデータ取得、関連論文検索、ID変換（PMID/PMCID/DOI）、引用情報からの論文特定 |
| **ClinVar** | バリアント検索（遺伝子名/疾患名/フリーテキスト）、バリアント詳細取得、サブミッション詳細（施設別判定根拠）、遺伝子サマリー統計 |
| **CIViC** | がんバリアントの臨床的エビデンス検索、エビデンスレベル・薬剤・疾患による絞り込み、アサーション取得 |
| **OncoKB** | がんバリアントのアクショナビリティ評価（FDA Level of Evidence）、薬剤感受性/耐性情報、がん遺伝子/腫瘍抑制遺伝子リスト |
| **Semantic Scholar** | 学術論文検索、引用/被引用ネットワーク解析、著者検索、推薦論文取得 |
| **ClinicalTrials** | 臨床試験検索（疾患/介入/ステータス別）、適格基準取得、日本国内治験施設フィルタ |

## セットアップ手順

### Step 1: ダウンロード

1. https://github.com/FujiLab-2026/genomics-mcp を開く
2. 緑色の **「Code」** ボタンをクリック → **「Download ZIP」** をクリック
3. ダウンロードされた `genomics-mcp-main.zip` を右クリック →「すべて展開」
4. 展開されたフォルダを好きな場所に移動（例: `C:\Users\自分のユーザー名\genomics-mcp-main`）

> うまくいかない場合は直接ダウンロード: https://github.com/FujiLab-2026/genomics-mcp/archive/refs/heads/main.zip

### Step 2: APIキーの取得（任意）

#### NCBI API Key（推奨・無くても動作します）

1. https://www.ncbi.nlm.nih.gov/account/ でNCBIアカウント作成
2. Settings → API Key Management → "Create an API Key"
3. 表示されたキーをメモ

#### OncoKB Token（OncoKBサーバー利用時は必須）

1. https://www.oncokb.org/account/register でアカウント登録
2. License Type で "Academic" を選択
3. 承認メールが届いたらログインしてTokenをメモ

※ 承認まで1〜3営業日かかる場合があります
※ OncoKBが不要なら、このステップはスキップしてOKです

### Step 3: セットアップ実行

展開したフォルダ内でコマンドを実行します。

#### Windows の場合

1. 展開したフォルダをエクスプローラーで開く
2. アドレスバーをクリックして `cmd` と入力し、Enterキーを押す（コマンドプロンプトが開きます）
3. 以下を入力してEnter:
   ```
   python setup_config.py
   ```

#### macOS の場合

1. Finderで展開したフォルダを右クリック →「フォルダでターミナルを開く」
2. 以下を入力してEnter:
   ```
   python3 setup_config.py
   ```

#### 画面の案内に従って操作

以下が自動で行われます:
- uv（Pythonパッケージマネージャ）のインストール（未導入の場合）
- APIキーの対話的設定（Step 2でメモしたキーを貼り付け。無ければEnterでスキップ）
- Claude Desktopの設定ファイルに全サーバーを自動登録（手でJSONを編集する必要はありません）

### Step 4: Claude Desktop を再起動

- **Windows**: タスクバー右下のClaude Desktopアイコンを右クリック →「終了」してから再度開く
- **macOS**: メニューバーのClaude →「Quit Claude」してから再度開く

## 手動設定（setup_config.py を使わない場合）

1. uv をインストール:
   - Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
   - macOS: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. `.env.example` を `.env` にコピーしてAPIキーを記入
3. `config_template.json` の `{{INSTALL_DIR}}` を実際のパスに書き換え
4. `claude_desktop_config.json` に内容をコピー（既存設定とマージ）

## 前提条件

- Claude Desktop がインストール済み
- 何らかのPython（`setup_config.py` の実行に必要。Anaconda、システムPython、python.org版いずれでもOK。バージョンは3.8以上なら動作する。uv やサーバー自体の実行にはPythonの事前インストールは不要）
- インターネット接続（uv の自動インストールとAPIアクセスに必要）

## 使用例

- PubMed: 「pancreatic cancer AND body composition で検索して」
- ClinVar: 「KRAS G12Dの臨床的意義を教えて」
- OncoKB: 「BRAF V600Eのアクショナビリティを調べて」
- CIViC: 「EGFRのエビデンスを検索して」
- ClinicalTrials: 「膵臓癌の第III相試験を検索して」

## トラブルシューティング

- **uv が見つからない**: ターミナルを再起動してPATHを反映、またはフルパスで実行（Windows: `%USERPROFILE%\.local\bin\uv`）
- **OncoKBが動かない**: `.env` の `ONCOKB_TOKEN` を確認、またはアカウント承認待ち
- **サーバーが表示されない**: Claude Desktopを再起動したか確認
- **初回起動が遅い**: uv が依存パッケージを初回ダウンロード中（2回目以降はキャッシュされる）

## オプション：Filesystemサーバー（ローカルファイルの読み書き）

セットアップスクリプトを実行すると、Filesystemサーバーの設定も自動で登録されます。
このサーバーを使うと、Claudeが自分のPC上のファイル（PDF・Excel・テキストなど）を直接読み書きできるようになります。

**使うには Node.js のインストールが必要です**（Node.jsが無くても他の6サーバーは正常に動きます）。

### Node.js のインストール手順

1. https://nodejs.org/en/download を開く
2. **「Windows Installer (.msi)」** の **64-bit** をクリックしてダウンロード
3. ダウンロードされた `.msi` ファイルをダブルクリックして実行
4. インストーラーの画面は全て **「Next」→「Next」→「Install」** でOK
5. Claude Desktopを再起動

Claudeに「Documentsフォルダの中身を見せて」と話しかけて動作確認してください。

> デフォルトではDocumentsフォルダにアクセスできます。他のフォルダも追加したい場合は藤井に相談してください。

## ライセンス

MIT License

OncoKB APIの利用は学術・非営利目的に限定されます。
OncoKBの利用規約: https://www.oncokb.org/terms

## 開発者

藤井武宏（三重大学医学部附属病院 肝胆膵・移植外科 / 医療情報管理部）
