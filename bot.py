


import json
import os
import logging
import time
from datetime import datetime, timezone

import discord
from discord.ext import commands


# ══════════════════════════════════════════════
import os

TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise Exception("TOKEN manquant")
# ══════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("bot")

os.makedirs("data", exist_ok=True)
CLANS_FILE          = "data/clans.json"
VOICE_FILE          = "data/voice.json"
PROTECTED_TAGS_FILE = "data/protected_tags.json"

# { user_id: (join_timestamp, channel_id) }
_active_sessions: dict = {}


# ══════════════════════════════════════════════
#  STORAGE
# ══════════════════════════════════════════════

def _load(path):
    if not os.path.exists(path):
        return [] if path == PROTECTED_TAGS_FILE else {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return [] if path == PROTECTED_TAGS_FILE else {}

def _save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(tmp, path)

def load_clans():  return _load(CLANS_FILE)
def save_clans(d): _save(CLANS_FILE, d)
def load_voice():  return _load(VOICE_FILE)
def save_voice(d): _save(VOICE_FILE, d)
def load_tags():   return _load(PROTECTED_TAGS_FILE)
def save_tags(d):  _save(PROTECTED_TAGS_FILE, d)


# ══════════════════════════════════════════════
#  VOICE SESSION HELPERS
# ══════════════════════════════════════════════

def flush_session(user_id: int) -> int:
    """Save elapsed time for user's current session. Returns seconds elapsed."""
    if user_id not in _active_sessions:
        return 0
    join_ts, channel_id = _active_sessions.pop(user_id)
    elapsed = int(time.time() - join_ts)
    v = load_voice()
    ch_key = f"{user_id}:{channel_id}"
    v[ch_key] = v.get(ch_key, 0) + elapsed
    save_voice(v)
    return elapsed

def get_clan_channel_seconds(user_id: int, voice_channel_id: int) -> int:
    """Total seconds a user spent in a specific voice channel (stored + live)."""
    v = load_voice()
    ch_key = f"{user_id}:{voice_channel_id}"
    stored = v.get(ch_key, 0)
    live = 0
    if user_id in _active_sessions:
        join_ts, active_ch = _active_sessions[user_id]
        if active_ch == voice_channel_id:
            live = int(time.time() - join_ts)
    return stored + live



def seconds_to_hm(secs: int) -> str:
    h, rem = divmod(int(secs), 3600)
    m, _   = divmod(rem, 60)
    return f"{h}h {m}m"

def now_str() -> str:
    """Current UTC time as readable string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

def is_admin_or_leader(clan_name_arg: str = None):
    """
    Check: user is admin  OR  user is the leader of the target clan.
    clan_name_arg = name of the positional argument that holds the clan name.
    """
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        # Determine clan name from the command arguments
        args = ctx.message.content.split()
        # command is args[0], clan name is args[1]
        if len(args) < 2:
            return False
        clan_name = args[1]
        clans = load_clans()
        if clan_name not in clans:
            return False
        return ctx.author.id == clans[clan_name]["leader_id"]
    return commands.check(predicate)

def mk_embed(title, desc="", color=discord.Color.blurple(), fields=None, footer=""):
    e = discord.Embed(title=title, description=desc, color=color)
    for (n, v, i) in (fields or []):
        e.add_field(name=n, value=v, inline=i)
    if footer:
        e.set_footer(text=footer)
    return e

async def safe_delete_role(guild, role_id):
    r = guild.get_role(role_id)
    if r:
        try:    await r.delete(reason="Clan bot cleanup")
        except discord.HTTPException: pass

async def safe_delete_channel(guild, channel_id):
    ch = guild.get_channel(channel_id)
    if ch:
        try:    await ch.delete(reason="Clan bot cleanup")
        except discord.HTTPException: pass


# ══════════════════════════════════════════════
#  CLAN LOG HELPER
# ══════════════════════════════════════════════

async def clan_log(guild: discord.Guild, clan_name: str, embed: discord.Embed):
    """
    Send a log embed to the clan's #clan-logs channel (if it exists).
    Also tries the global #clan-logs channel as fallback.
    """
    clans = load_clans()
    log_ch = None

    # 1 — Try the clan's own log channel
    if clan_name and clan_name in clans:
        log_ch_id = clans[clan_name].get("log_channel_id")
        if log_ch_id:
            log_ch = guild.get_channel(log_ch_id)

    # 2 — Fallback: look for a server-wide #clan-logs channel
    if log_ch is None:
        log_ch = discord.utils.get(guild.text_channels, name="clan-logs")

    if log_ch:
        try:
            await log_ch.send(embed=embed)
        except discord.HTTPException:
            pass


def log_embed(action: str, actor: discord.Member, color: discord.Color, **fields) -> discord.Embed:
    """Build a compact log embed."""
    e = discord.Embed(
        title=f"📋 {action}",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    e.set_footer(text=f"By {actor.display_name} ({actor.id})")
    for k, v in fields.items():
        e.add_field(name=k, value=str(v), inline=True)
    return e


# ══════════════════════════════════════════════
#  BOT SETUP
# ══════════════════════════════════════════════

intents = discord.Intents.default()
intents.message_content = True
intents.members         = True
intents.voice_states    = True

bot = commands.Bot(command_prefix="+", intents=intents, help_command=None)


# ══════════════════════════════════════════════
#  EVENTS
# ══════════════════════════════════════════════

@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="over the clans | +help"
    ))

@bot.event
async def on_voice_state_update(member, before, after):
    uid = member.id
    joined   = before.channel is None and after.channel is not None
    left     = before.channel is not None and after.channel is None
    switched = (
        before.channel is not None
        and after.channel is not None
        and before.channel.id != after.channel.id
    )
    if joined:
        _active_sessions[uid] = (time.time(), after.channel.id)
    elif left:
        flush_session(uid)
    elif switched:
        flush_session(uid)
        _active_sessions[uid] = (time.time(), after.channel.id)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):    return
    if isinstance(error, commands.CheckFailure):
        return await ctx.send("❌ You need **Administrator** or **Clan Leader** permission for this command.")
    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.send(f"❌ Missing argument: `{error.param.name}`")
    if isinstance(error, commands.BadArgument):
        return await ctx.send(f"❌ Bad argument: {error}")
    if isinstance(error, commands.MemberNotFound):
        return await ctx.send("❌ Member not found — please @mention them.")
    if isinstance(error, commands.ChannelNotFound):
        return await ctx.send("❌ Channel not found — please #mention it.")
    log.error(f"Unhandled error in '{ctx.command}': {error}", exc_info=error)
    await ctx.send(f"⚠️ Unexpected error: `{error}`")


# ══════════════════════════════════════════════
#  HELP
# ══════════════════════════════════════════════

@bot.command(name="help")
async def help_cmd(ctx):
    e = discord.Embed(title="📖 Clan Bot Help", color=discord.Color.blurple())
    e.add_field(name="🛡️ Admin Only", inline=False, value=(
        "`+createclan <n> <@leader>` — create clan + roles + channels\n"
        "`+deleteclan <n>` — delete clan, roles, channels\n"
        "`+changeleader <clan> <@new>` — transfer leadership\n"
        "`+sayto <#ch> <msg>` — bot sends a message\n"
        "`+protecttag` / `+unprotecttag` / `+protectedtags`\n"
        "`+resetvoicetime <@user>` — reset one user's voice time\n"
        "`+resetallvoice` — reset voice time for **all** clans & members"
    ))
    e.add_field(name="👑 Leader or Admin", inline=False, value=(
        "`+addmember <clan> <@user>` — add + assign clan role\n"
        "`+deletemember <clan> <@user>` — remove + revoke clan role"
    ))
    e.add_field(name="🏹 Members", inline=False, value=(
        "`+myclan` — show your clan info"
    ))
    e.add_field(name="🎤 Voice", inline=False, value=(
        "`+myvoice` — your time in your clan VC only\n"
        "`+voiceleaderboard` (or `+vlb`) — total VC time ranked by clan\n"
        "`+topvoice <clan>` — top members by clan VC time"
    ))
    await ctx.send(embed=e)



@bot.command(name="createclan")
@is_admin()
async def create_clan(ctx, name: str, leader: discord.Member):
    """Create a clan with roles + private category + text + voice + log channels."""
    clans = load_clans()
    if name in clans:
        return await ctx.send(f"❌ Clan **{name}** already exists.")

    tags = load_tags()
    if name.lower() in [t.lower() for t in tags]:
        return await ctx.send(f"❌ The tag **{name}** is protected.")

    try:
        # Member role (gold)
        member_role = await ctx.guild.create_role(
            name=f"Clan: {name}", color=discord.Color.gold(),
            mentionable=True, reason=f"Clan creation: {name}",
        )
        # Leader role (red)
        leader_role = await ctx.guild.create_role(
            name=f"Clan Leader: {name}", color=discord.Color.red(),
            mentionable=True, reason=f"Clan creation: {name}",
        )

        # Channel overwrites — private to clan role
        private_ow = {
            ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=False),
            member_role: discord.PermissionOverwrite(
                view_channel=True, send_messages=True,
                read_message_history=True, connect=True, speak=True,
            ),
            bot.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True),
        }
        # Log channel: visible to clan + read-only (no one can write except the bot)
        log_ow = {
            ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member_role: discord.PermissionOverwrite(
                view_channel=True, send_messages=False, read_message_history=True,
            ),
            bot.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }

        # Category
        category = await ctx.guild.create_category(
            name=f"🏰 {name}", overwrites=private_ow, reason=f"Clan creation: {name}"
        )
        # Text chat
        text_ch = await ctx.guild.create_text_channel(
            name=f"{name.lower()}-chat", category=category,
            overwrites=private_ow, topic=f"Official chat for clan {name}",
            reason=f"Clan creation: {name}",
        )
        # Voice
        voice_ch = await ctx.guild.create_voice_channel(
            name=f"🔊 {name} Voice", category=category,
            overwrites=private_ow, reason=f"Clan creation: {name}",
        )
        # Clan logs (read-only for members)
        log_ch = await ctx.guild.create_text_channel(
            name=f"{name.lower()}-logs", category=category,
            overwrites=log_ow, topic=f"Clan logs for {name} — bot only",
            reason=f"Clan creation: {name}",
        )

        await leader.add_roles(member_role, leader_role, reason=f"Clan leader: {name}")

    except discord.Forbidden:
        return await ctx.send("❌ Missing permissions — make sure my role is above clan roles.")
    except discord.HTTPException as exc:
        return await ctx.send(f"❌ Discord error: {exc}")

    clans[name] = {
        "leader_id":        leader.id,
        "members":          [leader.id],
        "member_role_id":   member_role.id,
        "leader_role_id":   leader_role.id,
        "category_id":      category.id,
        "text_channel_id":  text_ch.id,
        "voice_channel_id": voice_ch.id,
        "log_channel_id":   log_ch.id,
    }
    save_clans(clans)
    log.info(f"Clan '{name}' created by {ctx.author}, leader {leader}")

    await ctx.send(embed=mk_embed(
        "✅ Clan Created", color=discord.Color.green(),
        fields=[
            ("🏰 Clan",          name,                True),
            ("👑 Leader",        leader.mention,      True),
            ("🎖️ Member Role",   member_role.mention, True),
            ("🔴 Leader Role",   leader_role.mention, True),
            ("💬 Text Channel",  text_ch.mention,     True),
            ("🔊 Voice Channel", voice_ch.name,       True),
            ("📋 Log Channel",   log_ch.mention,      True),
        ],
    ))
    await text_ch.send(embed=mk_embed(
        f"🏰 Welcome to {name}!",
        desc=(
            f"This is your clan's private channel.\n\n"
            f"👑 **Leader:** {leader.mention}\n"
            f"Use `+myclan` to view clan info.\n"
            f"📋 All clan actions are logged in {log_ch.mention}"
        ),
        color=discord.Color.gold(),
    ))

    # Log the creation
    await clan_log(ctx.guild, name, log_embed(
        "Clan Created", ctx.author, discord.Color.green(),
        Clan=name, Leader=leader.mention, Time=now_str(),
    ))


@bot.command(name="deleteclan")
@is_admin()
async def delete_clan(ctx, name: str):
    """Delete a clan and all its roles and channels."""
    clans = load_clans()
    if name not in clans:
        return await ctx.send(f"❌ No clan named **{name}**.")

    clan = clans[name]
    for ch_key in ("text_channel_id", "voice_channel_id", "log_channel_id"):
        await safe_delete_channel(ctx.guild, clan.get(ch_key))
    await safe_delete_channel(ctx.guild, clan.get("category_id"))
    await safe_delete_role(ctx.guild, clan.get("member_role_id"))
    await safe_delete_role(ctx.guild, clan.get("leader_role_id"))

    del clans[name]
    save_clans(clans)
    log.info(f"Clan '{name}' deleted by {ctx.author}")
    await ctx.send(f"✅ Clan **{name}** fully deleted (roles + channels removed).")

    # Try global log fallback since clan channel is already deleted
    global_log = discord.utils.get(ctx.guild.text_channels, name="clan-logs")
    if global_log:
        await global_log.send(embed=log_embed(
            "Clan Deleted", ctx.author, discord.Color.red(),
            Clan=name, Time=now_str(),
        ))


@bot.command(name="changeleader")
@is_admin()
async def change_leader(ctx, name: str, new_leader: discord.Member):
    """Transfer clan leadership to another member."""
    clans = load_clans()
    if name not in clans:
        return await ctx.send(f"❌ No clan named **{name}**.")

    clan        = clans[name]
    leader_role = ctx.guild.get_role(clan.get("leader_role_id"))
    member_role = ctx.guild.get_role(clan.get("member_role_id"))

    if leader_role is None:
        return await ctx.send("❌ Leader role not found — it may have been manually deleted.")

    old_leader = ctx.guild.get_member(clan["leader_id"])
    old_name   = old_leader.mention if old_leader else f"Unknown ({clan['leader_id']})"
    if old_leader:
        try:    await old_leader.remove_roles(leader_role, reason=f"Leader change: {name}")
        except discord.Forbidden: pass

    roles_to_add = [leader_role]
    if member_role and member_role not in new_leader.roles:
        roles_to_add.append(member_role)
    try:
        await new_leader.add_roles(*roles_to_add, reason=f"New leader of {name}")
    except discord.Forbidden:
        return await ctx.send("❌ I don't have permission to assign roles.")

    if new_leader.id not in clan["members"]:
        clan["members"].append(new_leader.id)
    clan["leader_id"] = new_leader.id
    clans[name] = clan
    save_clans(clans)
    log.info(f"Clan '{name}' leadership -> {new_leader} by {ctx.author}")

    await ctx.send(embed=mk_embed(
        "👑 Leader Changed", color=discord.Color.gold(),
        fields=[("Clan", name, True), ("New Leader", new_leader.mention, True)],
    ))
    await clan_log(ctx.guild, name, log_embed(
        "Leader Changed", ctx.author, discord.Color.gold(),
        Clan=name, **{"Old Leader": old_name, "New Leader": new_leader.mention, "Time": now_str()},
    ))


@bot.command(name="sayto")
@is_admin()
async def say_to(ctx, channel: discord.TextChannel, *, message: str):
    """Send a message to a channel as the bot."""
    try:
        await channel.send(message)
        await ctx.message.add_reaction("✅")
    except discord.Forbidden:
        await ctx.send(f"❌ No permission to send in {channel.mention}.")




@bot.command(name="protecttag")
@is_admin()
async def protect_tag(ctx, tag: str):
    tags = load_tags()
    if tag.lower() in [t.lower() for t in tags]:
        return await ctx.send(f"❌ **{tag}** is already protected.")
    tags.append(tag)
    save_tags(tags)
    await ctx.send(f"🔒 Tag **{tag}** is now protected.")

@bot.command(name="unprotecttag")
@is_admin()
async def unprotect_tag(ctx, tag: str):
    tags = load_tags()
    if tag.lower() not in [t.lower() for t in tags]:
        return await ctx.send(f"❌ **{tag}** is not protected.")
    save_tags([t for t in tags if t.lower() != tag.lower()])
    await ctx.send(f"🔓 Tag **{tag}** is no longer protected.")

@bot.command(name="protectedtags")
@is_admin()
async def protected_tags(ctx):
    tags = load_tags()
    if not tags:
        return await ctx.send("ℹ️ No protected tags.")
    await ctx.send(embed=mk_embed(
        "🔒 Protected Tags", "\n".join(f"• `{t}`" for t in tags),
        color=discord.Color.red(),
    ))


@bot.command(name="resetvoicetime")
@is_admin()
async def reset_voice_time(ctx, user: discord.Member):
    """Reset all voice time for a single user (admin only)."""
    v = load_voice()
    _active_sessions.pop(user.id, None)
    prefix   = str(user.id)
    keys_del = [k for k in v if k == prefix or k.startswith(f"{prefix}:")]
    if not keys_del:
        return await ctx.send(f"ℹ️ {user.mention} has no recorded voice time.")
    for k in keys_del:
        del v[k]
    save_voice(v)
    log.info(f"Voice time reset for {user} by {ctx.author}")
    await ctx.send(f"✅ Voice time for {user.mention} has been fully reset.")

    # Find user's clan for log
    clans     = load_clans()
    clan_name = next((k for k, d in clans.items() if user.id in d["members"]), None)
    await clan_log(ctx.guild, clan_name, log_embed(
        "Voice Time Reset (1 user)", ctx.author, discord.Color.orange(),
        User=user.mention, Clan=clan_name or "N/A", Time=now_str(),
    ))


@bot.command(name="resetallvoice")
@is_admin()
async def reset_all_voice(ctx):
    """Reset voice time for ALL clans and ALL members (admin only)."""
    # Flush all live sessions first
    for uid in list(_active_sessions.keys()):
        _active_sessions.pop(uid, None)

    # Wipe the entire voice file
    save_voice({})
    log.info(f"All voice time reset by {ctx.author}")

    await ctx.send(embed=mk_embed(
        "🔄 All Voice Time Reset",
        "Voice time has been wiped for **all clans and all members**.",
        color=discord.Color.red(),
        footer=f"Executed by {ctx.author.display_name}",
    ))

    # Log to every clan's log channel
    clans = load_clans()
    sent_channels = set()
    for clan_name in clans:
        log_ch_id = clans[clan_name].get("log_channel_id")
        if log_ch_id and log_ch_id not in sent_channels:
            sent_channels.add(log_ch_id)
            await clan_log(ctx.guild, clan_name, log_embed(
                "ALL Voice Time Reset", ctx.author, discord.Color.red(),
                Scope="All clans & members", Time=now_str(),
            ))
    # Also try global fallback
    if not sent_channels:
        global_log = discord.utils.get(ctx.guild.text_channels, name="clan-logs")
        if global_log:
            await global_log.send(embed=log_embed(
                "ALL Voice Time Reset", ctx.author, discord.Color.red(),
                Scope="All clans & members", Time=now_str(),
            ))



@bot.command(name="addmember")
@is_admin_or_leader()
async def add_member(ctx, name: str, user: discord.Member):
    """
    Add a member to a clan and assign the clan role.
    Usable by: Admin OR the clan's Leader.
    """
    clans = load_clans()
    if name not in clans:
        return await ctx.send(f"❌ No clan named **{name}**.")
    if user.id in clans[name]["members"]:
        return await ctx.send(f"❌ {user.mention} is already in **{name}**.")

    # Leaders can only manage their own clan
    if not ctx.author.guild_permissions.administrator:
        if ctx.author.id != clans[name]["leader_id"]:
            return await ctx.send("❌ You can only manage your own clan.")

    member_role = ctx.guild.get_role(clans[name].get("member_role_id"))
    if member_role:
        try:
            await user.add_roles(member_role, reason=f"Added to clan {name}")
        except discord.Forbidden:
            return await ctx.send("❌ I don't have permission to assign roles.")
    else:
        await ctx.send("⚠️ Clan member role not found — member added to data only.")

    clans[name]["members"].append(user.id)
    save_clans(clans)
    log.info(f"{user} added to clan '{name}' by {ctx.author}")

    await ctx.send(embed=mk_embed(
        "✅ Member Added", color=discord.Color.green(),
        fields=[
            ("Clan",   name,                                          True),
            ("Member", user.mention,                                  True),
            ("Role",   member_role.mention if member_role else "N/A", True),
        ],
    ))
    await clan_log(ctx.guild, name, log_embed(
        "Member Added", ctx.author, discord.Color.green(),
        Clan=name, Member=user.mention, Time=now_str(),
    ))


@bot.command(name="deletemember")
@is_admin_or_leader()
async def delete_member(ctx, name: str, user: discord.Member):
    """
    Remove a member from a clan and revoke their clan role.
    Usable by: Admin OR the clan's Leader.
    """
    clans = load_clans()
    if name not in clans:
        return await ctx.send(f"❌ No clan named **{name}**.")

    clan = clans[name]
    if user.id not in clan["members"]:
        return await ctx.send(f"❌ {user.mention} is not in **{name}**.")
    if user.id == clan["leader_id"]:
        return await ctx.send(f"❌ {user.mention} is the leader. Use `+changeleader` first.")

    # Leaders can only manage their own clan
    if not ctx.author.guild_permissions.administrator:
        if ctx.author.id != clan["leader_id"]:
            return await ctx.send("❌ You can only manage your own clan.")

    for role_key in ("member_role_id", "leader_role_id"):
        role = ctx.guild.get_role(clan.get(role_key))
        if role and role in user.roles:
            try:    await user.remove_roles(role, reason=f"Removed from clan {name}")
            except discord.Forbidden: pass

    clan["members"].remove(user.id)
    clans[name] = clan
    save_clans(clans)
    log.info(f"{user} removed from clan '{name}' by {ctx.author}")
    await ctx.send(f"✅ {user.mention} removed from **{name}** and clan role revoked.")
    await clan_log(ctx.guild, name, log_embed(
        "Member Removed", ctx.author, discord.Color.orange(),
        Clan=name, Member=user.mention, Time=now_str(),
    ))


@bot.command(name="myclan")
async def my_clan(ctx):
    """Show your current clan info."""
    clans = load_clans()
    found = next((k for k, v in clans.items() if ctx.author.id in v["members"]), None)
    if not found:
        return await ctx.send("❌ You are not in any clan.")

    clan        = clans[found]
    leader      = ctx.guild.get_member(clan["leader_id"])
    leader_str  = leader.mention if leader else f"Unknown ({clan['leader_id']})"
    member_role = ctx.guild.get_role(clan.get("member_role_id"))
    text_ch     = ctx.guild.get_channel(clan.get("text_channel_id"))
    voice_ch    = ctx.guild.get_channel(clan.get("voice_channel_id"))
    log_ch      = ctx.guild.get_channel(clan.get("log_channel_id"))

    members_str = "\n".join(
        (ctx.guild.get_member(mid).mention if ctx.guild.get_member(mid) else f"Unknown ({mid})")
        for mid in clan["members"]
    ) or "No members."

    await ctx.send(embed=mk_embed(
        f"🏰 Clan: {found}", color=discord.Color.blurple(),
        fields=[
            ("👑 Leader",                            leader_str,                                    False),
            ("🎖️ Role",                              member_role.mention if member_role else "N/A", True),
            ("💬 Text",                              text_ch.mention if text_ch else "N/A",         True),
            ("🔊 Voice",                             voice_ch.name if voice_ch else "N/A",          True),
            ("📋 Logs",                              log_ch.mention if log_ch else "N/A",           True),
            (f"👥 Members ({len(clan['members'])})", members_str,                                   False),
        ],
    ))



@bot.command(name="myvoice")
async def my_voice(ctx):
    """Show your voice time spent in your clan voice channel only."""
    clans = load_clans()
    clan_name = next((k for k, v in clans.items() if ctx.author.id in v["members"]), None)
    if not clan_name:
        return await ctx.send("❌ You are not in any clan.")

    voice_ch_id = clans[clan_name].get("voice_channel_id")
    if not voice_ch_id:
        return await ctx.send("❌ Your clan has no voice channel recorded.")

    total    = get_clan_channel_seconds(ctx.author.id, voice_ch_id)
    voice_ch = ctx.guild.get_channel(voice_ch_id)
    ch_name  = voice_ch.name if voice_ch else f"Channel {voice_ch_id}"

    await ctx.send(embed=mk_embed(
        "🎙️ Your Voice Time",
        (
            f"{ctx.author.mention}\n"
            f"**Clan:** {clan_name}\n"
            f"**Channel:** {ch_name}\n"
            f"**Time in clan VC:** {seconds_to_hm(total)}"
        ),
        color=discord.Color.blurple(),
        footer="Only time spent in your clan voice channel is counted.",
    ))


@bot.command(name="voiceleaderboard", aliases=["vlb"])
async def voice_leaderboard(ctx):
    """Clan voice leaderboard — total VC time per clan, ranked."""
    clans = load_clans()
    if not clans:
        return await ctx.send("📭 No clans exist yet.")

    clan_totals = []
    for clan_name, clan_data in clans.items():
        voice_ch_id = clan_data.get("voice_channel_id")
        if not voice_ch_id:
            continue
        total_secs = sum(
            get_clan_channel_seconds(uid, voice_ch_id)
            for uid in clan_data["members"]
        )
        clan_totals.append((clan_name, total_secs, len(clan_data["members"])))

    if not clan_totals:
        return await ctx.send("📭 No voice data yet.")

    clan_totals.sort(key=lambda x: x[1], reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    lines  = []
    for i, (clan_name, secs, member_count) in enumerate(clan_totals, 1):
        medal = medals[i - 1] if i <= 3 else f"`{i}.`"
        lines.append(f"{medal} **{clan_name}** — {seconds_to_hm(secs)} ({member_count} members)")

    await ctx.send(embed=mk_embed(
        "🎤 Clan Voice Leaderboard", "\n".join(lines),
        color=discord.Color.purple(),
        footer="Total time all members spent in each clan's voice channel",
    ))


@bot.command(name="topvoice")
async def top_voice(ctx, name: str):
    """Top members by time spent in the clan voice channel."""
    clans = load_clans()
    if name not in clans:
        return await ctx.send(f"❌ No clan named **{name}**.")

    voice_ch_id = clans[name].get("voice_channel_id")
    if not voice_ch_id:
        return await ctx.send(f"❌ Clan **{name}** has no voice channel recorded.")

    entries = [
        (uid, get_clan_channel_seconds(uid, voice_ch_id))
        for uid in clans[name]["members"]
    ]
    entries.sort(key=lambda x: x[1], reverse=True)

    medals = ["🥇", "🥈", "🥉"]
    lines  = []
    for i, (uid, secs) in enumerate(entries, 1):
        m       = ctx.guild.get_member(uid)
        display = m.display_name if m else f"Unknown ({uid})"
        medal   = medals[i - 1] if i <= 3 else f"`{i}.`"
        lines.append(f"{medal} **{display}** — {seconds_to_hm(secs)}")

    await ctx.send(embed=mk_embed(
        f"🎤 Top Voice — {name}", "\n".join(lines) or "No data.",
        color=discord.Color.purple(),
        footer="Time spent in the clan voice channel only",
    ))


import asyncio

async def main():
    while True:
        try:
            await bot.start(TOKEN)
        except Exception as e:
            print("Crash détecté:", e)
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
