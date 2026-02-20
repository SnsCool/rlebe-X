---
name: codex-review
description: OpenAI CLI を使用してコードレビューを実行する
---

## 発動条件

- 「codex でレビュー」「Codex レビュー」と言われた時
- 5ファイル以上の変更があった時（自動）
- 重要なロジック変更時
- セキュリティに関わる変更時
- PR/マージ前の最終確認

**注意**: Codex はレビュー専用。コード生成には GLM を使用。

## 前提条件

OpenAI CLI または curl が必要です：

```bash
# OpenAI CLI インストール（オプション）
pip install openai

# 環境変数設定（必須）
export OPENAI_API_KEY='your-api-key'
```

## 使い方

```bash
node .claude/skills/codex-review/scripts/review.js \
  --files <file1> [file2...] \
  [--diff] \
  [--output <file>]
```

## オプション

| オプション | 必須 | 説明 |
|-----------|------|------|
| --files | はい | レビュー対象ファイル（複数指定可） |
| --diff | いいえ | git diff の内容をレビュー |
| --output | いいえ | 出力先ファイルパス（省略時は stdout） |

## 実行例

```bash
# 単一ファイル
node .claude/skills/codex-review/scripts/review.js --files bot.py

# 複数ファイル + git diff
node .claude/skills/codex-review/scripts/review.js \
  --files bot.py requirements.txt \
  --diff

# 結果をファイルに保存
node .claude/skills/codex-review/scripts/review.js \
  --files bot.py \
  --output review-result.json
```

## レスポンス形式

```json
{
  "ok": true,
  "summary": "コードは良好です",
  "issues": [],
  "passed_checks": ["セキュリティ", "エラーハンドリング"]
}
```

### issues の構造

```json
{
  "severity": "error" | "warning" | "info",
  "file": "ファイルパス",
  "line": 行番号,
  "message": "問題の説明",
  "suggestion": "修正提案"
}
```

## チェック項目

- セキュリティ脆弱性（XSS, SQL Injection, etc.）
- エラーハンドリング
- コードスタイル・一貫性
- パフォーマンス問題
- ベストプラクティス準拠

## 終了コード

| コード | 意味 |
|--------|------|
| 0 | レビュー通過（ok: true） |
| 1 | 問題検出（ok: false）またはエラー |
