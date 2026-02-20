# Discord Bot設定ガイド

このドキュメントでは、Discord Botを正常に動作させるための設定手順を説明します。

## 目次
1. [Discord Developer PortalでのBot作成](#1-discord-developer-portalでのbot作成)
2. [特権インテントの有効化](#2-特権インテントの有効化)
3. [Botをサーバーに招待](#3-botをサーバーに招待)
4. [Bot権限の確認](#4-bot権限の確認)

---

## 1. Discord Developer PortalでのBot作成

### 1-1. アプリケーションの作成
1. https://discord.com/developers/applications にアクセス
2. 「New Application」をクリック
3. アプリケーション名を入力（例: "LikeCounter Bot"）
4. 「Create」をクリック

### 1-2. Botの作成
1. 左メニューから「Bot」を選択
2. 「Add Bot」をクリック
3. 「Yes, do it!」をクリックして確認

### 1-3. Botトークンの取得
1. 「Bot」セクションの「Token」セクションを確認
2. 「Reset Token」をクリック（初回作成時は自動で表示される）
3. 表示されたトークンをコピー（**このトークンは一度しか表示されません**）
4. Railway環境変数 `DISCORD_TOKEN` に設定

⚠️ **重要**: トークンは秘密情報です。他人に共有しないでください。

---

## 2. 特権インテントの有効化

### 2-1. 特権インテントとは
Discord Botが特定の機能を使用するために必要な権限です。このBotでは以下の2つが必要です。

### 2-2. 設定手順
1. Discord Developer Portalで、作成したアプリケーションを選択
2. 左メニューから「Bot」を選択
3. ページを下にスクロールして「Privileged Gateway Intents」セクションを探す
4. 以下の2つのトグルスイッチを**ON（有効）**にする：
   - ✅ **MESSAGE CONTENT INTENT**
     - 説明: "Required for your bot to receive message content in most messages"
     - Botがメッセージの内容を読み取るために必要
   - ✅ **SERVER MEMBERS INTENT**
     - 説明: "Required for your bot to receive events listed under GUILD_MEMBERS"
     - Botがサーバーメンバー情報を取得するために必要

### 2-3. 確認
- 両方のトグルが**紫色（ON）**になっていることを確認
- 設定は自動的に保存されます

---

## 3. Botをサーバーに招待

### 3-1. OAuth2 URL Generatorの設定
1. Discord Developer Portalで、作成したアプリケーションを選択
2. 左メニューから「OAuth2」を選択
3. 「URL Generator」を選択

### 3-2. Scopes（スコープ）の選択
「Scopes」セクションで、以下の2つにチェックを入れる：
- ✅ **bot** - Botをサーバーに追加するために必要
- ✅ **applications.commands** - スラッシュコマンドを使用するために必要

### 3-3. Bot Permissions（権限）の選択
「Bot Permissions」セクションで、以下の権限にチェックを入れる：

**General Permissions（左側の列）:**
- ✅ **View Channels** - チャンネルを閲覧するために必要

**Text Permissions（真ん中の列）:**
- ✅ **Send Messages** - メッセージを送信するために必要
- ✅ **Read Message History** - メッセージ履歴を読み取るために必要
- ✅ **Add Reactions** - リアクションを追加するために必要
- ✅ **Use Slash Commands** - スラッシュコマンドを使用するために必要
- ✅ **Attach Files** - CSVファイルを送信するために必要

### 3-4. 招待URLの生成と使用
1. ページ下部の「Generated URL」セクションにURLが自動生成されます
2. 生成されたURLをコピー
3. ブラウザでURLを開く
4. Botを追加したいサーバーを選択
5. 「認証」または「Authorize」をクリック
6. 権限を確認して「認証」をクリック

### 3-5. 確認
- Discordのサーバーで、Botがメンバー一覧に表示されていることを確認
- Botのステータスがオンライン（緑色の円）になっていることを確認

---

## 4. Bot権限の確認

### 4-1. サーバー設定での確認
1. Discordでサーバーを開く
2. サーバー名を右クリック → 「サーバー設定」を選択
3. 左メニューから「ロール」を選択
4. Botのロール（通常はBot名と同じ）を選択
5. 以下の権限が有効になっているか確認：
   - チャンネルの閲覧
   - メッセージの送信
   - メッセージ履歴の読み取り
   - ファイル添付
   - スラッシュコマンドの使用

### 4-2. チャンネル権限の確認
1. チャンネルを右クリック → 「チャンネル編集」を選択
2. 「権限」タブを選択
3. Botのロールが追加されているか確認
4. Botがチャンネルを閲覧・送信できる権限があるか確認

---

## トラブルシューティング

### Botがオフライン表示される
- Railwayのログを確認して、Botが正常に起動しているか確認
- Discordを再起動またはページを更新（F5）
- Botがサーバーに参加しているか確認

### スラッシュコマンドが表示されない
- Botがサーバーに参加しているか確認
- `applications.commands`スコープが選択されているか確認
- Discordを再起動してコマンドを再同期

### Botメンションが反応しない
- `MESSAGE CONTENT INTENT`が有効になっているか確認
- Botがチャンネルを閲覧できる権限があるか確認
- Railwayのログでエラーメッセージを確認

### 権限エラーが発生する
- Botのロールに適切な権限が付与されているか確認
- チャンネル権限でBotがブロックされていないか確認
- Botをサーバー管理者ロールに追加（推奨されないが、テスト時は有効）

---

## まとめチェックリスト

設定が完了したら、以下を確認してください：

- [ ] Discord Developer PortalでBotを作成
- [ ] Botトークンを取得してRailway環境変数に設定
- [ ] MESSAGE CONTENT INTENTを有効化
- [ ] SERVER MEMBERS INTENTを有効化
- [ ] OAuth2 URL Generatorで`bot`と`applications.commands`を選択
- [ ] 必要なBot Permissionsを選択
- [ ] 生成されたURLでBotをサーバーに招待
- [ ] Botがサーバーに参加していることを確認
- [ ] Botがオンラインになっていることを確認
- [ ] スラッシュコマンド（`/report`, `/ask`）が動作することを確認
- [ ] Botメンション（`@heart`）が動作することを確認

---

## 参考リンク

- [Discord Developer Portal](https://discord.com/developers/applications)
- [Discord Bot Permissions](https://discord.com/developers/docs/topics/permissions)
- [Discord Gateway Intents](https://discord.com/developers/docs/topics/gateway#gateway-intents)
