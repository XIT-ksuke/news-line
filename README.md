# 毎日ニュース → LINE配信ボット

GitHub Actions で毎日3回（7:30 / 12:00 / 18:00 JST）最新ニュースを自分のLINEに届けるボット。  
**完全無料枠**で運用できます。

## アーキテクチャ

```
GitHub Actions (cron)
  → RSS取得（NHK / ITmedia / はてブ / GIGAZINE / Google News など）
  → Groq (Llama 3.3 70B) で重要記事を選定 + 要約
  → LINE Messaging API で自分にpush配信
```

## 無料枠の範囲

| サービス | 無料枠 | 1日3回配信での消費 |
|---|---|---|
| GitHub Actions | publicリポは実質無制限 | 問題なし |
| Groq API (llama-3.3-70b-versatile) | 無料枠（1日1,000リクエスト目安） | 3リクエスト/日 |
| LINE Messaging API (push) | 月200通 | 約90通/月 |

---

## セットアップ手順

### 1. LINE Messaging API の設定

#### 1-1. チャネルアクセストークン（長期）の発行

1. [LINE Developers Console](https://developers.line.biz/console/) にログイン
2. 作成済みの Messaging API チャネルを選択
3. **「Messaging API設定」タブ** → 下部の「チャネルアクセストークン（長期）」→ **「発行」**
4. 表示されたトークンをコピーして保管（後でGitHub Secretsに登録）

#### 1-2. 自分の userId の取得

**方法A: LINE Developers Console で確認**

1. LINE Developers Console → チャネル → **「Messaging API設定」タブ**
2. 「Your user ID」欄に表示されている値が userId（`Uxxxxxxxxxx...` の形式）

**方法B: Webhook で拾う（方法Aで見つからない場合）**

1. [Webhook.site](https://webhook.site/) を開き、表示されるURL（例: `https://webhook.site/xxxx`）をコピー
2. LINE Developers Console → 「Messaging API設定」→「Webhook URL」に貼り付けて「更新」→「検証」
3. LINEアプリで自分の公式アカウントにメッセージを送る（または友だち追加する）
4. Webhook.site に届いたJSONの `events[0].source.userId` が自分の userId

> **注意:** ボットを**自分のLINEで友だち追加**しないとpushメッセージが届きません。

### 2. Groq API キーの取得

1. [Groq Console](https://console.groq.com/keys) にアクセス（GitHub や Google アカウントで無料サインアップ）
2. 「Create API Key」→ キーをコピーして保管（`gsk_...` の形式）

### 3. GitHubリポジトリの作成と設定

#### 3-1. リポジトリ作成

```bash
# このフォルダをpublicリポとしてpush（GitHub CLIの場合）
gh repo create linenews-app --public --source=. --push
```

または GitHub.com で手動作成後:

```bash
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/<あなたのユーザー名>/linenews-app.git
git push -u origin main
```

#### 3-2. GitHub Secrets の登録

GitHub リポジトリ → **Settings → Secrets and variables → Actions → New repository secret** で以下を登録:

| Secret名 | 値 |
|---|---|
| `GROQ_API_KEY` | Groq Console で取得したキー（`gsk_...`） |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Developers で発行した長期トークン |
| `LINE_USER_ID` | 上記で確認した自分の userId |

#### 3-3. LINE Official Account Manager の設定

[LINE Official Account Manager](https://manager.line.biz/) → アカウント選択 → **「応答設定」**:
- 「応答メッセージ」→ **オフ**（自動返信が配信メッセージに混ざらないようにする）
- 「Webhook」→ **オン**

### 4. 動作確認

1. GitHub リポジトリ → **Actions タブ** → 「News Delivery」ワークフロー
2. **「Run workflow」** → 「Run workflow」ボタンを押して手動実行
3. ジョブが緑チェック（✓）になればOK
4. 自分のLINEにメッセージが届いているか確認

---

## カスタマイズ

### 配信フィードの追加・変更

`news_bot.py` の `RSS_FEEDS` リストを編集するか、GitHub Secrets に `RSS_FEEDS` を登録（改行区切りでURLを列挙）。

**Google News 検索フィードの例:**

```
# Oracle関連
https://news.google.com/rss/search?q=Oracle+%E3%82%AF%E3%83%A9%E3%82%A6%E3%83%89&hl=ja&gl=JP&ceid=JP:ja

# SES業界
https://news.google.com/rss/search?q=SES+IT%E6%A5%AD%E7%95%8C&hl=ja&gl=JP&ceid=JP:ja

# 生成AI
https://news.google.com/rss/search?q=%E7%94%9F%E6%88%90AI&hl=ja&gl=JP&ceid=JP:ja
```

### 配信件数・時間ウィンドウの変更

GitHub Secrets（またはワークフローの env）で以下を設定:

| 変数名 | デフォルト | 説明 |
|---|---|---|
| `TOP_N` | `5` | 配信する記事の件数 |
| `HOURS_WINDOW` | `7` | 直近何時間の記事を対象にするか |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | 使用するGroqモデル |

### 配信時刻の変更

`.github/workflows/news_delivery.yml` の `cron` を編集（UTC基準、JST = UTC+9）:

```yaml
- cron: "30 22 * * *"  # JST 07:30 に相当
- cron: "0 3 * * *"   # JST 12:00 に相当
- cron: "0 9 * * *"   # JST 18:00 に相当
```

> **注意:** GitHub Actions のcronは数分〜十数分の遅延が生じる場合があります（仕様）。

---

## ファイル構成

```
.
├── .github/
│   └── workflows/
│       └── news_delivery.yml   # GitHub Actions ワークフロー
├── news_bot.py                 # メインスクリプト
├── requirements.txt            # Python依存ライブラリ
└── README.md
```

## 将来の拡張案

- 配信済みタイトルをファイルに記録して重複配信を防ぐ
- 自宅PC常時稼働に切り替えてOllamaでローカル要約（完全オフライン版）
- 興味カテゴリ別に複数フィードを追加
