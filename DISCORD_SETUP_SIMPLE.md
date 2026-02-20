# Discord Bot設定 - 簡潔版

## 必要な設定（3ステップ）

### 1. Botトークンの取得
- Discord Developer Portal → Bot → Token → Reset Token
- Railway環境変数 `DISCORD_TOKEN` に設定

### 2. 特権インテントの有効化
Discord Developer Portal → Bot → Privileged Gateway Intents
- ✅ **MESSAGE CONTENT INTENT** をON
- ✅ **SERVER MEMBERS INTENT** をON

### 3. Botをサーバーに招待
Discord Developer Portal → OAuth2 → URL Generator

**Scopes:**
- ✅ `bot`
- ✅ `applications.commands`

**Bot Permissions:**
- ✅ View Channels
- ✅ Send Messages
- ✅ Read Message History
- ✅ Attach Files
- ✅ Use Slash Commands

生成されたURLでBotをサーバーに招待

---

## 確認事項
- [ ] Botがサーバーに参加している
- [ ] Botがオンライン（緑色の円）になっている
- [ ] `/report` コマンドが動作する
- [ ] `@heart` メンションが動作する

---

## トラブルシューティング
- Botがオフライン → Railwayログを確認、Discordを再起動
- コマンドが表示されない → `applications.commands`スコープを確認
- メンションが反応しない → MESSAGE CONTENT INTENTを確認
