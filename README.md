# LikeCounter Bot

Discord リアクション（❤️）・投稿数 月次集計 Bot（AI統合版）

## 機能

- `/report` - 指定月のユーザー別 ❤️ リアクション数・投稿数を集計（CSV出力）
- `/ask` - 自然言語で集計を依頼（AI解析）
  - 「先月のレポート」
  - 「田中さんのいいね数」
  - 「2024年1月の集計」

## セットアップ

### 1. Discord Developer Portal での設定

1. [Discord Developer Portal](https://discord.com/developers/applications) にアクセス
2. 「New Application」でアプリケーションを作成
3. 「Bot」タブで Bot を作成
4. 「Reset Token」でトークンを取得（**安全に保管**）
5. 「Privileged Gateway Intents」で以下を ON:
   - **MESSAGE CONTENT INTENT**
   - **SERVER MEMBERS INTENT**

### 2. Bot をサーバーに招待

OAuth2 > URL Generator で以下を選択：

**Scopes:**
- `bot`
- `applications.commands`

**Bot Permissions:**
- View Channels
- Read Message History

生成されたURLでサーバーに招待

### 3. 環境変数の設定

```bash
export DISCORD_TOKEN='your-discord-bot-token'
export GEMINI_API_KEY='your-gemini-api-key'
```

### 4. bot.py の設定

```python
GUILD_ID = 123456789012345678      # サーバーID
CHANNEL_IDS = [123456789012345678]  # 集計対象チャンネルID
ALLOWED_USER_IDS = [123456789012345678]  # 実行許可ユーザーID
```

### 5. 実行

```bash
pip install -r requirements.txt
python bot.py
```

## コマンド

### /report（従来互換）

```
/report period:2024-01   # 2024年1月を集計
/report period:last      # 先月を集計
/report period:all       # 全期間を集計
```

### /ask（AI自然言語対応）

```
/ask query:先月のレポート
/ask query:田中さんのいいね数
/ask query:2024年1月の集計
/ask query:@田中 の今月のハート数
```

## 出力

### 全体レポート（CSV）

CSVファイルがDMで送信されます。

| name | hearts | posts |
|------|--------|-------|
| ユーザー名 | ❤️数 | 投稿数 |

ソート順: hearts降順 → posts降順 → name昇順

### 個別照会

チャンネル内にテキストで表示されます。

```
2024年1月 の 田中 さん
❤️ いいね数: 42
📝 投稿数: 15
```

## デプロイ

### ローカル実行

```bash
python bot.py
```

### Railway（推奨）

1. [Railway](https://railway.app/) にログイン
2. 「New Project」→「Deploy from GitHub repo」
3. 環境変数を設定:
   - `DISCORD_TOKEN`
   - `GEMINI_API_KEY`
4. 自動デプロイ

### Render

1. [Render](https://render.com/) にログイン
2. 「New」→「Background Worker」
3. GitHubリポジトリを接続
4. Build Command: `pip install -r requirements.txt`
5. Start Command: `python bot.py`
6. 環境変数を設定

## トラブルシューティング

### /report, /ask が表示されない

- Bot に `applications.commands` スコープが付与されているか確認
- チャンネルで Bot に「Use Application Commands」権限があるか確認
- Bot を再起動してコマンドを同期

### 権限エラー

- 対象チャンネルで Bot に以下の権限があるか確認:
  - View Channel
  - Read Message History

### DM が届かない

- Discord設定 > プライバシー・安全 > 「サーバーメンバーからのダイレクトメッセージを許可する」を ON

### AI解析が動かない

- `GEMINI_API_KEY` が正しく設定されているか確認
- Gemini API の利用制限に達していないか確認

## 技術スタック

- Python 3.11+
- discord.py 2.3+
- Google Gemini API (gemini-3.0-flash)
