import datetime
import logging
import re
import typing as t

import hikari
import lightbulb
import miru

import models
from etc import constants as const
from models.bot import ChenBot
from models.checks import bot_has_permissions
from models.checks import has_permissions
from models.checks import is_above_target
from models.checks import is_invoker_above_target
from models.context import ChenSlashContext
from models.context import ChenUserContext
from models.db_user import DatabaseUser
from models.events import MassBanEvent
from models.mod_actions import ModerationFlags
from models.plugin import ChenPlugin
from utils import helpers

logger = logging.getLogger(__name__)

mod = ChenPlugin("Moderation", include_datastore=True)


@mod.command
@lightbulb.option("user", "Пользователь", type=hikari.User)
@lightbulb.command("whois", "Показать информацию о пользователе", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def whois(ctx: ChenSlashContext, user: hikari.User) -> None:
    embed = await helpers.get_userinfo(ctx, user)
    await ctx.mod_respond(embed=embed)


@mod.command
@lightbulb.command("Показать профиль", "Показать пользовательскую информацию о пользователе", pass_options=True)
@lightbulb.implements(lightbulb.UserCommand)
async def whois_user_command(ctx: ChenUserContext, target: hikari.User) -> None:
    embed = await helpers.get_userinfo(ctx, target)
    await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@mod.command
@lightbulb.add_cooldown(20, 1, lightbulb.ChannelBucket)
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.MANAGE_MESSAGES, hikari.Permissions.READ_MESSAGE_HISTORY),
    has_permissions(hikari.Permissions.MANAGE_MESSAGES),
)
@lightbulb.option("user", "Удалить сообщения пользователя", type=hikari.User, required=False)
@lightbulb.option("regex", "Удалить сообщения, соответствующие регулярному выражению", required=False)
@lightbulb.option("embeds", "Удалить сообщения, содержащие embed", type=bool, required=False)
@lightbulb.option("links", "Удалить сообщения, содержащие ссылки", type=bool, required=False)
@lightbulb.option("invites", "Удалить сообщения, содержащие дискорд-приглашения", type=bool, required=False)
@lightbulb.option("attachments", "Удалить сообщения, содержащие файлы и изображения", type=bool, required=False)
@lightbulb.option("onlytext", "Удалить сообщения, в который есть только текст", type=bool, required=False)
@lightbulb.option("notext", "Удалить сообщения, в которых нет текста", type=bool, required=False)
@lightbulb.option("endswith", "Удалить сообщения, которые заканчиваются на определенный текст", required=False)
@lightbulb.option("startswith", "Удалить сообщения, которые начинаются на определенный текст", required=False)
@lightbulb.option("count", "Количество сообщения для удаления", type=int, min_value=1, max_value=100)
@lightbulb.command("purge", "Удалить сообщения в данном чате")
@lightbulb.implements(lightbulb.SlashCommand)
async def purge(ctx: ChenSlashContext) -> None:

    channel = ctx.get_channel() or await ctx.app.rest.fetch_channel(ctx.channel_id)
    assert isinstance(channel, hikari.TextableGuildChannel)

    predicates = [
        # Ignore deferred typing indicator so it doesn't get deleted lmfao
        lambda message: not (hikari.MessageFlag.LOADING & message.flags)
    ]

    if ctx.options.regex:
        try:
            regex = re.compile(ctx.options.regex)
        except re.error as error:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Некорректный regex",
                    description=f"Ошибка парсинга регулярного выражения: ```{str(error)}```",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

            assert ctx.invoked is not None and ctx.invoked.cooldown_manager is not None
            return await ctx.invoked.cooldown_manager.reset_cooldown(ctx)
        else:
            predicates.append(lambda message, regex=regex: regex.match(message.content) if message.content else False)

    if ctx.options.startswith:
        predicates.append(
            lambda message: message.content.startswith(ctx.options.startswith) if message.content else False
        )

    if ctx.options.endswith:
        predicates.append(lambda message: message.content.endswith(ctx.options.endswith) if message.content else False)

    if ctx.options.notext:
        predicates.append(lambda message: not message.content)

    if ctx.options.onlytext:
        predicates.append(lambda message: message.content and not message.attachments and not message.embeds)

    if ctx.options.attachments:
        predicates.append(lambda message: bool(message.attachments))

    if ctx.options.invites:
        predicates.append(
            lambda message: helpers.is_invite(message.content, fullmatch=False) if message.content else False
        )

    if ctx.options.links:
        predicates.append(
            lambda message: helpers.is_url(message.content, fullmatch=False) if message.content else False
        )

    if ctx.options.embeds:
        predicates.append(lambda message: bool(message.embeds))

    if ctx.options.user:
        predicates.append(lambda message: message.author.id == ctx.options.user.id)

    await ctx.mod_respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)

    messages = (
        await ctx.app.rest.fetch_messages(channel)
        .take_until(lambda m: (helpers.utcnow() - datetime.timedelta(days=14)) > m.created_at)
        .filter(*predicates)
        .limit(ctx.options.count)
    )

    if messages:
        try:
            await ctx.app.rest.delete_messages(channel, messages)
            embed = hikari.Embed(
                title="🗑️ Сообщения удалены",
                description=f"Удалено сообщений: **{len(messages)}**",
                color=const.EMBED_GREEN,
            )

        except hikari.BulkDeleteError as error:
            embed = hikari.Embed(
                title="🗑️ Messages purged",
                description=f"Only **{len(error.messages_deleted)}/{len(messages)}** messages have been deleted due to an error.",
                color=const.WARN_COLOR,
            )
            raise error
    else:
        embed = hikari.Embed(
            title="🗑️ Не найдены",
            description=f"Нет сообщений по заданым критериям за последние 2 недели",
            color=const.ERROR_COLOR,
        )

    await ctx.mod_respond(embed=embed)


@mod.command
@lightbulb.command("journal", "Доступ и управление журналом модерации")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def journal(ctx: ChenSlashContext) -> None:
    pass


@journal.child
@lightbulb.add_checks(has_permissions(hikari.Permissions.VIEW_AUDIT_LOG))
@lightbulb.option("user", "Пользователь для которого требуется получить журнал", type=hikari.User)
@lightbulb.command("get", "Получить журнал для указанного пользователя", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def journal_get(ctx: ChenSlashContext, user: hikari.User) -> None:

    assert ctx.guild_id is not None
    notes = await ctx.app.mod.get_notes(user, ctx.guild_id)

    if notes:
        navigator = models.AuthorOnlyNavigator(ctx, pages=helpers.build_note_pages(notes))  # type: ignore
        ephemeral = bool((await ctx.app.mod.get_settings(ctx.guild_id)).flags & ModerationFlags.IS_EPHEMERAL)
        await navigator.send(ctx.interaction, ephemeral=ephemeral)

    else:
        await ctx.mod_respond(
            embed=hikari.Embed(
                title="📒 Записи журнала для пользователя:",
                description=f"Для этого пользователя нет записей в журнале. Добавить вручную можно командой `/journal add {ctx.options.user}`",
                color=const.EMBED_BLUE,
            )
        )


@journal.child
@lightbulb.add_checks(has_permissions(hikari.Permissions.VIEW_AUDIT_LOG))
#@lightbulb.add_checks(lightbulb.has_roles(role1=957354746962903050))
@lightbulb.option("note", "Заметка в журнале")
@lightbulb.option("user", "Пользователь, для которого нужно добавить запись", type=hikari.User)
@lightbulb.command("add", "Добавить новую запись в журнале для указанного пользователя", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def journal_add(ctx: ChenSlashContext, user: hikari.User, note: str) -> None:

    assert ctx.guild_id is not None

    await ctx.app.mod.add_note(user, ctx.guild_id, f"💬 **От {ctx.author}:** {note}")
    await ctx.mod_respond(
        embed=hikari.Embed(
            title="✅ Добавлена запись в журнал",
            description=f"Добавлена новая запись для **{user}**. Посмотреть журнал можно командой `/journal get {ctx.options.user}`.",
            color=const.EMBED_GREEN,
        )
    )


@mod.command
@lightbulb.add_checks(is_invoker_above_target, has_permissions(hikari.Permissions.VIEW_AUDIT_LOG))
@lightbulb.option("reason", "Причина предупреждения", required=False)
@lightbulb.option("user", "Пользователь", type=hikari.Member)
@lightbulb.command(
    "warn", "Предупреждение пользователю. Заносится в журнал", pass_options=True
)
@lightbulb.implements(lightbulb.SlashCommand)
async def warn_cmd(ctx: ChenSlashContext, user: hikari.Member, reason: t.Optional[str] = None) -> None:
    helpers.is_member(user)
    assert ctx.member is not None
    embed = await ctx.app.mod.warn(user, ctx.member, reason=reason)
    await ctx.mod_respond(
        embed=embed,
        components=miru.View().add_item(
            miru.Button(
                label="Просмотреть журнал", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


@mod.command
@lightbulb.command("warns", "Управление предупреждениями")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def warns(ctx: ChenSlashContext) -> None:
    pass


@warns.child
@lightbulb.option("user", "Пользователь", type=hikari.Member)
@lightbulb.command("list", "Список предупреждений пользователя", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def warns_list(ctx: ChenSlashContext, user: hikari.Member) -> None:
    helpers.is_member(user)
    assert ctx.guild_id is not None

    db_user = await DatabaseUser.fetch(user.id, ctx.guild_id)
    warns = db_user.warns
    embed = hikari.Embed(
        title=f"{user}",
        description=f"**Предупреждений:** `{warns}`",
        color=const.WARN_COLOR,
    )
    embed.set_thumbnail(user.display_avatar_url)
    await ctx.mod_respond(embed=embed)


@warns.child
@lightbulb.add_checks(is_invoker_above_target, has_permissions(hikari.Permissions.VIEW_AUDIT_LOG))
@lightbulb.option("reason", "Причина очистки предупреждений", required=False)
@lightbulb.option("user", "Пользователь", type=hikari.Member)
@lightbulb.command("clear", "Очистить ВСЕ предупреждения пользователя", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def warns_clear(ctx: ChenSlashContext, user: hikari.Member, reason: t.Optional[str] = None) -> None:
    helpers.is_member(user)

    assert ctx.guild_id is not None and ctx.member is not None
    embed = await ctx.app.mod.clear_warns(user, ctx.member, reason=reason)
    await ctx.mod_respond(
        embed=embed,
        components=miru.View().add_item(
            miru.Button(
                label="Просмотреть журнал", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


@warns.child
@lightbulb.add_checks(is_invoker_above_target, has_permissions(hikari.Permissions.VIEW_AUDIT_LOG))
@lightbulb.option("reason", "Причина удаления предупреждения пользователя", required=False)
@lightbulb.option("user", "Пользователь", type=hikari.Member)
@lightbulb.command("remove", "Удалить одно предупреждение пользователя", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def warns_remove(ctx: ChenSlashContext, user: hikari.Member, reason: t.Optional[str] = None) -> None:
    helpers.is_member(user)

    assert ctx.guild_id is not None and ctx.member is not None

    embed = await ctx.app.mod.remove_warn(user, ctx.member, reason=reason)
    await ctx.mod_respond(
        embed=embed,
        components=miru.View().add_item(
            miru.Button(
                label="Просмотреть журнал", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


@mod.command
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.MODERATE_MEMBERS),
    has_permissions(hikari.Permissions.MODERATE_MEMBERS),
    is_above_target,
    is_invoker_above_target,
)
@lightbulb.option("reason", "Причина тайм-аута", required=False)
@lightbulb.option(
    "duration", "Продолжительность тайм-аута. Пример: '10 минут', '2022-03-01', 'завтра 20:00'"
)
@lightbulb.option("user", "Пользователь", type=hikari.Member)
@lightbulb.command("timeout", "Тайм-аут пользователя", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def timeout_cmd(
    ctx: ChenSlashContext, user: hikari.Member, duration: str, reason: t.Optional[str] = None
) -> None:
    helpers.is_member(user)
    reason = helpers.format_reason(reason, max_length=1024)
    assert ctx.member is not None

    if user.communication_disabled_until() is not None:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Уже в тайм-ауте",
                description="Пользователь уже в тайм-ауте. Используйте `/timeouts remove` чтобы освободить",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    try:
        communication_disabled_until: datetime.datetime = await ctx.app.scheduler.convert_time(
            duration, user=ctx.user, future_time=True
        )
    except ValueError:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Некорректная дата",
                description="Введите корректную дату тайм-аута",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await ctx.mod_respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)

    embed = await ctx.app.mod.timeout(user, ctx.member, communication_disabled_until, reason)

    await ctx.mod_respond(
        embed=embed,
        components=miru.View().add_item(
            miru.Button(
                label="Просмотреть журнал", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


@mod.command
@lightbulb.command("timeouts", "Управление тайм-аутами")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def timeouts(ctx: ChenSlashContext) -> None:
    pass


@timeouts.child
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.MODERATE_MEMBERS),
    has_permissions(hikari.Permissions.MODERATE_MEMBERS),
    is_above_target,
    is_invoker_above_target,
)
@lightbulb.option("reason", "Причина удаления тайм-аута", required=False)
@lightbulb.option("user", "Пользователь", type=hikari.Member)
@lightbulb.command("remove", "Удалить тайм-аут пользователя", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def timeouts_remove_cmd(ctx: ChenSlashContext, user: hikari.Member, reason: t.Optional[str] = None) -> None:
    helpers.is_member(user)
    reason = helpers.format_reason(reason, max_length=1024)

    assert ctx.member is not None

    if user.communication_disabled_until() is None:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Пользователь не в тайм-ауте",
                description="Этот пользователь и так может зайти на сервер",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await ctx.mod_respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    await ctx.app.mod.remove_timeout(user, ctx.member, reason)

    await ctx.mod_respond(
        embed=hikari.Embed(
            title="🔉 " + "Таймаут удален",
            description=f"Тайм-аут **{user}** снят.\n**Причина:** ```{reason}```",
            color=const.EMBED_GREEN,
        ),
        components=miru.View().add_item(
            miru.Button(
                label="Просмотреть журнал", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


@mod.command
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.BAN_MEMBERS),
    has_permissions(hikari.Permissions.BAN_MEMBERS),
    is_above_target,
    is_invoker_above_target,
)
@lightbulb.option(
    "days_to_delete",
    "Количество дней сообщений для удаления. По-умолчанию 0",
    choices=["0", "1", "2", "3", "4", "5", "6", "7"],
    required=False,
    default=0,
)
@lightbulb.option(
    "duration",
    "Как долго/до когда должен длиться бан. Пример: '10 минут', '2022-03-01', 'завтра 20:00'",
    required=False,
)
@lightbulb.option("reason", "Причина бана", required=False)
@lightbulb.option("user", "Пользователь", type=hikari.User)
@lightbulb.command(
    "ban", "Забанить пользователя на сервере. При желании можно выбрать на какое время", pass_options=True
)
@lightbulb.implements(lightbulb.SlashCommand)
async def ban_cmd(
    ctx: ChenSlashContext,
    user: hikari.User,
    reason: t.Optional[str] = None,
    duration: t.Optional[str] = None,
    days_to_delete: t.Optional[str] = None,
) -> None:

    assert ctx.member is not None

    if duration:
        try:
            banned_until = await ctx.app.scheduler.convert_time(duration, user=ctx.user, future_time=True)
        except ValueError:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Некорректная дата",
                    description="Введене невозможная дата",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return
    else:
        banned_until = None

    await ctx.mod_respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)

    embed = await ctx.app.mod.ban(
        user,
        ctx.member,
        duration=banned_until,
        days_to_delete=int(days_to_delete) if days_to_delete else 0,
        reason=reason,
    )
    await ctx.mod_respond(
        embed=embed,
        components=(
            miru.View()
            .add_item(
                miru.Button(
                    label="Разблокировать", custom_id=f"Разблокировать:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SUCCESS
                )
            )
            .add_item(
                miru.Button(
                    label="Просмотреть журнал",
                    custom_id=f"JOURNAL:{user.id}:{ctx.member.id}",
                    style=hikari.ButtonStyle.SECONDARY,
                )
            )
        ),
    )


@mod.command
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.BAN_MEMBERS),
    has_permissions(hikari.Permissions.KICK_MEMBERS),
    is_above_target,
    is_invoker_above_target,
)
@lightbulb.option(
    "days_to_delete",
    "Количество дней сообщений для удаления. По-умолчанию 0",
    choices=["0", "1", "2", "3", "4", "5", "6", "7"],
    required=False,
    default=0,
)
@lightbulb.option("reason", "Причина софтбана", required=False)
@lightbulb.option("user", "Пользователь", type=hikari.Member)
@lightbulb.command(
    "softban",
    "Софтбан пользователя с удалением его сообщений и разбаном",
    pass_options=True,
)
@lightbulb.implements(lightbulb.SlashCommand)
async def softban_cmd(
    ctx: ChenSlashContext, user: hikari.Member, reason: t.Optional[str] = None, days_to_delete: t.Optional[str] = None
) -> None:
    helpers.is_member(user)
    assert ctx.member is not None

    await ctx.respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    embed = await ctx.app.mod.ban(
        user,
        ctx.member,
        soft=True,
        days_to_delete=int(days_to_delete) if days_to_delete else 0,
        reason=reason,
    )
    await ctx.mod_respond(embed=embed)


@mod.command
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.BAN_MEMBERS),
    has_permissions(hikari.Permissions.BAN_MEMBERS),
    is_above_target,
    is_invoker_above_target,
)
@lightbulb.option("reason", "Причина", required=False)
@lightbulb.option("user", "Пользователь", type=hikari.User)
@lightbulb.command("unban", "Разбан забаненного пользователя", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def unban_cmd(ctx: ChenSlashContext, user: hikari.User, reason: t.Optional[str] = None) -> None:

    assert ctx.member is not None

    await ctx.mod_respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    embed = await ctx.app.mod.unban(user, ctx.member, reason=reason)
    await ctx.mod_respond(
        embed=embed,
        components=miru.View().add_item(
            miru.Button(
                label="Просмотреть журнал", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


@mod.command
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.KICK_MEMBERS),
    has_permissions(hikari.Permissions.KICK_MEMBERS),
    is_above_target,
    is_invoker_above_target,
)
@lightbulb.option("reason", "Причина", required=False)
@lightbulb.option("user", "Пользователь", type=hikari.Member)
@lightbulb.command("kick", "Кик пользователя с сервера", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def kick_cmd(ctx: ChenSlashContext, user: hikari.Member, reason: t.Optional[str] = None) -> None:

    helpers.is_member(user)
    assert ctx.member is not None

    await ctx.mod_respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    embed = await ctx.app.mod.kick(user, ctx.member, reason=reason)
    await ctx.mod_respond(
        embed=embed,
        components=miru.View().add_item(
            miru.Button(
                label="Просмотреть журнал", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


@mod.command
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.MANAGE_CHANNELS, hikari.Permissions.MANAGE_MESSAGES),
    has_permissions(hikari.Permissions.MANAGE_CHANNELS),
)
@lightbulb.option(
    "interval", "Интервал медленного режима в секундах, 0 чтобы отключить", type=int, min_value=0, max_value=21600
)
@lightbulb.command("slowmode", "Установить слоу-мод режим в этом канале.", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def slowmode_mcd(ctx: ChenSlashContext, interval: int) -> None:
    await ctx.app.rest.edit_channel(ctx.channel_id, rate_limit_per_user=interval)
    await ctx.mod_respond(
        embed=hikari.Embed(
            title="✅ Слоумод обновлен",
            description=f"{const.EMOJI_SLOWMODE} Слоумод настроен на одно сообщение в `{interval}` секунд",
            color=const.EMBED_GREEN,
        )
    )


@mod.command
@lightbulb.set_max_concurrency(1, lightbulb.GuildBucket)
@lightbulb.add_cooldown(60.0, 1, bucket=lightbulb.GuildBucket)
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.BAN_MEMBERS),
    has_permissions(hikari.Permissions.BAN_MEMBERS),
)
@lightbulb.option(
    "show",
    "Фиктивный запуск. Показать пользователей, которые будут забанены",
    type=bool,
    default=False,
    required=False,
)
@lightbulb.option("reason", "Причина блокировки пользователей", required=False)
@lightbulb.option("regex", "Регулярное выражение для сопоставления имен", required=False)
@lightbulb.option(
    "no-avatar", "Только пользователей без аватара", type=bool, default=False, required=False
)
@lightbulb.option(
    "no-roles", "Только пользователей без роли", type=bool, default=False, required=False
)
@lightbulb.option(
    "created", "Только пользователей, который зарегистрировались Х минут назад", type=int, min_value=1, required=False
)
@lightbulb.option(
    "joined", "Только пользователей которые присоединились к серверу X минут назад", type=int, min_value=1, required=False
)
@lightbulb.option("joined-before", "Только пользователи, которые присоединились до данного пользователя", type=hikari.Member, required=False)
@lightbulb.option("joined-after", "Только пользователи, которые присоединились после данного пользователя", type=hikari.Member, required=False)
@lightbulb.command("massban", "Заблокировать сразу большое количество пользователей по параметрам")
@lightbulb.implements(lightbulb.SlashCommand)
async def massban(ctx: ChenSlashContext) -> None:

    if ctx.options["joined-before"]:
        helpers.is_member(ctx.options["joined-before"])
    if ctx.options["joined-after"]:
        helpers.is_member(ctx.options["joined-after"])

    predicates = [
        lambda member: not member.is_bot,
        lambda member: member.id != ctx.author.id,
        lambda member: member.discriminator != "0000",  # Deleted users
    ]

    guild = ctx.get_guild()
    assert guild is not None

    me = guild.get_member(ctx.app.user_id)
    assert me is not None

    def is_above_member(member: hikari.Member, me: hikari.Member = me) -> bool:
        # Check if the bot's role is above the member's or not to reduce invalid requests.
        return helpers.is_above(me, member)

    predicates.append(is_above_member)

    if ctx.options.regex:
        try:
            regex = re.compile(ctx.options.regex)
        except re.error as error:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Некорректное регулярное выражение",
                    description=f"Error: ```{str(error)}```",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            assert ctx.invoked is not None and ctx.invoked.cooldown_manager is not None
            await ctx.invoked.cooldown_manager.reset_cooldown(ctx)
            return
        else:
            predicates.append(lambda member, regex=regex: regex.match(member.username))

    await ctx.mod_respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)

    # Ensure the specified guild is explicitly chunked
    await ctx.app.request_guild_members(guild, include_presences=False)

    members = list(guild.get_members().values())

    if ctx.options["no-avatar"]:
        predicates.append(lambda member: member.avatar_url is None)
    if ctx.options["no-roles"]:
        predicates.append(lambda member: len(member.role_ids) <= 1)

    now = helpers.utcnow()

    if ctx.options.created:

        def created(member: hikari.User, offset=now - datetime.timedelta(minutes=ctx.options.created)) -> bool:
            return member.created_at > offset

        predicates.append(created)

    if ctx.options.joined:

        def joined(member: hikari.User, offset=now - datetime.timedelta(minutes=ctx.options.joined)) -> bool:
            if not isinstance(member, hikari.Member):
                return True
            else:
                return member.joined_at and member.joined_at > offset

        predicates.append(joined)

    if ctx.options["joined-after"]:

        def joined_after(member: hikari.Member, joined_after=ctx.options["joined-after"]) -> bool:
            return member.joined_at and joined_after.joined_at and member.joined_at > joined_after.joined_at

        predicates.append(joined_after)

    if ctx.options["joined-before"]:

        def joined_before(member: hikari.Member, joined_before=ctx.options["joined-before"]) -> bool:
            return member.joined_at and joined_before.joined_at and member.joined_at < joined_before.joined_at

        predicates.append(joined_before)

    to_ban = [member for member in members if all(predicate(member) for predicate in predicates)]

    if len(to_ban) == 0:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Пользователи не найдены",
                description=f"Нет пользователей по заданым критериям",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    content = [f"Массбан: {guild.name}   |  Сопоставленные пользователи: {len(to_ban)}\n{now}\n"]

    for member in to_ban:
        content.append(f"{member} ({member.id})  |  Присоединился: {member.joined_at}  |  Зарегистрирован: {member.created_at}")

    content = "\n".join(content)
    file = hikari.Bytes(content.encode("utf-8"), "members_to_ban.txt")

    if ctx.options.show == True:
        await ctx.mod_respond(attachment=file)
        return

    reason = ctx.options.reason if ctx.options.reason is not None else "Причина не указана."
    helpers.format_reason(reason, ctx.member, max_length=512)

    embed = hikari.Embed(
        title="⚠️ Подвердите масс бан",
        description=f"Вы собираетесь забанить **{len(to_ban)}** пользователей. Вы уверены, что хотите это сделать?",
        color=const.WARN_COLOR,
    )
    confirm_embed = hikari.Embed(
        title="Массбан запущен...",
        description="Это может занять некоторое время...",
        color=const.WARN_COLOR,
    )
    cancel_embed = hikari.Embed(
        title="Массбан прерван",
        description="Ни один пользователь не был забанен",
        color=const.ERROR_COLOR,
    )

    is_ephemeral = bool((await ctx.app.mod.get_settings(guild.id)).flags & ModerationFlags.IS_EPHEMERAL)
    flags = hikari.MessageFlag.EPHEMERAL if is_ephemeral else hikari.MessageFlag.NONE
    confirmed = await ctx.confirm(
        embed=embed,
        flags=flags,
        cancel_payload={"embed": cancel_embed, "flags": flags, "components": []},
        confirm_payload={"embed": confirm_embed, "flags": flags, "components": []},
        attachment=file,
    )

    if not confirmed:
        return

    userlog = ctx.app.get_plugin("Logging")
    if userlog:
        await userlog.d.actions.freeze_logging(guild.id)

    count = 0

    for member in to_ban:
        try:
            await guild.ban(member, reason=reason)
        except (hikari.HTTPError, hikari.ForbiddenError):
            pass
        else:
            count += 1

    file = hikari.Bytes(content.encode("utf-8"), "members_banned.txt")

    assert ctx.guild_id is not None and ctx.member is not None
    await ctx.app.dispatch(MassBanEvent(ctx.app, ctx.guild_id, ctx.member, len(to_ban), count, file, reason))

    await ctx.mod_respond(
        embed=hikari.Embed(
            title="✅ Массбан завершен",
            description=f"Забанено пользователей: **{count}/{len(to_ban)}**",
            color=const.EMBED_GREEN,
        )
    )

    if userlog:
        await userlog.d.actions.unfreeze_logging(ctx.guild_id)


def load(bot: ChenBot) -> None:
    bot.add_plugin(mod)


def unload(bot: ChenBot) -> None:
    bot.remove_plugin(mod)


# Copyright (C) 2022-present HyperGH

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see: https://www.gnu.org/licenses
