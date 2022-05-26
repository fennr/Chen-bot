import logging
import typing as t

import hikari
import lightbulb
import miru

from etc import constants as const
from models import ChenSlashContext
from models.bot import ChenBot
from models.context import SnedContext
from models.context import ChenMessageContext
from models.context import ChenUserContext
from models.plugin import ChenPlugin
from utils import helpers

logger = logging.getLogger(__name__)

reports = ChenPlugin("Reports")


class ReportModal(miru.Modal):
    def __init__(self, member: hikari.Member) -> None:
        super().__init__(f"Репорт на {member}", autodefer=False)
        self.add_item(
            miru.TextInput(
                label="Причина репорта",
                placeholder="Пожалуйста, укажите причину...",
                style=hikari.TextInputStyle.PARAGRAPH,
                max_length=1000,
                required=True,
            )
        )
        self.add_item(
            miru.TextInput(
                label="Дополнительный контекст",
                placeholder="Более детальное описание поможет рассмотреть вопрос быстрее...",
                style=hikari.TextInputStyle.PARAGRAPH,
                max_length=1000,
            )
        )
        self.reason: t.Optional[str] = None
        self.info: t.Optional[str] = None

    async def callback(self, ctx: miru.ModalContext) -> None:
        if not ctx.values:
            return

        for item, value in ctx.values.items():
            assert isinstance(item, miru.TextInput)

            if item.label == "Причина репорта":
                self.reason = value
            elif item.label == "Дополнительный контекст":
                self.info = value

        await ctx.defer(flags=hikari.MessageFlag.EPHEMERAL)


async def report_error(ctx: SnedContext) -> None:
    guild = ctx.get_guild()
    assert guild is not None

    await ctx.respond(
        embed=hikari.Embed(
            title="❌ Ошибка",
            description=f"Похоже администрация **{guild.name}** не включила в настройках данную команду",
            color=const.ERROR_COLOR,
        ),
        flags=hikari.MessageFlag.EPHEMERAL,
    )


async def report_perms_error(ctx: SnedContext) -> None:
    await ctx.respond(
        embed=hikari.Embed(
            title="❌ Ошибка",
            description=f"Похоже недостаточно прав для создания сообщения. Сообщите об этой ошибке администратору сообщества",
            color=const.ERROR_COLOR,
        ),
        flags=hikari.MessageFlag.EPHEMERAL,
    )


async def report(ctx: SnedContext, member: hikari.Member, message: t.Optional[hikari.Message] = None) -> None:

    assert ctx.member is not None and ctx.guild_id is not None

    if member.id == ctx.member.id or member.is_bot:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ ???",
                description=f"Нельзя выбрать себя или бота",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    records = await ctx.app.db_cache.get(table="reports", guild_id=ctx.guild_id)

    if not records or not records[0]["is_enabled"]:
        return await report_error(ctx)

    channel = ctx.app.cache.get_guild_channel(records[0]["channel_id"])
    assert isinstance(channel, hikari.TextableGuildChannel)

    if not channel:
        await ctx.app.db.execute(
            """INSERT INTO reports (is_enabled, guild_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO
            UPDATE SET is_enabled = $1""",
            False,
            ctx.guild_id,
        )
        await ctx.app.db_cache.refresh(table="reports", guild_id=ctx.guild_id)
        return await report_error(ctx)

    me = ctx.app.cache.get_member(ctx.guild_id, ctx.app.user_id)
    assert me is not None

    perms = lightbulb.utils.permissions_in(channel, me)

    if not (perms & hikari.Permissions.SEND_MESSAGES):
        return await report_perms_error(ctx)

    assert ctx.interaction is not None

    modal = ReportModal(member)
    await modal.send(ctx.interaction)
    await modal.wait()

    if not modal.reason:  # Modal was closed/timed out
        return

    role_ids = records[0]["pinged_role_ids"] or []
    roles = filter(lambda r: r is not None, [ctx.app.cache.get_role(role_id) for role_id in role_ids])
    role_mentions = [role.mention for role in roles if role is not None]

    embed = hikari.Embed(
        title="⚠️ Новое сообщение",
        description=f"""
**От:** {ctx.member.mention} `({ctx.member.id})`
**Репорт на:**  {member.mention} `({member.id})`
**Причина:** ```{modal.reason}```
**Дополнительный контекст:** ```{modal.info or "Отсутствует"}```""",
        color=const.WARN_COLOR,
    )

    components = hikari.UNDEFINED

    if message:
        components = (
            miru.View().add_item(miru.Button(label="Associated Message", url=message.make_link(ctx.guild_id))).build()
        )

    await channel.send(
        " ".join(role_mentions) or hikari.UNDEFINED, embed=embed, components=components, role_mentions=True
    )
    await modal.get_response_context().respond(
        embed=hikari.Embed(
            title="✅ Сообщение отправлено",
            description="Модерация рассмотрит сообщение в ближайшее время",
            color=const.EMBED_GREEN,
        ),
        flags=hikari.MessageFlag.EPHEMERAL,
    )


@reports.command
@lightbulb.option("user", "Пользователь нарушивший правила", type=hikari.Member, required=True)
@lightbulb.command("report", "Сообщить о нарушении", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def report_cmd(ctx: ChenSlashContext, user: hikari.Member) -> None:
    helpers.is_member(user)
    await report(ctx, user)


@reports.command
@lightbulb.command("Report User", "Сообщить о пользователе модераторам", pass_options=True)
@lightbulb.implements(lightbulb.UserCommand)
async def report_user_cmd(ctx: ChenUserContext, target: hikari.Member) -> None:
    helpers.is_member(target)
    await report(ctx, ctx.options.target)


@reports.command
@lightbulb.command(
    "Report Message", "Сообщить о сообщении модераторам", pass_options=True
)
@lightbulb.implements(lightbulb.MessageCommand)
async def report_msg_cmd(ctx: ChenMessageContext, target: hikari.Message) -> None:
    assert ctx.guild_id is not None
    member = ctx.app.cache.get_member(ctx.guild_id, target.author)
    if not member:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Ошибка",
                description="Похоже автор сообщения уже покинул сервер",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await report(ctx, member, ctx.options.target)


def load(bot: ChenBot) -> None:
    bot.add_plugin(reports)


def unload(bot: ChenBot) -> None:
    bot.remove_plugin(reports)


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
