"""
Lunch Stats Bot
Discord ランチ制度利用状況 集計スクリプト
フォーム投稿からデータを抽出・集計
"""

import os
import csv
import io
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict

import discord
from discord import app_commands


# =============================================================================
# 設定値
# =============================================================================
GUILD_ID = 1172020927047942154
LUNCH_CHANNEL_ID = 1437763696096182363  # ランチ制度フォーム投稿チャンネル
ALLOWED_USER_IDS = [1340666940615823451, 1307922048731058247]
EXCLUDE_BOTS = True

# タイムゾーン
JST = ZoneInfo("Asia/Tokyo")
UTC = ZoneInfo("UTC")


# =============================================================================
# Bot 初期化
# =============================================================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# =============================================================================
# 部署抽出
# =============================================================================
def extract_department_from_nickname(nickname: str) -> str | None:
    """
    ニックネームから部署を抽出する。
    形式: 【部署名】名前（ニックネーム）
    例: 【社長室】與儀 あんり（あんり） → "社長室"
    """
    match = re.match(r'【(.+?)】', nickname)
    return match.group(1) if match else None


def extract_name_from_nickname(nickname: str) -> str:
    """
    ニックネームから名前部分を抽出する。
    形式: 【部署名】名前（ニックネーム）
    例: 【社長室】與儀 あんり（あんり） → "與儀 あんり"
    """
    # 【部署】を除去
    name = re.sub(r'【.+?】', '', nickname).strip()
    # （ニックネーム）を除去
    name = re.sub(r'（.+?）$', '', name).strip()
    name = re.sub(r'\(.+?\)$', '', name).strip()
    return name


def find_member_by_name(guild: discord.Guild, form_name: str) -> discord.Member | None:
    """
    フォームの名前からDiscordメンバーを検索する。
    """
    form_name_normalized = form_name.strip()

    for member in guild.members:
        if member.bot:
            continue

        # ニックネームから名前を抽出して比較
        display = member.display_name or member.name
        extracted_name = extract_name_from_nickname(display)

        # 完全一致
        if extracted_name == form_name_normalized:
            return member

        # 部分一致（名前がニックネームに含まれる）
        if form_name_normalized in display:
            return member

    return None


def get_member_department(member: discord.Member) -> str:
    """メンバーの部署を取得"""
    display = member.display_name or member.name
    dept = extract_department_from_nickname(display)
    return dept if dept else "不明"


# =============================================================================
# フォームパーサー
# =============================================================================
def parse_lunch_form(content: str) -> dict | None:
    """
    フォーム投稿からランチ制度データを抽出する。

    Returns:
        {
            "representative": str,        # 代表者名
            "department": str,            # 所属部署
            "date": str,                  # 実施日 (YYYY-MM-DD)
            "participant_count": int,     # 参加人数
            "participants": list[str],    # 参加メンバーリスト
            "total_amount": int,          # 合計金額
            "comment": str                # 感想
        }
        またはパース失敗時は None
    """
    # フォーム投稿かどうかの簡易チェック
    if '【代表者名】' not in content:
        return None

    try:
        result = {}

        # 代表者名
        match = re.search(r'【代表者名】\s*\n(.+?)(?=\n【|$)', content, re.DOTALL)
        result["representative"] = match.group(1).strip() if match else ""

        # 所属部署
        match = re.search(r'【代表者の所属部署】\s*\n(.+?)(?=\n【|$)', content, re.DOTALL)
        result["department"] = match.group(1).strip() if match else ""

        # 実施日
        match = re.search(r'【ランチ実施日】\s*\n(.+?)(?=\n【|$)', content, re.DOTALL)
        result["date"] = match.group(1).strip() if match else ""

        # 参加人数
        match = re.search(r'【参加人数】\s*\n(\d+)', content)
        result["participant_count"] = int(match.group(1)) if match else 0

        # 参加メンバー（複数行）
        match = re.search(r'【参加メンバー】\s*\n(.+?)(?=\n【|$)', content, re.DOTALL)
        if match:
            members_text = match.group(1).strip()
            # 改行で分割し、空行を除外
            result["participants"] = [m.strip() for m in members_text.split('\n') if m.strip()]
        else:
            result["participants"] = []

        # 合計金額
        match = re.search(r'【合計金額（税込）】\s*\n(\d+)', content)
        result["total_amount"] = int(match.group(1)) if match else 0

        # 感想
        match = re.search(r'【ランチ会議の感想をひとこと】\s*\n(.+?)(?=\n【|$)', content, re.DOTALL)
        result["comment"] = match.group(1).strip() if match else ""

        # 必須項目のチェック
        if not result["representative"] or not result["participants"]:
            return None

        return result

    except Exception:
        return None


# =============================================================================
# 集計関数
# =============================================================================
async def collect_lunch_stats(
    guild: discord.Guild,
    start_utc: datetime | None = None,
    end_utc: datetime | None = None
) -> dict:
    """
    ランチ制度の利用状況を集計する。

    Returns:
        {
            "records": list[dict],           # 各フォームのパース結果リスト
            "user_counts": dict[str, int],   # ユーザー別参加回数
            "user_departments": dict[str, str], # ユーザー別部署
            "dept_counts": dict[str, int],   # 部署別参加回数
            "total_events": int,             # 総イベント数
            "total_participants": int,       # 延べ参加人数
            "unique_participants": set,      # ユニーク参加者
            "total_amount": int              # 総金額
        }
    """
    channel = guild.get_channel(LUNCH_CHANNEL_ID)
    if not channel or not isinstance(channel, discord.TextChannel):
        raise Exception(f"チャンネル {LUNCH_CHANNEL_ID} が見つかりません。")

    records = []
    user_counts = defaultdict(int)
    user_departments = {}  # 名前 → 部署
    dept_counts = defaultdict(int)  # 部署 → 回数
    total_amount = 0
    unique_participants = set()

    try:
        async for message in channel.history(
            after=start_utc,
            before=end_utc,
            limit=None,
            oldest_first=True
        ):
            # Bot除外
            if EXCLUDE_BOTS and message.author.bot:
                continue

            # フォームをパース
            parsed = parse_lunch_form(message.content)
            if not parsed:
                continue

            records.append({
                **parsed,
                "message_id": message.id,
                "posted_at": message.created_at
            })

            # 参加者カウント & 部署取得
            for participant in parsed["participants"]:
                user_counts[participant] += 1
                unique_participants.add(participant)

                # 部署を取得（まだ取得していない場合）
                if participant not in user_departments:
                    member = find_member_by_name(guild, participant)
                    if member:
                        dept = get_member_department(member)
                        user_departments[participant] = dept
                    else:
                        user_departments[participant] = "不明"

                # 部署別カウント
                dept = user_departments.get(participant, "不明")
                dept_counts[dept] += 1

            total_amount += parsed["total_amount"]

    except discord.Forbidden:
        raise Exception(f"チャンネル <#{LUNCH_CHANNEL_ID}> の履歴を読む権限がありません。")

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
    """集計結果をCSV形式で出力"""
    output = io.StringIO()
    writer = csv.writer(output)

    # サマリー計算
    unique_count = len(stats["unique_participants"])
    usage_rate = (unique_count / total_members * 100) if total_members > 0 else 0

    # データ準備
    sorted_users = sorted(stats["user_counts"].items(), key=lambda x: (-x[1], x[0]))
    sorted_depts = sorted(stats["dept_counts"].items(), key=lambda x: (-x[1], x[0]))

    # サマリーデータ（縦並び）
    summary_data = [
        ("チャンネルメンバー数", total_members),
        ("利用者数", unique_count),
        ("利用率", f"{usage_rate:.1f}%")
    ]

    # 最大行数を計算
    max_rows = max(len(sorted_users), len(sorted_depts), len(summary_data))

    # ヘッダー
    writer.writerow([
        "名前", "部署", "参加回数",
        "",  # 区切り
        "部署", "部署別参加回数",
        "",  # 区切り
        "項目", "値"
    ])

    # データ行
    for i in range(max_rows):
        row = []

        # セクション1: ユーザー別
        if i < len(sorted_users):
            name, count = sorted_users[i]
            dept = stats["user_departments"].get(name, "不明")
            row.extend([name, dept, count])
        else:
            row.extend(["", "", ""])

        row.append("")  # 区切り

        # セクション2: 部署別
        if i < len(sorted_depts):
            dept_name, dept_count = sorted_depts[i]
            row.extend([dept_name, dept_count])
        else:
            row.extend(["", ""])

        row.append("")  # 区切り

        # セクション3: サマリー（縦並び）
        if i < len(summary_data):
            item, value = summary_data[i]
            row.extend([item, value])
        else:
            row.extend(["", ""])

        writer.writerow(row)

    return output.getvalue()


# =============================================================================
# 期間計算
# =============================================================================
def get_period_range(year: int, month: int) -> tuple[datetime, datetime]:
    """指定年月の開始・終了日時をUTCで返す"""
    start_jst = datetime(year, month, 1, 0, 0, 0, tzinfo=JST)

    if month == 12:
        end_jst = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=JST)
    else:
        end_jst = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=JST)

    return start_jst.astimezone(UTC), end_jst.astimezone(UTC)


# =============================================================================
# スラッシュコマンド
# =============================================================================
def parse_period(period: str) -> tuple[int, int] | str | None:
    """
    期間文字列をパースして (year, month) または "all" を返す。
    対応形式:
      - "2024-01" → 特定の月
      - "last", "先月" → 先月
      - "this", "今月" → 今月
      - "-1", "-2", "-3" → N ヶ月前
      - "all", "全期間" → 全期間
    """
    period_lower = period.lower().strip()
    now = datetime.now(JST)

    # 全期間
    if period_lower in ("all", "全期間"):
        return "all"

    # 先月
    if period_lower in ("last", "先月", "-1"):
        if now.month == 1:
            return (now.year - 1, 12)
        else:
            return (now.year, now.month - 1)

    # 今月
    if period_lower in ("this", "今月", "0"):
        return (now.year, now.month)

    # N ヶ月前（-2, -3, ...）
    match = re.match(r'^-(\d+)$', period_lower)
    if match:
        months_ago = int(match.group(1))
        year = now.year
        month = now.month - months_ago
        while month <= 0:
            month += 12
            year -= 1
        return (year, month)

    # YYYY-MM 形式
    match = re.match(r'^(\d{4})-(\d{2})$', period)
    if match:
        return (int(match.group(1)), int(match.group(2)))

    return None


@tree.command(
    name="lunch_report",
    description="ランチ制度の利用状況レポートを生成",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(
    period="集計期間（例: 2024-01, last, -2, all）"
)
async def lunch_report_command(interaction: discord.Interaction, period: str):
    """ランチ制度レポートコマンド"""

    # 権限チェック
    if interaction.user.id not in ALLOWED_USER_IDS:
        await interaction.response.send_message(
            "このコマンドを実行する権限がありません。",
            ephemeral=True
        )
        return

    # 期間パース
    parsed = parse_period(period)
    if parsed is None:
        await interaction.response.send_message(
            "期間の形式が正しくありません。例: 2024-01, last, -2, all",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        guild = interaction.guild

        # 全期間 or 特定月
        if parsed == "all":
            start_utc, end_utc = None, None
            period_label = "全期間"
            filename = "lunch_report_all.csv"
        else:
            year, month = parsed
            start_utc, end_utc = get_period_range(year, month)
            period_label = f"{year}年{month}月"
            filename = f"lunch_report_{year}-{month:02d}.csv"

        # ランチチャンネルを取得
        lunch_channel = guild.get_channel(LUNCH_CHANNEL_ID)
        if not lunch_channel:
            await interaction.followup.send(
                "ランチチャンネルが見つかりません。",
                ephemeral=True
            )
            return

        # 集計
        stats = await collect_lunch_stats(guild, start_utc, end_utc)

        if stats["total_events"] == 0:
            await interaction.followup.send(
                f"{period_label}のランチ制度利用データがありません。",
                ephemeral=True
            )
            return

        # チャンネルメンバー数（Bot除外）= 分母
        channel_members = [m for m in lunch_channel.members if not m.bot]
        total_members = len(channel_members)

        # CSV生成
        csv_content = generate_lunch_csv(stats, total_members)

        # ファイル送信
        file = discord.File(
            io.BytesIO(csv_content.encode('utf-8-sig')),
            filename=filename
        )

        # サマリーメッセージ
        unique_count = len(stats["unique_participants"])
        usage_rate = (unique_count / total_members * 100) if total_members > 0 else 0
        summary = (
            f"**ランチ制度 利用状況レポート {period_label}**\n\n"
            f"📊 イベント数: {stats['total_events']}回\n"
            f"👥 利用者: {unique_count}人 / チャンネルメンバー {total_members}人\n"
            f"📈 利用率: {usage_rate:.1f}%\n"
            f"💰 総金額: ¥{stats['total_amount']:,}"
        )

        # DMで送信
        try:
            await interaction.user.send(summary, file=file)
            await interaction.followup.send(
                "レポートをDMに送信しました。",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "DMを送信できませんでした。DM設定を確認してください。",
                ephemeral=True
            )

    except Exception as e:
        await interaction.followup.send(
            f"エラーが発生しました: {e}",
            ephemeral=True
        )


# =============================================================================
# イベントハンドラ
# =============================================================================
@client.event
async def on_ready():
    """Bot起動時の処理"""
    print(f"Logged in as {client.user}")

    # スラッシュコマンド同期
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print("Slash commands synced.")


# =============================================================================
# メイン
# =============================================================================
def main():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN environment variable is not set.")
        return

    client.run(token)


if __name__ == "__main__":
    main()
