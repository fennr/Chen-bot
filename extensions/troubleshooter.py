import asyncio
import logging

import hikari
import lightbulb

from etc import constants as const
from etc import get_perm_str
from models import ChenSlashContext
from models.bot import ChenBot
from models.plugin import ChenPlugin

logger = logging.getLogger(__name__)

troubleshooter = ChenPlugin("Troubleshooter")

# Find perms issues
# Find automod config issues
# Find missing channel perms issues
# ...

REQUIRED_PERMISSIONS = (
    hikari.Permissions.VIEW_AUDIT_LOG
    | hikari.Permissions.MANAGE_ROLES
    | hikari.Permissions.KICK_MEMBERS
    | hikari.Permissions.BAN_MEMBERS
    | hikari.Permissions.MANAGE_CHANNELS
    | hikari.Permissions.MANAGE_THREADS
    | hikari.Permissions.MANAGE_NICKNAMES
    | hikari.Permissions.CHANGE_NICKNAME
    | hikari.Permissions.READ_MESSAGE_HISTORY
    | hikari.Permissions.VIEW_CHANNEL
    | hikari.Permissions.SEND_MESSAGES
    | hikari.Permissions.CREATE_PUBLIC_THREADS
    | hikari.Permissions.CREATE_PRIVATE_THREADS
    | hikari.Permissions.SEND_MESSAGES_IN_THREADS
    | hikari.Permissions.EMBED_LINKS
    | hikari.Permissions.ATTACH_FILES
    | hikari.Permissions.MENTION_ROLES
    | hikari.Permissions.USE_EXTERNAL_EMOJIS
    | hikari.Permissions.MODERATE_MEMBERS
    | hikari.Permissions.MANAGE_MESSAGES
    | hikari.Permissions.ADD_REACTIONS
)

# Explain why the bot requires the perm
PERM_DESCRIPTIONS = {
    hikari.Permissions.VIEW_AUDIT_LOG: "Требуется заполнить в журнал детали, такие как кто модератор, о ком речь, какая причина",
    hikari.Permissions.MANAGE_ROLES: "Треубется чтобы выдавать пользователям роли с помощью кнопок",
    hikari.Permissions.MANAGE_CHANNELS: "Используется для `/slowmode` чтобы установить слоу-мод на канале",
    hikari.Permissions.MANAGE_THREADS: "Используется для `/slowmode` чтобы установить слоу-мод в ветке",
    hikari.Permissions.MANAGE_NICKNAMES: "Используется для изменения ника в `/setnick`",
    hikari.Permissions.KICK_MEMBERS: "Требуется для использования команды `/kick`",
    hikari.Permissions.BAN_MEMBERS: "Требуется для использования команд `/ban`, `/softban`, `/massban`",
    hikari.Permissions.CHANGE_NICKNAME: "Используется для изменения ника в `/setnick`",
    hikari.Permissions.READ_MESSAGE_HISTORY: "Требуется для множества команд, требующих чтения сообщений",
    hikari.Permissions.VIEW_CHANNEL: "Требуется для множества команд, требующих чтения сообщений",
    hikari.Permissions.SEND_MESSAGES: "Требуется для отправки сообщений с помощью `/echo`, `/edit`, логирования, репортов и других команд",
    hikari.Permissions.CREATE_PUBLIC_THREADS: "Требуется для доступа к веткам",
    hikari.Permissions.CREATE_PRIVATE_THREADS: "Требуется для доступа к веткам",
    hikari.Permissions.SEND_MESSAGES_IN_THREADS: "Требуется для доступа к веткам",
    hikari.Permissions.EMBED_LINKS: "Требуется для создания ботом embed сообщений. Без этого разрешения бот не сможет отправить ни одно сообщение",
    hikari.Permissions.ATTACH_FILES: "Требуется для отправки файлов. Используется в команде `/massban`.",
    hikari.Permissions.MENTION_ROLES: "Требуется, чтобы бот мог упоминать роли. Ни одна команда **не использует** упоминания @everyone или @here",
    hikari.Permissions.USE_EXTERNAL_EMOJIS: "Требуется для отображения смайликов в сообщениях",
    hikari.Permissions.ADD_REACTIONS: "Требуется для создания начальных реакций на сообщение",
    hikari.Permissions.MODERATE_MEMBERS: "Требуется для использования команды `/timeout`",
    hikari.Permissions.MANAGE_MESSAGES: "Требуется для возможности удалять сообщения других пользователей",
}


@troubleshooter.command
@lightbulb.command("troubleshoot", "Диагностика возможных проблем")
@lightbulb.implements(lightbulb.SlashCommand)
async def troubleshoot(ctx: ChenSlashContext) -> None:

    assert ctx.guild_id is not None

    me = ctx.app.cache.get_member(ctx.guild_id, ctx.app.user_id)
    assert me is not None

    perms = lightbulb.utils.permissions_for(me)
    missing_perms = ~perms & REQUIRED_PERMISSIONS
    content = []

    if missing_perms is not hikari.Permissions.NONE:
        content.append("**Отсутствуют права:**")
        content += [
            f"❌ **{get_perm_str(perm)}**: {desc}" for perm, desc in PERM_DESCRIPTIONS.items() if missing_perms & perm
        ]

    if not content:
        embed = hikari.Embed(
            title="✅ Проблем с правами не найдено",
            description="Если вы все же столкнулись с проблемой, напишите мне на [сервер Samuro_dev](https://discord.gg/qxy6WE9cke)",
            color=const.EMBED_GREEN,
        )
    else:
        content = "\n".join(content)
        embed = hikari.Embed(
            title="О, нет!",
            description=f"Похоже, что боту не хватает прав для выполнения некоторых действий\n\n{content}\n\nЕсли вы не можете самостоятельно решить проблему, напишите мне на [сервер Samuro_dev](https://discord.gg/qxy6WE9cke)",
            color=const.ERROR_COLOR,
        )

    await ctx.mod_respond(embed=embed)


def load(bot: ChenBot) -> None:
    bot.add_plugin(troubleshooter)


def unload(bot: ChenBot) -> None:
    bot.remove_plugin(troubleshooter)


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
