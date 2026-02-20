"""
LikeCounter Bot
Discord リアクション（❤️）・投稿数 月次集計 Bot
AI統合版 - 自然言語で期間・ユーザー指定可能
"""

import os
import csv
import io
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict

import discord
from discord import app_commands
import google.generativeai as genai


# =============================================================================
# 設定値
# =============================================================================
GUILD_ID = 1172020927047942154
CHANNEL_IDS = [1448981729938247710]  # レベッター（❤️集計）
LUNCH_CHANNEL_ID = 1437763696096182363  # ランチ制度チャンネル
LUNCH_THREAD_ID = 1459225398616260853  # ランチ制度フォーム投稿スレッド
AI_THREAD_ID = 1451733100882165882  # 本気AI提出スレッド
AI_CHANNEL_ID = 1425718558935224362  # 本気AI関連チャンネル
ALLOWED_USER_IDS = [1340666940615823451, 1307922048731058247]
HEART_EMOJI = "❤️"
EXCLUDE_BOTS = True

# タイムゾーン
JST = ZoneInfo("Asia/Tokyo")
UTC = ZoneInfo("UTC")


# =============================================================================
# AI クライアント初期化（Gemini）
# =============================================================================
def init_gemini():
    """Gemini APIを初期化"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
        return genai.GenerativeModel("gemini-2.5-flash")
    return None

ai_model = None  # 起動時に初期化


def extract_urls(content: str) -> set[str]:
    """メッセージからURLを抽出する"""
    # ma-ji.ai や google.com/forms などのURLを抽出
    url_pattern = r'https?://[^\s<>\]\)」』】]+'
    urls = re.findall(url_pattern, content)
    # 正規化（末尾の句読点などを除去）
    normalized = set()
    for url in urls:
        # 末尾の不要な文字を除去
        url = url.rstrip('。、.,;:')
        normalized.add(url)
    return normalized


def extract_name_regex(content: str) -> str | None:
    """正規表現でメッセージから名前を抽出する（高速）"""
    # パターン1: 名前: xxx または 名前：xxx
    match = re.search(r'名前[:：]\s*\n?(.+?)(?:\n|$)', content)
    if match:
        name = match.group(1).strip()
        if 2 <= len(name) <= 20:
            return name

    # パターン2: 【名前\n(説明)】\n実際の名前
    match = re.search(r'【名前[^】]*】\s*\n(.+?)(?:\n|$)', content)
    if match:
        name = match.group(1).strip()
        if 2 <= len(name) <= 20:
            return name

    return None


def extract_name_with_ai(content: str, debug: bool = False) -> str | None:
    """AIを使ってメッセージから名前を抽出する（フォールバック）"""
    if ai_model is None:
        if debug:
            print("DEBUG: ai_model is None", flush=True)
        return None

    prompt = f"""以下のメッセージから人の名前（フルネーム）を1つだけ抽出してください。
名前のみを出力してください。余計な説明は不要です。
名前が見つからない場合は「なし」と出力してください。

メッセージ:
{content[:500]}

名前:"""

    try:
        response = ai_model.generate_content(prompt)
        result = response.text.strip()

        if debug:
            print(f"DEBUG AI: '{result}'", flush=True)

        if result in ["なし", "なし。", "", "不明"]:
            return None
        if len(result) > 20:
            return None
        return result
    except Exception as e:
        print(f"AI error: {e}", flush=True)
        return None


def extract_name_hybrid(content: str, debug: bool = False) -> str | None:
    """ハイブリッド方式: まず正規表現、失敗時のみAI"""
    # まず正規表現で試す（高速）
    name = extract_name_regex(content)
    if name:
        if debug:
            print(f"DEBUG regex: '{name}'", flush=True)
        return name

    # 正規表現で見つからない場合のみAIを使用
    if debug:
        print("DEBUG: regex failed, trying AI...", flush=True)
    return extract_name_with_ai(content, debug=debug)


# =============================================================================
# Bot 初期化
# =============================================================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# =============================================================================
# AI 意図解析
# =============================================================================
def parse_intent_with_ai(user_input: str, current_date: str, guild_members: list[dict]) -> dict:
    """
    AIを使ってユーザー入力から意図を解析する。

    Args:
        user_input: ユーザーの自然言語入力
        current_date: 現在日付（YYYY-MM-DD形式）
        guild_members: サーバーメンバーリスト [{"id": int, "name": str}, ...]

    Returns:
        {
            "action": "report" | "user_likes" | "unknown",
            "period": {"year": int, "month": int} | "last" | "all" | null,
            "target_user_id": int | null,
            "error": str | null
        }
    """
    members_info = "\n".join([f"- ID: {m['id']}, 名前: {m['name']}" for m in guild_members[:50]])

    prompt = f"""あなたはDiscord Botのコマンド解析アシスタントです。
ユーザーの入力から、以下の情報を抽出してJSON形式で返してください。

## 現在日付
{current_date}

## サーバーメンバー一覧
{members_info}

## 抽出する情報

1. action: 実行するアクション
   - "report": 月次レポート（全員の集計）
   - "user_likes": 特定ユーザーのいいね数照会
   - "unknown": 判断できない

2. period: 集計期間
   - {{"year": 2024, "month": 1}} のような形式（月単位）
   - {{"start": "2024-01-15 09:00", "end": "2024-01-15 23:59"}} のような形式（日時範囲指定）
   - "last": 先月
   - "all": 全期間
   - null: 指定なし（デフォルトで今月扱い）
   ※日付や時刻の範囲指定がある場合は必ず start/end 形式を使ってください。
   ※年の指定がない場合は現在日付の年を使ってください。
   ※時刻の指定がない場合は、startは 00:00、endは 23:59 をデフォルトとしてください。

3. target_user_id: 対象ユーザーのID（user_likes の場合のみ）
   - メンバー一覧から最も近い名前のユーザーIDを選択
   - null: 指定なし

4. error: エラーメッセージ（解析できない場合のみ）

## 入力例と出力例

入力: "先月のレポート"
出力: {{"action": "report", "period": "last", "target_user_id": null, "error": null}}

入力: "田中さんのいいね数"
出力: {{"action": "user_likes", "period": null, "target_user_id": 123456789, "error": null}}

入力: "2024年1月の集計"
出力: {{"action": "report", "period": {{"year": 2024, "month": 1}}, "target_user_id": null, "error": null}}

入力: "1月の佐藤くんのハート数"
出力: {{"action": "user_likes", "period": {{"year": 2024, "month": 1}}, "target_user_id": 987654321, "error": null}}

入力: "2/15 11:16〜23:59のいいね数"
出力: {{"action": "report", "period": {{"start": "2025-02-15 11:16", "end": "2025-02-15 23:59"}}, "target_user_id": null, "error": null}}

入力: "1/10〜1/20のレポート"
出力: {{"action": "report", "period": {{"start": "2025-01-10 00:00", "end": "2025-01-20 23:59"}}, "target_user_id": null, "error": null}}

## ユーザー入力
{user_input}

## 出力
JSONのみを出力してください。説明は不要です。
"""

    try:
        if ai_model is None:
            return {"action": "unknown", "period": None, "target_user_id": None, "error": "AI未初期化"}

        response = ai_model.generate_content(prompt)
        result_text = response.text.strip()

        # JSON部分を抽出
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        else:
            return {"action": "unknown", "period": None, "target_user_id": None, "error": "JSON解析失敗"}

    except Exception as e:
        return {"action": "unknown", "period": None, "target_user_id": None, "error": str(e)}


# =============================================================================
# 期間計算ユーティリティ
# =============================================================================
def get_period_range(period) -> tuple[datetime | None, datetime | None]:
    """
    期間指定から開始日時と終了日時（JST）を返す。

    Args:
        period: {"year": int, "month": int} | "last" | "all" | None

    Returns:
        (start_dt, end_dt) - JST での期間
    """
    now_jst = datetime.now(JST)

    if period is None:
        # 今月
        start_dt = now_jst.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now_jst.month == 12:
            end_dt = datetime(now_jst.year + 1, 1, 1, 0, 0, 0, tzinfo=JST)
        else:
            end_dt = datetime(now_jst.year, now_jst.month + 1, 1, 0, 0, 0, tzinfo=JST)
        return start_dt, end_dt

    if period == "all":
        return None, None

    if period == "last":
        first_of_this_month = now_jst.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_dt = first_of_this_month
        if first_of_this_month.month == 1:
            start_dt = first_of_this_month.replace(year=first_of_this_month.year - 1, month=12)
        else:
            start_dt = first_of_this_month.replace(month=first_of_this_month.month - 1)
        return start_dt, end_dt

    if isinstance(period, dict) and "start" in period and "end" in period:
        # カスタム日時範囲: {"start": "YYYY-MM-DD HH:MM", "end": "YYYY-MM-DD HH:MM"}
        start_dt = datetime.strptime(period["start"], "%Y-%m-%d %H:%M").replace(tzinfo=JST)
        end_dt = datetime.strptime(period["end"], "%Y-%m-%d %H:%M").replace(tzinfo=JST)
        return start_dt, end_dt

    if isinstance(period, dict) and "year" in period and "month" in period:
        year = period["year"]
        month = period["month"]
        start_dt = datetime(year, month, 1, 0, 0, 0, tzinfo=JST)
        if month == 12:
            end_dt = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=JST)
        else:
            end_dt = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=JST)
        return start_dt, end_dt

    # デフォルト: 今月
    return get_period_range(None)


def format_period_str(period) -> str:
    """期間を表示用文字列に変換"""
    if period is None:
        now = datetime.now(JST)
        return f"{now.year}年{now.month}月"
    if period == "all":
        return "全期間"
    if period == "last":
        now = datetime.now(JST)
        if now.month == 1:
            return f"{now.year - 1}年12月"
        return f"{now.year}年{now.month - 1}月"
    if isinstance(period, dict) and "start" in period and "end" in period:
        return f"{period['start']} 〜 {period['end']}"
    if isinstance(period, dict):
        return f"{period['year']}年{period['month']}月"
    return str(period)


# =============================================================================
# 集計処理
# =============================================================================
async def collect_stats(
    guild: discord.Guild,
    start_utc: datetime | None,
    end_utc: datetime | None,
    target_user_id: int | None = None,
    collect_top_posts: bool = False
) -> dict:
    """
    メッセージを集計してユーザー統計を返す。

    Args:
        guild: Discordサーバー
        start_utc: 開始日時（UTC）
        end_utc: 終了日時（UTC）
        target_user_id: 特定ユーザーのみ集計する場合はそのID
        collect_top_posts: いいね数トップ投稿を収集するか

    Returns:
        {
            "user_stats": {user_id: {"name": str, "hearts": int, "posts": int, "likes_given": int}, ...},
            "top_posts": [{"author": str, "hearts": int, "content": str, "date": str}, ...]  # collect_top_posts=True時のみ
        }
    """
    user_stats = {}
    likes_given = defaultdict(int)  # いいねした回数を追跡
    top_posts = []  # いいね数トップ投稿
    msg_count = 0
    reaction_count = 0

    for channel_id in CHANNEL_IDS:
        channel = guild.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            continue

        print(f"[collect_stats] Processing channel {channel_id}...", flush=True)

        try:
            async for message in channel.history(
                after=start_utc,
                before=end_utc,
                limit=None,
                oldest_first=True
            ):
                msg_count += 1
                if msg_count % 50 == 0:
                    print(f"[collect_stats] Processed {msg_count} messages, {reaction_count} reactions...", flush=True)

                # Bot除外
                if EXCLUDE_BOTS and message.author.bot:
                    continue

                user_id = message.author.id
                display_name = message.author.display_name

                if user_id not in user_stats:
                    user_stats[user_id] = {
                        "name": display_name,
                        "hearts": 0,
                        "posts": 0,
                        "likes_given": 0
                    }

                # 特定ユーザーのみの場合は投稿カウントをスキップ
                if target_user_id and message.author.id != target_user_id:
                    pass  # 投稿カウントはスキップ、いいねした人の取得は続行
                else:
                    # 投稿数カウント
                    user_stats[user_id]["posts"] += 1

                # ❤️リアクションをカウント
                msg_hearts = 0
                for reaction in message.reactions:
                    if str(reaction.emoji) == HEART_EMOJI:
                        msg_hearts = reaction.count
                        # 投稿者がもらったいいね数
                        if not target_user_id or message.author.id == target_user_id:
                            user_stats[user_id]["hearts"] += reaction.count

                        # いいねした人を取得
                        reaction_count += 1
                        try:
                            async for reactor in reaction.users():
                                if reactor.bot:
                                    continue
                                likes_given[reactor.id] += 1
                                # ユーザー情報を登録（まだなければ）
                                if reactor.id not in user_stats:
                                    user_stats[reactor.id] = {
                                        "name": reactor.display_name,
                                        "hearts": 0,
                                        "posts": 0,
                                        "likes_given": 0
                                    }
                        except discord.Forbidden:
                            pass  # リアクションユーザー取得権限がない場合はスキップ
                        break

                # トップ投稿を収集
                if collect_top_posts and msg_hearts > 0:
                    post_date = message.created_at.astimezone(JST).strftime("%Y-%m-%d %H:%M")
                    top_posts.append({
                        "author": display_name,
                        "hearts": msg_hearts,
                        "content": message.content,
                        "date": post_date
                    })

        except discord.Forbidden:
            raise Exception(f"チャンネル <#{channel_id}> の履歴を読む権限がありません。")

    # いいねした回数をuser_statsに反映
    for uid, count in likes_given.items():
        if uid in user_stats:
            user_stats[uid]["likes_given"] = count

    # トップ10投稿をソート
    if collect_top_posts:
        top_posts = sorted(top_posts, key=lambda x: -x["hearts"])[:10]

    print(f"[collect_stats] Done: {msg_count} messages, {reaction_count} reactions", flush=True)
    return {"user_stats": user_stats, "top_posts": top_posts}


def extract_department(name: str) -> tuple[str, str]:
    """名前から部署を抽出する。【部署】名前 の形式を想定。"""
    import re
    match = re.match(r'【(.+?)】\s*(.+)', name)
    if match:
        return match.group(1), match.group(2)
    return "", name


def generate_csv(data: list[dict], inactive_members: list[str] = None, include_total: bool = True) -> io.BytesIO:
    """集計データをCSVファイル（BytesIO）として生成する。"""
    output = io.StringIO()

    # 日本語ヘッダー（部署を一番左に、いいねした回数を追加）
    fieldnames_jp = ["部署", "名前", "いいね数", "いいねした回数", "投稿数", "平均いいね数", "全体いいね数", "全体投稿数"]
    writer = csv.DictWriter(output, fieldnames=fieldnames_jp)
    writer.writeheader()

    # 先に合計を計算
    total_hearts = sum(row["hearts"] for row in data)
    total_posts = sum(row["posts"] for row in data)
    total_likes_given = sum(row.get("likes_given", 0) for row in data)

    # 投稿者データを書き込み
    for i, row in enumerate(data):
        dept, name_only = extract_department(row["name"])
        row_data = {
            "部署": dept,
            "名前": name_only,
            "いいね数": row["hearts"],
            "いいねした回数": row.get("likes_given", 0),
            "投稿数": row["posts"],
            "平均いいね数": row["avg_hearts"],
            "全体いいね数": "",
            "全体投稿数": ""
        }

        # 1行目にのみ全体いいね数・全体投稿数を表示
        if i == 0:
            row_data["全体いいね数"] = total_hearts
            row_data["全体投稿数"] = total_posts

        writer.writerow(row_data)

    # 投稿していないメンバーを追加（部署と名前の列に）
    inactive_list = inactive_members if inactive_members else []
    for inactive_name in inactive_list:
        dept, name_only = extract_department(inactive_name)
        writer.writerow({
            "部署": dept,
            "名前": name_only,
            "いいね数": 0,
            "いいねした回数": 0,
            "投稿数": 0,
            "平均いいね数": 0,
            "全体いいね数": "",
            "全体投稿数": ""
        })

    # 合計行を追加
    if include_total:
        total_avg = round(total_hearts / total_posts, 2) if total_posts > 0 else 0
        writer.writerow({
            "部署": "",
            "名前": "【合計】",
            "いいね数": total_hearts,
            "いいねした回数": total_likes_given,
            "投稿数": total_posts,
            "平均いいね数": total_avg,
            "全体いいね数": "",
            "全体投稿数": ""
        })

    csv_bytes = output.getvalue().encode("utf-8-sig")
    return io.BytesIO(csv_bytes)


# =============================================================================
# スラッシュコマンド: /date_report（日時範囲指定）
# =============================================================================
@tree.command(
    name="date_report",
    description="指定した日時範囲の❤️リアクション数と投稿数を集計します",
    guild=discord.Object(id=GUILD_ID) if GUILD_ID else None
)
@app_commands.describe(
    start="開始日時（YYYY-MM-DD HH:MM）例: 2025-02-15 11:16",
    end="終了日時（YYYY-MM-DD HH:MM）例: 2025-02-15 23:59"
)
async def date_report(interaction: discord.Interaction, start: str, end: str):
    """日時範囲を指定してレポートを生成"""

    # 権限チェック
    if ALLOWED_USER_IDS and interaction.user.id not in ALLOWED_USER_IDS:
        await interaction.response.send_message(
            "このコマンドを実行する権限がありません。",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    # 日時パース
    try:
        parsed_period = {"start": start.strip(), "end": end.strip()}
        start_dt, end_dt = get_period_range(parsed_period)
    except ValueError:
        await interaction.followup.send(
            f"日時の形式が正しくありません。\n"
            f"正しい形式: `YYYY-MM-DD HH:MM`（例: `2025-02-15 11:16`）\n"
            f"入力値: start=`{start}`, end=`{end}`",
            ephemeral=True
        )
        return

    if start_dt >= end_dt:
        await interaction.followup.send("開始日時は終了日時より前にしてください。", ephemeral=True)
        return

    start_utc = start_dt.astimezone(UTC)
    end_utc = end_dt.astimezone(UTC)

    # 集計実行
    try:
        result = await collect_stats(interaction.guild, start_utc, end_utc)
        user_stats = result["user_stats"]
    except Exception as e:
        await interaction.followup.send(str(e), ephemeral=True)
        return

    period_label = format_period_str(parsed_period)

    if not user_stats:
        await interaction.followup.send(
            f"{period_label} のデータがありませんでした。",
            ephemeral=True
        )
        return

    # 平均いいね数を計算
    for user_id, stats in user_stats.items():
        if stats["posts"] > 0:
            stats["avg_hearts"] = round(stats["hearts"] / stats["posts"], 2)
        else:
            stats["avg_hearts"] = 0.0

    # ソート: hearts降順 → posts降順 → name昇順
    sorted_data = sorted(
        user_stats.values(),
        key=lambda x: (-x["hearts"], -x["posts"], x["name"])
    )

    # 投稿していないメンバーを取得
    posted_user_ids = set(user_stats.keys())
    inactive_members = []
    for member in interaction.guild.members:
        if member.bot:
            continue
        if member.id not in posted_user_ids:
            inactive_members.append(member.display_name)

    # CSV生成
    csv_file = generate_csv(sorted_data, inactive_members=inactive_members, include_total=True)
    filename = f"{start.strip().replace(' ', '_')}_{end.strip().replace(' ', '_')}_report.csv"

    # レポートメッセージ作成
    total_hearts = sum(s["hearts"] for s in sorted_data)
    total_posts = sum(s["posts"] for s in sorted_data)
    report_message = f"**{period_label}** の集計結果です。\n"
    report_message += f"📊 **全体合計**: いいね数 {total_hearts} / 投稿数 {total_posts}"

    # DM送信
    try:
        await interaction.user.send(
            report_message,
            file=discord.File(csv_file, filename=filename)
        )
        await interaction.followup.send("DMにCSVを送信しました。", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send(
            "DMを送信できませんでした。DM受信設定を確認してください。",
            ephemeral=True
        )


# =============================================================================
# スラッシュコマンド: /report（従来互換）
# =============================================================================
@tree.command(
    name="report",
    description="❤️リアクション数と投稿数を集計してCSVで出力します",
    guild=discord.Object(id=GUILD_ID) if GUILD_ID else None
)
@app_commands.describe(period="集計期間（YYYY-MM / last / all）")
async def report(interaction: discord.Interaction, period: str = "last"):
    """従来の /report コマンド（システム的なパース）"""

    # 権限チェック
    if ALLOWED_USER_IDS and interaction.user.id not in ALLOWED_USER_IDS:
        await interaction.response.send_message(
            "このコマンドを実行する権限がありません。",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    # 期間パース（システム的）
    try:
        if period.lower() == "all":
            parsed_period = "all"
        elif period.lower() == "last":
            parsed_period = "last"
        else:
            # YYYY-MM or YYYY/MM
            match = re.match(r'(\d{4})[-/](\d{1,2})', period)
            if match:
                parsed_period = {"year": int(match.group(1)), "month": int(match.group(2))}
            else:
                await interaction.followup.send(
                    f"無効な期間指定です: {period}（YYYY-MM / last / all）",
                    ephemeral=True
                )
                return
    except Exception as e:
        await interaction.followup.send(f"期間解析エラー: {e}", ephemeral=True)
        return

    # 期間計算
    start_dt, end_dt = get_period_range(parsed_period)
    start_utc = start_dt.astimezone(UTC) if start_dt else None
    end_utc = end_dt.astimezone(UTC) if end_dt else None

    # 集計実行
    try:
        result = await collect_stats(interaction.guild, start_utc, end_utc)
        user_stats = result["user_stats"]
    except Exception as e:
        await interaction.followup.send(str(e), ephemeral=True)
        return

    if not user_stats:
        await interaction.followup.send(
            f"{format_period_str(parsed_period)} のデータがありませんでした。",
            ephemeral=True
        )
        return

    # 平均いいね数を計算
    for user_id, stats in user_stats.items():
        if stats["posts"] > 0:
            stats["avg_hearts"] = round(stats["hearts"] / stats["posts"], 2)
        else:
            stats["avg_hearts"] = 0.0

    # ソート: hearts降順 → posts降順 → name昇順
    sorted_data = sorted(
        user_stats.values(),
        key=lambda x: (-x["hearts"], -x["posts"], x["name"])
    )

    # 投稿していないメンバーを取得
    posted_user_ids = set(user_stats.keys())
    inactive_members = []
    for member in interaction.guild.members:
        if member.bot:
            continue
        if member.id not in posted_user_ids:
            inactive_members.append(member.display_name)

    # CSV生成（投稿なしメンバーと合計を含む）
    csv_file = generate_csv(sorted_data, inactive_members=inactive_members, include_total=True)
    filename = f"{format_period_str(parsed_period).replace('年', '-').replace('月', '')}_report.csv"

    # レポートメッセージ作成
    total_hearts = sum(s["hearts"] for s in sorted_data)
    total_posts = sum(s["posts"] for s in sorted_data)
    report_message = f"**{format_period_str(parsed_period)}** の集計結果です。\n"
    report_message += f"📊 **全体合計**: いいね数 {total_hearts} / 投稿数 {total_posts}"

    # DM送信
    try:
        await interaction.user.send(
            report_message,
            file=discord.File(csv_file, filename=filename)
        )
        await interaction.followup.send("DMにCSVを送信しました。", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send(
            "DMを送信できませんでした。DM受信設定を確認してください。",
            ephemeral=True
        )


# =============================================================================
# スラッシュコマンド: /ask（AI自然言語対応）
# =============================================================================
@tree.command(
    name="ask",
    description="自然言語で集計を依頼できます（例: 先月のレポート、田中さんのいいね数）",
    guild=discord.Object(id=GUILD_ID) if GUILD_ID else None
)
@app_commands.describe(query="質問や依頼（例: 先月のレポート、@田中 のいいね数）")
async def ask(interaction: discord.Interaction, query: str):
    """AI統合の自然言語コマンド"""

    # 権限チェック
    if ALLOWED_USER_IDS and interaction.user.id not in ALLOWED_USER_IDS:
        await interaction.response.send_message(
            "このコマンドを実行する権限がありません。",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    # サーバーメンバー取得
    guild = interaction.guild
    if not guild:
        await interaction.followup.send("サーバー内で実行してください。", ephemeral=True)
        return

    members = [{"id": m.id, "name": m.display_name} for m in guild.members if not m.bot]
    current_date = datetime.now(JST).strftime("%Y-%m-%d")

    # AI解析
    intent = parse_intent_with_ai(query, current_date, members)

    if intent.get("error"):
        await interaction.followup.send(
            f"解析エラー: {intent['error']}",
            ephemeral=True
        )
        return

    if intent["action"] == "unknown":
        await interaction.followup.send(
            "すみません、リクエストを理解できませんでした。\n"
            "例: 「先月のレポート」「田中さんのいいね数」「2024年1月の集計」",
            ephemeral=True
        )
        return

    # 期間計算
    period = intent["period"]
    start_dt, end_dt = get_period_range(period)
    start_utc = start_dt.astimezone(UTC) if start_dt else None
    end_utc = end_dt.astimezone(UTC) if end_dt else None
    period_str = format_period_str(period)

    # 集計実行
    target_user_id = intent.get("target_user_id")

    try:
        result = await collect_stats(guild, start_utc, end_utc, target_user_id)
        user_stats = result["user_stats"]
    except Exception as e:
        await interaction.followup.send(str(e), ephemeral=True)
        return

    # 結果返却
    if intent["action"] == "user_likes":
        # 特定ユーザーのいいね数
        if not user_stats:
            target_name = "指定ユーザー"
            for m in members:
                if m["id"] == target_user_id:
                    target_name = m["name"]
                    break
            await interaction.followup.send(
                f"{period_str} の **{target_name}** さんのデータがありませんでした。",
                ephemeral=True
            )
            return

        data = list(user_stats.values())[0]
        avg_hearts = round(data['hearts'] / data['posts'], 2) if data['posts'] > 0 else 0.0
        await interaction.followup.send(
            f"**{period_str}** の **{data['name']}** さん\n"
            f"❤️ いいね数: **{data['hearts']}**\n"
            f"📝 投稿数: **{data['posts']}**\n"
            f"📊 平均いいね数: **{avg_hearts}**",
            ephemeral=True
        )

    else:
        # 全体レポート
        if not user_stats:
            await interaction.followup.send(
                f"{period_str} のデータがありませんでした。",
                ephemeral=True
            )
            return

        # 平均いいね数を計算
        for user_id, stats in user_stats.items():
            if stats["posts"] > 0:
                stats["avg_hearts"] = round(stats["hearts"] / stats["posts"], 2)
            else:
                stats["avg_hearts"] = 0.0

        sorted_data = sorted(
            user_stats.values(),
            key=lambda x: (-x["hearts"], -x["posts"], x["name"])
        )

        # 投稿していないメンバーを取得
        posted_user_ids = set(user_stats.keys())
        inactive_members = []
        for member in guild.members:
            if member.bot:
                continue
            if member.id not in posted_user_ids:
                inactive_members.append(member.display_name)

        # CSV生成（投稿なしメンバーと合計を含む）
        csv_file = generate_csv(sorted_data, inactive_members=inactive_members, include_total=True)
        filename = f"{period_str.replace('年', '-').replace('月', '')}_report.csv"

        # レポートメッセージ作成
        total_hearts = sum(s["hearts"] for s in sorted_data)
        total_posts = sum(s["posts"] for s in sorted_data)
        report_message = f"**{period_str}** の集計結果です。\n"
        report_message += f"📊 **全体合計**: いいね数 {total_hearts} / 投稿数 {total_posts}"

        try:
            await interaction.user.send(
                report_message,
                file=discord.File(csv_file, filename=filename)
            )
            await interaction.followup.send("DMにCSVを送信しました。", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(
                "DMを送信できませんでした。DM受信設定を確認してください。",
                ephemeral=True
            )


# =============================================================================
# イベント: @Bot メンション対応
# =============================================================================
@client.event
async def on_message(message: discord.Message):
    """@Bot メンションでの呼び出しを処理"""

    # 自分自身のメッセージは無視
    if message.author.bot:
        return

    # Botがメンションされていない場合は無視
    if not client.user or client.user not in message.mentions:
        return

    # 権限チェック
    if ALLOWED_USER_IDS and message.author.id not in ALLOWED_USER_IDS:
        await message.reply("このコマンドを実行する権限がありません。")
        return

    # サーバー内でのみ動作
    if not message.guild:
        await message.reply("サーバー内で実行してください。")
        return

    # メッセージからBotメンションを除去してクエリを取得
    query = message.content
    if client.user:
        query = query.replace(f"<@{client.user.id}>", "").replace(f"<@!{client.user.id}>", "").strip()

    if not query:
        await message.reply(
            "使い方: `@Bot 田中さんの先月のいいね数` または `@Bot 先月のレポート`"
        )
        return

    # サーバーメンバー取得
    guild = message.guild
    members = [{"id": m.id, "name": m.display_name} for m in guild.members if not m.bot]
    current_date = datetime.now(JST).strftime("%Y-%m-%d")

    # AI解析
    intent = parse_intent_with_ai(query, current_date, members)

    if intent.get("error"):
        error_msg = f"解析エラー: {intent['error']}"
        print(error_msg)
        try:
            await message.reply(error_msg)
        except Exception as e:
            print(f"Failed to send error message: {e}")
        return

    if intent["action"] == "unknown":
        error_msg = "すみません、リクエストを理解できませんでした。\n例: 「先月のレポート」「田中さんのいいね数」「2024年1月の集計」"
        print("Intent parse: unknown action")
        try:
            await message.reply(error_msg)
        except Exception as e:
            print(f"Failed to send unknown action message: {e}")
        return

    # 期間計算
    period = intent["period"]
    start_dt, end_dt = get_period_range(period)
    start_utc = start_dt.astimezone(UTC) if start_dt else None
    end_utc = end_dt.astimezone(UTC) if end_dt else None
    period_str = format_period_str(period)

    # 集計実行
    target_user_id = intent.get("target_user_id")

    try:
        result = await collect_stats(guild, start_utc, end_utc, target_user_id)
        user_stats = result["user_stats"]
    except Exception as e:
        error_msg = f"集計エラー: {e}"
        print(error_msg)
        try:
            await message.reply(error_msg)
        except Exception as e2:
            print(f"Failed to send error message: {e2}")
        return

    # データがない場合
    if not user_stats:
        if target_user_id:
            target_name = "指定ユーザー"
            for m in members:
                if m["id"] == target_user_id:
                    target_name = m["name"]
                    break
            try:
                await message.author.send(
                    f"{period_str} の **{target_name}** さんのデータがありませんでした。"
                )
            except discord.Forbidden:
                print("DM failed: user has DMs disabled.")
        else:
            try:
                await message.author.send(f"{period_str} のデータがありませんでした。")
            except discord.Forbidden:
                print("DM failed: user has DMs disabled.")
        return

    # 平均いいね数を計算
    for user_id, stats in user_stats.items():
        if stats["posts"] > 0:
            stats["avg_hearts"] = round(stats["hearts"] / stats["posts"], 2)
        else:
            stats["avg_hearts"] = 0.0

    # ソート: hearts降順 → posts降順 → name昇順
    sorted_data = sorted(
        user_stats.values(),
        key=lambda x: (-x["hearts"], -x["posts"], x["name"])
    )

    # 投稿していないメンバーを取得
    posted_user_ids = set(user_stats.keys())
    inactive_members = []
    for member in guild.members:
        if member.bot:
            continue
        if member.id not in posted_user_ids:
            inactive_members.append(member.display_name)

    # CSV生成（投稿なしメンバーと合計を含む）
    csv_file = generate_csv(sorted_data, inactive_members=inactive_members, include_total=True)
    filename = f"{period_str.replace('年', '-').replace('月', '')}_report.csv"

    # レポートメッセージ作成
    total_hearts = sum(s["hearts"] for s in sorted_data)
    total_posts = sum(s["posts"] for s in sorted_data)
    report_message = f"**{period_str}** の集計結果です。\n"
    report_message += f"📊 **全体合計**: いいね数 {total_hearts} / 投稿数 {total_posts}"

    # DMで送信
    try:
        await message.author.send(
            report_message,
            file=discord.File(csv_file, filename=filename)
        )
    except discord.Forbidden:
        print("DM failed: user has DMs disabled.")


# =============================================================================
# ランチ制度: 部署抽出
# =============================================================================
def extract_department_from_nickname(nickname: str) -> str | None:
    """
    ニックネームから部署を抽出する。
    形式: 【部署名】名前（ニックネーム）
    """
    match = re.match(r'【(.+?)】', nickname)
    return match.group(1) if match else None


def extract_departments_list(nickname: str) -> list[str]:
    """
    ニックネームから部署をリストで抽出する。
    例: 【CTO室/マーケ】畑 来世人 → ["CTO室", "マーケ"]
    """
    match = re.match(r'【(.+?)】', nickname)
    if not match:
        return ["不明"]
    dept_str = match.group(1)
    # /で分割して複数部署を取得
    depts = [d.strip() for d in dept_str.split('/') if d.strip()]
    return depts if depts else ["不明"]


def extract_name_from_nickname(nickname: str) -> str:
    """ニックネームから名前部分を抽出する。"""
    # 改行を除去
    name = nickname.replace("\n", "").replace("\r", "")
    # 【部署】を除去
    name = re.sub(r'【.+?】', '', name).strip()
    # （ニックネーム）を除去
    name = re.sub(r'（.+?）$', '', name).strip()
    name = re.sub(r'\(.+?\)$', '', name).strip()
    return name


def normalize_name(name: str) -> str:
    """名前を正規化する（スペース・改行除去、Unicode正規化）"""
    import unicodedata
    # Unicode正規化（異体字などを統一）
    normalized = unicodedata.normalize('NFKC', name)
    # スペース・改行除去（全角・半角）
    normalized = normalized.replace(" ", "").replace("　", "")
    normalized = normalized.replace("\n", "").replace("\r", "")
    normalized = normalized.strip()
    return normalized


def find_member_by_name(guild: discord.Guild, form_name: str) -> discord.Member | None:
    """フォームの名前からDiscordメンバーを検索する（マッチング甘め）"""
    form_normalized = normalize_name(form_name)

    for member in guild.members:
        if member.bot:
            continue
        display = member.display_name or member.name
        extracted_name = extract_name_from_nickname(display)
        extracted_normalized = normalize_name(extracted_name)

        # 正規化後の完全一致
        if extracted_normalized == form_normalized:
            return member

        # 正規化後の部分一致
        if form_normalized in extracted_normalized or extracted_normalized in form_normalized:
            return member

        # 元の名前での部分一致
        if form_name.strip() in display:
            return member

    return None


def get_member_department(member: discord.Member) -> str:
    """メンバーの部署を取得"""
    display = member.display_name or member.name
    dept = extract_department_from_nickname(display)
    return dept if dept else "不明"


# =============================================================================
# ランチ制度: フォームパーサー
# =============================================================================
def parse_lunch_form(content: str) -> dict | None:
    """フォーム投稿からランチ制度データを抽出する。"""
    if '【代表者名】' not in content:
        return None
    try:
        result = {}
        match = re.search(r'【代表者名】\s*\n(.+?)(?=\n【|$)', content, re.DOTALL)
        result["representative"] = match.group(1).strip() if match else ""
        match = re.search(r'【代表者の所属部署】\s*\n(.+?)(?=\n【|$)', content, re.DOTALL)
        result["department"] = match.group(1).strip() if match else ""
        match = re.search(r'【ランチ実施日】\s*\n(.+?)(?=\n【|$)', content, re.DOTALL)
        result["date"] = match.group(1).strip() if match else ""
        match = re.search(r'【参加人数】\s*\n(\d+)', content)
        result["participant_count"] = int(match.group(1)) if match else 0
        match = re.search(r'【参加メンバー】\s*\n(.+?)(?=\n【|$)', content, re.DOTALL)
        if match:
            members_text = match.group(1).strip()
            result["participants"] = [m.strip() for m in members_text.split('\n') if m.strip()]
        else:
            result["participants"] = []
        match = re.search(r'【合計金額（税込）】\s*\n(\d+)', content)
        result["total_amount"] = int(match.group(1)) if match else 0
        match = re.search(r'【ランチ会議の感想をひとこと】\s*\n(.+?)(?=\n【|$)', content, re.DOTALL)
        result["comment"] = match.group(1).strip() if match else ""
        if not result["representative"] or not result["participants"]:
            return None
        return result
    except Exception:
        return None


# =============================================================================
# ランチ制度: 集計関数
# =============================================================================
async def collect_lunch_stats(
    guild: discord.Guild,
    start_utc: datetime | None = None,
    end_utc: datetime | None = None
) -> dict:
    """ランチ制度の利用状況を集計する。"""
    # スレッドから投稿を取得
    thread = guild.get_thread(LUNCH_THREAD_ID)
    if not thread:
        try:
            thread = await client.fetch_channel(LUNCH_THREAD_ID)
        except Exception as e:
            raise Exception(f"ランチ制度スレッド {LUNCH_THREAD_ID} が見つかりません: {e}")

    records = []
    user_counts = defaultdict(int)
    user_departments = {}
    dept_counts = defaultdict(int)
    total_amount = 0
    unique_participants = set()

    try:
        async for message in thread.history(
            after=start_utc,
            before=end_utc,
            limit=None,
            oldest_first=True
        ):
            # ランチ制度はBot投稿（フォーム連携）も集計対象
            parsed = parse_lunch_form(message.content)
            if not parsed:
                continue
            records.append({**parsed, "message_id": message.id, "posted_at": message.created_at})
            for participant in parsed["participants"]:
                user_counts[participant] += 1
                unique_participants.add(participant)
                if participant not in user_departments:
                    member = find_member_by_name(guild, participant)
                    if member:
                        # 複数部署をリストで取得
                        depts = extract_departments_list(member.display_name or member.name)
                        user_departments[participant] = depts
                    else:
                        user_departments[participant] = ["不明"]
                # 部署別カウント（各部署にカウント）
                for dept in user_departments.get(participant, ["不明"]):
                    dept_counts[dept] += 1
            total_amount += parsed["total_amount"]
    except discord.Forbidden:
        raise Exception(f"スレッド <#{LUNCH_THREAD_ID}> の履歴を読む権限がありません。")

    return {
        "records": records,
        "user_departments": user_departments,
        "dept_counts": dict(dept_counts),
        "user_counts": dict(user_counts),
        "total_events": len(records),
        "total_participants": sum(len(r["participants"]) for r in records),
        "unique_participants": unique_participants,
        "total_amount": total_amount
    }


def generate_lunch_csv(stats: dict, total_members: int) -> str:
    """ランチ制度集計結果をCSV形式で出力"""
    output = io.StringIO()
    writer = csv.writer(output)

    unique_count = len(stats["unique_participants"])
    usage_rate = (unique_count / total_members * 100) if total_members > 0 else 0

    sorted_users = sorted(stats["user_counts"].items(), key=lambda x: (-x[1], x[0]))
    sorted_depts = sorted(stats["dept_counts"].items(), key=lambda x: (-x[1], x[0]))
    summary_data = [
        ("チャンネルメンバー数", total_members),
        ("利用者数", unique_count),
        ("利用率", f"{usage_rate:.1f}%")
    ]

    max_rows = max(len(sorted_users), len(sorted_depts), len(summary_data))

    writer.writerow(["名前", "部署", "参加回数", "", "部署", "部署別参加回数", "", "項目", "値"])

    for i in range(max_rows):
        row = []
        if i < len(sorted_users):
            name, count = sorted_users[i]
            depts = stats["user_departments"].get(name, ["不明"])
            # 複数部署の場合、名前と部署をセル内改行で表示
            if isinstance(depts, list) and len(depts) > 1:
                name_cell = "\n".join([name] * len(depts))
                dept_cell = "\n".join(depts)
            else:
                name_cell = name
                dept_cell = depts[0] if isinstance(depts, list) else depts
            row.extend([name_cell, dept_cell, count])
        else:
            row.extend(["", "", ""])
        row.append("")
        if i < len(sorted_depts):
            dept_name, dept_count = sorted_depts[i]
            row.extend([dept_name, dept_count])
        else:
            row.extend(["", ""])
        row.append("")
        if i < len(summary_data):
            item, value = summary_data[i]
            row.extend([item, value])
        else:
            row.extend(["", ""])
        writer.writerow(row)

    return output.getvalue()


# =============================================================================
# ランチ制度: 期間パース
# =============================================================================
def parse_lunch_period(period: str) -> tuple[int, int] | str | None:
    """
    期間文字列をパースして (year, month) または "all" を返す。
    対応: "2024-01", "last", "this", "-1"〜"-N", "all"
    """
    period_lower = period.lower().strip()
    now = datetime.now(JST)

    if period_lower in ("all", "全期間"):
        return "all"
    if period_lower in ("last", "先月", "-1"):
        if now.month == 1:
            return (now.year - 1, 12)
        return (now.year, now.month - 1)
    if period_lower in ("this", "今月", "0"):
        return (now.year, now.month)
    match = re.match(r'^-(\d+)$', period_lower)
    if match:
        months_ago = int(match.group(1))
        year, month = now.year, now.month - months_ago
        while month <= 0:
            month += 12
            year -= 1
        return (year, month)
    match = re.match(r'^(\d{4})-(\d{2})$', period)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    return None


def get_lunch_period_range(year: int, month: int) -> tuple[datetime, datetime]:
    """指定年月の開始・終了日時をUTCで返す"""
    start_jst = datetime(year, month, 1, 0, 0, 0, tzinfo=JST)
    if month == 12:
        end_jst = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=JST)
    else:
        end_jst = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=JST)
    return start_jst.astimezone(UTC), end_jst.astimezone(UTC)


# =============================================================================
# ランチ制度: スラッシュコマンド
# =============================================================================
@tree.command(
    name="lunch_report",
    description="ランチ制度の利用状況レポートを生成",
    guild=discord.Object(id=GUILD_ID) if GUILD_ID else None
)
@app_commands.describe(period="集計期間（例: 2024-01, last, -2, all）")
async def lunch_report_command(interaction: discord.Interaction, period: str):
    """ランチ制度レポートコマンド"""
    if interaction.user.id not in ALLOWED_USER_IDS:
        await interaction.response.send_message("このコマンドを実行する権限がありません。", ephemeral=True)
        return

    parsed = parse_lunch_period(period)
    if parsed is None:
        await interaction.response.send_message(
            "期間の形式が正しくありません。例: 2024-01, last, -2, all", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        guild = interaction.guild
        if parsed == "all":
            start_utc, end_utc = None, None
            period_label = "全期間"
            filename = "lunch_report_all.csv"
        else:
            year, month = parsed
            start_utc, end_utc = get_lunch_period_range(year, month)
            period_label = f"{year}年{month}月"
            filename = f"lunch_report_{year}-{month:02d}.csv"

        lunch_channel = guild.get_channel(LUNCH_CHANNEL_ID)
        if not lunch_channel:
            await interaction.followup.send("ランチチャンネルが見つかりません。", ephemeral=True)
            return

        stats = await collect_lunch_stats(guild, start_utc, end_utc)
        if stats["total_events"] == 0:
            await interaction.followup.send(f"{period_label}のランチ制度利用データがありません。", ephemeral=True)
            return

        channel_members = [m for m in lunch_channel.members if not m.bot]
        total_members = len(channel_members)
        csv_content = generate_lunch_csv(stats, total_members)

        file = discord.File(io.BytesIO(csv_content.encode('utf-8-sig')), filename=filename)

        unique_count = len(stats["unique_participants"])
        usage_rate = (unique_count / total_members * 100) if total_members > 0 else 0
        summary = (
            f"**ランチ制度 利用状況レポート {period_label}**\n\n"
            f"📊 イベント数: {stats['total_events']}回\n"
            f"👥 利用者: {unique_count}人 / チャンネルメンバー {total_members}人\n"
            f"📈 利用率: {usage_rate:.1f}%\n"
            f"💰 総金額: ¥{stats['total_amount']:,}"
        )

        try:
            await interaction.user.send(summary, file=file)
            await interaction.followup.send("レポートをDMに送信しました。", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("DMを送信できませんでした。DM設定を確認してください。", ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"エラーが発生しました: {e}", ephemeral=True)


# =============================================================================
# 本気AI: 集計関数
# =============================================================================
async def collect_ai_stats(
    guild: discord.Guild,
    start_utc: datetime | None = None,
    end_utc: datetime | None = None
) -> dict:
    """本気AI提出の統計を集計する（名前:フィールドベース）。"""
    # スレッドから投稿を取得
    thread = guild.get_thread(AI_THREAD_ID)
    if not thread:
        try:
            thread = await client.fetch_channel(AI_THREAD_ID)
        except Exception as e:
            raise Exception(f"スレッド {AI_THREAD_ID} が見つかりません: {e}")

    user_counts = defaultdict(int)
    user_departments = {}
    unique_participants = set()
    monthly_counts = defaultdict(int)
    debug_count = 0
    debug_matched = 0
    debug_unmatched_samples = []  # マッチしなかったメッセージのサンプル

    try:
        async for message in thread.history(
            after=start_utc,
            before=end_utc,
            limit=None,
            oldest_first=True
        ):
            debug_count += 1
            content = message.content

            # ハイブリッド方式で名前を抽出（正規表現優先、失敗時のみAI）
            # 最初の5件はデバッグログを出力
            enable_debug = debug_count <= 5
            if enable_debug:
                print(f"Processing message {debug_count}...", flush=True)
            name = extract_name_hybrid(content, debug=enable_debug)

            if name:
                debug_matched += 1
                raw_name = name
                # 名前を正規化
                normalized_name = normalize_name(raw_name)

                # デバッグ: 正規化前後を表示
                if enable_debug:
                    print(f"DEBUG: raw='{raw_name}' -> normalized='{normalized_name}'")
                if normalized_name:
                    user_counts[normalized_name] += 1
                    unique_participants.add(normalized_name)

                    # 部署を取得（Discordメンバーから検索）
                    if normalized_name not in user_departments:
                        member = find_member_by_name(guild, raw_name)
                        if member:
                            depts = extract_departments_list(member.display_name or member.name)
                            user_departments[normalized_name] = depts
                        else:
                            user_departments[normalized_name] = ["不明"]

                    # 月別カウント
                    month_key = message.created_at.astimezone(JST).strftime("%Y-%m")
                    monthly_counts[month_key] += 1
            else:
                # マッチしなかったメッセージをサンプル保存（最大3件）
                if len(debug_unmatched_samples) < 3:
                    debug_unmatched_samples.append(content[:150])

    except discord.Forbidden:
        raise Exception(f"スレッド <#{AI_THREAD_ID}> の履歴を読む権限がありません。")

    # チャンネルからも投稿数を取得
    channel = guild.get_channel(AI_CHANNEL_ID)
    if not channel:
        try:
            channel = await client.fetch_channel(AI_CHANNEL_ID)
        except:
            channel = None

    channel_monthly_counts = defaultdict(int)
    channel_debug_count = 0
    channel_unique_count = 0
    seen_urls = set()  # 既出URLを追跡
    if channel:
        try:
            async for message in channel.history(
                after=start_utc,
                before=end_utc,
                limit=None,
                oldest_first=True
            ):
                channel_debug_count += 1
                content = message.content

                # URLを抽出
                urls = extract_urls(content)

                # ma-ji.ai のURLのみを重複チェック対象にする
                maji_urls = {u for u in urls if 'ma-ji.ai' in u}

                if maji_urls:
                    # 新しいURLがあるかチェック
                    new_urls = maji_urls - seen_urls
                    if new_urls:
                        # 新しいURLがある = ユニークな投稿
                        seen_urls.update(new_urls)
                        channel_unique_count += 1
                        month_key = message.created_at.astimezone(JST).strftime("%Y-%m")
                        channel_monthly_counts[month_key] += 1
                    # 既出URLのみ = リマインド投稿 → スキップ
                else:
                    # URLがない投稿も一応カウント
                    channel_unique_count += 1
                    month_key = message.created_at.astimezone(JST).strftime("%Y-%m")
                    channel_monthly_counts[month_key] += 1
        except discord.Forbidden:
            pass

    return {
        "user_counts": dict(user_counts),
        "user_departments": user_departments,
        "unique_participants": unique_participants,
        "monthly_counts": dict(monthly_counts),
        "channel_monthly_counts": dict(channel_monthly_counts),
        "total_posts": sum(user_counts.values()),
        "debug_thread_messages": debug_count,
        "debug_matched": debug_matched,
        "debug_channel_messages": channel_debug_count,
        "debug_unmatched_samples": debug_unmatched_samples
    }


def generate_ai_csv(stats: dict, total_members: int) -> str:
    """本気AI集計結果をCSV形式で出力"""
    output = io.StringIO()
    writer = csv.writer(output)

    unique_count = len(stats["unique_participants"])
    participation_rate = (unique_count / total_members * 100) if total_members > 0 else 0

    sorted_users = sorted(stats["user_counts"].items(), key=lambda x: (-x[1], x[0]))
    sorted_months = sorted(stats["monthly_counts"].items())
    sorted_channel_months = sorted(stats["channel_monthly_counts"].items())

    summary_data = [
        ("参加者数", unique_count),
        ("全体メンバー数", total_members),
        ("参加率", f"{participation_rate:.1f}%"),
        ("総投稿数", stats["total_posts"])
    ]

    # 最大行数を計算
    max_rows = max(len(sorted_users), len(sorted_months), len(sorted_channel_months), len(summary_data))

    # ヘッダー
    writer.writerow([
        "名前", "部署", "投稿回数",
        "",
        "月", "スレッド投稿数",
        "",
        "月", "チャンネル投稿数",
        "",
        "項目", "値"
    ])

    for i in range(max_rows):
        row = []

        # セクション1: ユーザー別
        if i < len(sorted_users):
            name, count = sorted_users[i]
            depts = stats["user_departments"].get(name, ["不明"])
            # 複数部署の場合、名前と部署をセル内改行で表示
            if isinstance(depts, list) and len(depts) > 1:
                name_cell = "\n".join([name] * len(depts))
                dept_cell = "\n".join(depts)
            else:
                name_cell = name
                dept_cell = depts[0] if isinstance(depts, list) else depts
            row.extend([name_cell, dept_cell, count])
        else:
            row.extend(["", "", ""])

        row.append("")

        # セクション2: 月別（スレッド）
        if i < len(sorted_months):
            month, count = sorted_months[i]
            row.extend([month, count])
        else:
            row.extend(["", ""])

        row.append("")

        # セクション3: 月別（チャンネル）
        if i < len(sorted_channel_months):
            month, count = sorted_channel_months[i]
            row.extend([month, count])
        else:
            row.extend(["", ""])

        row.append("")

        # セクション4: サマリー
        if i < len(summary_data):
            item, value = summary_data[i]
            row.extend([item, value])
        else:
            row.extend(["", ""])

        writer.writerow(row)

    return output.getvalue()


# =============================================================================
# 本気AI: スラッシュコマンド
# =============================================================================
@tree.command(
    name="ai_report",
    description="本気AI提出の利用状況レポートを生成",
    guild=discord.Object(id=GUILD_ID) if GUILD_ID else None
)
@app_commands.describe(period="集計期間（例: 2024-01, last, -2, all）")
async def ai_report_command(interaction: discord.Interaction, period: str):
    """本気AIレポートコマンド"""
    if interaction.user.id not in ALLOWED_USER_IDS:
        await interaction.response.send_message("このコマンドを実行する権限がありません。", ephemeral=True)
        return

    parsed = parse_lunch_period(period)
    if parsed is None:
        await interaction.response.send_message(
            "期間の形式が正しくありません。例: 2024-01, last, -2, all", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        guild = interaction.guild
        if parsed == "all":
            start_utc, end_utc = None, None
            period_label = "全期間"
            filename = "ai_report_all.csv"
        else:
            year, month = parsed
            start_utc, end_utc = get_lunch_period_range(year, month)
            period_label = f"{year}年{month}月"
            filename = f"ai_report_{year}-{month:02d}.csv"

        # 期間を明確に表示
        if start_utc and end_utc:
            start_jst = start_utc.astimezone(JST)
            end_jst = end_utc.astimezone(JST)
            period_range = f"{start_jst.strftime('%Y-%m-%d')} 〜 {end_jst.strftime('%Y-%m-%d')}"
        else:
            period_range = "全期間"

        stats = await collect_ai_stats(guild, start_utc, end_utc)
        if stats["total_posts"] == 0:
            debug_info = (
                f"スレッド読取数: {stats.get('debug_thread_messages', 0)}, "
                f"マッチ数: {stats.get('debug_matched', 0)}, "
                f"チャンネル読取数: {stats.get('debug_channel_messages', 0)}"
            )
            unmatched = stats.get('debug_unmatched_samples', [])
            sample_info = ""
            if unmatched:
                sample_info = "\n\n**マッチしなかったサンプル:**\n" + "\n---\n".join(unmatched[:2])
            await interaction.followup.send(
                f"{period_label}（{period_range}）の本気AI提出データがありません。\n({debug_info}){sample_info}",
                ephemeral=True
            )
            return

        # 全体メンバー数（Bot除外）
        total_members = sum(1 for m in guild.members if not m.bot)
        csv_content = generate_ai_csv(stats, total_members)

        file = discord.File(io.BytesIO(csv_content.encode('utf-8-sig')), filename=filename)

        unique_count = len(stats["unique_participants"])
        participation_rate = (unique_count / total_members * 100) if total_members > 0 else 0
        summary = (
            f"**本気AI 提出状況レポート {period_label}**\n"
            f"📅 期間: {period_range}\n\n"
            f"📊 総投稿数: {stats['total_posts']}回\n"
            f"👥 参加者: {unique_count}人 / {total_members}人\n"
            f"📈 参加率: {participation_rate:.1f}%"
        )

        try:
            await interaction.user.send(summary, file=file)
            await interaction.followup.send("レポートをDMに送信しました。", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("DMを送信できませんでした。DM設定を確認してください。", ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"エラーが発生しました: {e}", ephemeral=True)


# =============================================================================
# デバッグ: チャンネル情報取得
# =============================================================================
@tree.command(
    name="channel_info",
    description="設定されているチャンネル/スレッドの情報を表示",
    guild=discord.Object(id=GUILD_ID) if GUILD_ID else None
)
async def channel_info_command(interaction: discord.Interaction):
    """チャンネル情報表示コマンド"""
    if interaction.user.id not in ALLOWED_USER_IDS:
        await interaction.response.send_message("このコマンドを実行する権限がありません。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    info_lines = ["**設定されているチャンネル/スレッド情報**\n"]

    # レベッターチャンネル
    for ch_id in CHANNEL_IDS:
        try:
            ch = await client.fetch_channel(ch_id)
            info_lines.append(f"📢 レベッター: **{ch.name}** (ID: {ch_id})")
        except:
            info_lines.append(f"❌ レベッター: 取得失敗 (ID: {ch_id})")

    # ランチ制度スレッド
    try:
        ch = await client.fetch_channel(LUNCH_THREAD_ID)
        info_lines.append(f"🍽️ ランチ制度スレッド: **{ch.name}** (ID: {LUNCH_THREAD_ID})")
    except:
        info_lines.append(f"❌ ランチ制度スレッド: 取得失敗 (ID: {LUNCH_THREAD_ID})")

    # ランチ制度チャンネル
    try:
        ch = await client.fetch_channel(LUNCH_CHANNEL_ID)
        info_lines.append(f"🍽️ ランチ制度チャンネル: **{ch.name}** (ID: {LUNCH_CHANNEL_ID})")
    except:
        info_lines.append(f"❌ ランチ制度チャンネル: 取得失敗 (ID: {LUNCH_CHANNEL_ID})")

    # 本気AIスレッド
    try:
        ch = await client.fetch_channel(AI_THREAD_ID)
        info_lines.append(f"🤖 本気AIスレッド: **{ch.name}** (ID: {AI_THREAD_ID})")
    except:
        info_lines.append(f"❌ 本気AIスレッド: 取得失敗 (ID: {AI_THREAD_ID})")

    # 本気AIチャンネル
    try:
        ch = await client.fetch_channel(AI_CHANNEL_ID)
        info_lines.append(f"🤖 本気AIチャンネル: **{ch.name}** (ID: {AI_CHANNEL_ID})")
    except:
        info_lines.append(f"❌ 本気AIチャンネル: 取得失敗 (ID: {AI_CHANNEL_ID})")

    await interaction.followup.send("\n".join(info_lines), ephemeral=True)


# =============================================================================
# いいねした回数: スラッシュコマンド
# =============================================================================
@tree.command(
    name="like_stats",
    description="各メンバーがいいねした回数を集計",
    guild=discord.Object(id=GUILD_ID) if GUILD_ID else None
)
@app_commands.describe(period="集計期間（例: 2024-01, last, -2, all）")
async def like_stats_command(interaction: discord.Interaction, period: str):
    """いいねした回数レポートコマンド"""
    if interaction.user.id not in ALLOWED_USER_IDS:
        await interaction.response.send_message("このコマンドを実行する権限がありません。", ephemeral=True)
        return

    parsed = parse_lunch_period(period)
    if parsed is None:
        await interaction.response.send_message(
            "期間の形式が正しくありません。例: 2024-01, last, -2, all", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        guild = interaction.guild
        if parsed == "all":
            start_utc, end_utc = None, None
            period_label = "全期間"
            filename = "like_stats_all.csv"
        else:
            year, month = parsed
            start_utc, end_utc = get_lunch_period_range(year, month)
            period_label = f"{year}年{month}月"
            filename = f"like_stats_{year}-{month:02d}.csv"

        # いいねした回数を取得（トップ投稿も収集）
        result = await collect_stats(guild, start_utc, end_utc, collect_top_posts=True)
        user_stats = result["user_stats"]
        top_posts = result["top_posts"]

        if not user_stats:
            await interaction.followup.send(
                f"{period_label}のデータがありません。",
                ephemeral=True
            )
            return

        # いいねした回数でソート
        sorted_by_likes = sorted(
            [(uid, data) for uid, data in user_stats.items() if data.get("likes_given", 0) > 0],
            key=lambda x: -x[1].get("likes_given", 0)
        )

        # 部署別集計を計算
        dept_stats = defaultdict(lambda: {"posts": 0, "hearts": 0, "likes_given": 0})
        for uid, data in user_stats.items():
            dept, _ = extract_department(data["name"])
            if not dept:
                dept = "不明"
            dept_stats[dept]["posts"] += data.get("posts", 0)
            dept_stats[dept]["hearts"] += data.get("hearts", 0)
            dept_stats[dept]["likes_given"] += data.get("likes_given", 0)

        # 部署別を投稿数でソート
        sorted_depts = sorted(dept_stats.items(), key=lambda x: -x[1]["posts"])

        # CSV生成
        output = io.StringIO()
        writer = csv.writer(output)

        # 個人別、部署別、トップ投稿を横並びで表示
        max_rows = max(len(sorted_by_likes), len(sorted_depts), len(top_posts))

        writer.writerow([
            "部署", "名前", "いいねした回数", "いいねもらった数", "投稿数",
            "",
            "部署", "部署別投稿数", "部署別いいねもらった数",
            "",
            "順位", "投稿者", "いいね数", "投稿日時", "投稿内容"
        ])

        total_likes_given = 0
        total_hearts = 0
        total_posts = 0
        for i in range(max_rows):
            row = []

            # 個人別
            if i < len(sorted_by_likes):
                uid, data = sorted_by_likes[i]
                dept, name_only = extract_department(data["name"])
                likes_given = data.get("likes_given", 0)
                total_likes_given += likes_given
                total_hearts += data["hearts"]
                total_posts += data["posts"]
                row.extend([dept, name_only, likes_given, data["hearts"], data["posts"]])
            else:
                row.extend(["", "", "", "", ""])

            row.append("")  # 区切り

            # 部署別
            if i < len(sorted_depts):
                dept_name, dept_data = sorted_depts[i]
                row.extend([dept_name, dept_data["posts"], dept_data["hearts"]])
            else:
                row.extend(["", "", ""])

            row.append("")  # 区切り

            # トップ投稿
            if i < len(top_posts):
                post = top_posts[i]
                _, author_name = extract_department(post["author"])
                # 投稿内容は最初の100文字まで
                content_preview = post["content"][:100].replace("\n", " ")
                if len(post["content"]) > 100:
                    content_preview += "..."
                row.extend([i + 1, author_name, post["hearts"], post["date"], content_preview])
            else:
                row.extend(["", "", "", "", ""])

            writer.writerow(row)

        # 合計行
        writer.writerow([
            "", "【合計】", total_likes_given, total_hearts, total_posts,
            "", "", "", "",
            "", "", "", "", ""
        ])

        csv_content = output.getvalue()
        file = discord.File(io.BytesIO(csv_content.encode('utf-8-sig')), filename=filename)

        summary = (
            f"**いいねした回数レポート {period_label}**\n\n"
            f"👍 いいねした人数: {len(sorted_by_likes)}人\n"
            f"❤️ 総いいね数: {total_likes_given}回"
        )

        try:
            await interaction.user.send(summary, file=file)
            await interaction.followup.send("レポートをDMに送信しました。", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("DMを送信できませんでした。DM設定を確認してください。", ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"エラーが発生しました: {e}", ephemeral=True)


# =============================================================================
# イベント: Bot起動時
# =============================================================================
@client.event
async def on_ready():
    """Bot起動時の処理"""
    print(f"Logged in as {client.user}")

    # スラッシュコマンドを同期
    if GUILD_ID:
        guild = discord.Object(id=GUILD_ID)
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
        print(f"Commands synced to guild {GUILD_ID}")
    else:
        await tree.sync()
        print("Commands synced globally")

    print("Bot is ready!")


# =============================================================================
# メイン
# =============================================================================
if __name__ == "__main__":
    # バッファリング無効化（Railwayでログをリアルタイム表示）
    import sys
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    discord_token = os.environ.get("DISCORD_TOKEN")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    if not discord_token:
        print("Error: DISCORD_TOKEN 環境変数が設定されていません。")
        exit(1)

    if not gemini_key:
        print("Error: GEMINI_API_KEY 環境変数が設定されていません。")
        exit(1)

    # Gemini初期化（グローバル変数ai_modelを更新）
    ai_model = init_gemini()
    if ai_model:
        print("Gemini API initialized successfully")
    else:
        print("WARNING: Gemini API failed to initialize (GEMINI_API_KEY missing?)")

    client.run(discord_token)
