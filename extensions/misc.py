import logging
import re
import typing as t
from difflib import get_close_matches

import hikari
import lightbulb
import miru
import psutil
import pytz

import asyncio

import utils.helpers
from etc import constants as const
from models import ChenBot
from models.checks import bot_has_permissions
from models.checks import has_permissions
from models.context import ChenMessageContext
from models.context import ChenSlashContext
from models.plugin import ChenPlugin
from utils import helpers
from utils.scheduler import ConversionMode

logger = logging.getLogger(__name__)

misc = ChenPlugin("Miscellaneous Commands")
psutil.cpu_percent(interval=1)  # Call so subsequent calls for CPU % will not be blocking

RGB_REGEX = re.compile(r"[0-9]{1,3} [0-9]{1,3} [0-9]{1,3}")


@misc.command
@lightbulb.command("ping", "Проверить жив ли бот")
@lightbulb.implements(lightbulb.SlashCommand)
async def ping(ctx: ChenSlashContext) -> None:
    await ctx.respond(
        embed=hikari.Embed(
            title="🏓 Pong!",
            description=f"Latency: `{round(ctx.app.heartbeat_latency * 1000)}ms`",
            color=const.MISC_COLOR,
        )
    )


@misc.command
@lightbulb.option("detach", "Отправить как отдельное сообщение", type=bool, required=False)
@lightbulb.option(
    "color",
    "Цвет. Ожидается 3 RGB значения через пробел",
    type=hikari.Color,
    required=False,
)
@lightbulb.option("author_url", "URL на который идет переход по клику по автору", required=False)
@lightbulb.option(
    "author_image_url",
    "URL на аватар автора",
    required=False,
)
@lightbulb.option("author", "Автор вставки. Появляется под заголовком", required=False)
@lightbulb.option(
    "footer_image_url",
    "Изображение в 'подвале' эмбеда",
    required=False,
)
@lightbulb.option(
    "image_url",
    "Изображение сбоку эмбеда",
    required=False,
)
@lightbulb.option(
    "thumbnail_url",
    "Изображение в виде миниатюры",
    required=False,
)
@lightbulb.option("footer", "Подвал эмбеда", required=False)
@lightbulb.option("description", "Описание эмбеда", required=False)
@lightbulb.option("title", "Заголовок эмбеда. Обязателен!", required=False)
@lightbulb.command("embed", "Сгенерировать новое embed-сообщение с параметрами")
@lightbulb.implements(lightbulb.SlashCommand)
async def embed(ctx: ChenSlashContext) -> None:
    url_options = [
        ctx.options.image_url,
        ctx.options.thumbnail_url,
        ctx.options.footer_image_url,
        ctx.options.author_image_url,
        ctx.options.author_url,
    ]
    for option in url_options:
        if option and not helpers.is_url(option):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Некорректный URL",
                    description=f"Указан неверный URL.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

    if ctx.options.color is not None and not RGB_REGEX.fullmatch(ctx.options.color):
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Некорректный цвет",
                description=f"Цвет должен быть в формате `RRR GGG BBB`, три значения разделенные пробелами",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    embed = (
        hikari.Embed(
            title=ctx.options.title,
            description=ctx.options.description,
            color=ctx.options.color,
        )
        .set_footer(ctx.options.footer, icon=ctx.options.footer_image_url)
        .set_image(ctx.options.image_url)
        .set_thumbnail(ctx.options.thumbnail_url)
        .set_author(
            name=ctx.options.author,
            url=ctx.options.author_url,
            icon=ctx.options.author_image_url,
        )
    )

    if not ctx.options.detach:
        await ctx.respond(embed=embed)
        return

    if ctx.member and not helpers.includes_permissions(
        lightbulb.utils.permissions_for(ctx.member), hikari.Permissions.MANAGE_MESSAGES
    ):
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Отсутствуют права доступа",
                description=f"Необходимо иметь роль с правами на `Manage Messages`",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    if ctx.guild_id:
        me = ctx.app.cache.get_member(ctx.guild_id, ctx.app.user_id)
        channel = ctx.get_channel()

        if not isinstance(channel, (hikari.GuildTextChannel, hikari.GuildNewsChannel)):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Невозможно отправить в треде",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        assert me is not None

        if not helpers.includes_permissions(
            lightbulb.utils.permissions_in(channel, me),
            hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL,
        ):
            raise lightbulb.BotMissingRequiredPermission(
                perms=hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES
            )

    await ctx.app.rest.create_message(ctx.channel_id, embed=embed)
    await ctx.respond(
        embed=hikari.Embed(title="✅ Embed создан!", color=const.EMBED_GREEN), flags=hikari.MessageFlag.EPHEMERAL
    )


@embed.set_error_handler
async def embed_error(event: lightbulb.CommandErrorEvent) -> None:
    if isinstance(event.exception, lightbulb.CommandInvocationError) and isinstance(
        event.exception.original, ValueError
    ):
        await event.context.respond(
            embed=hikari.Embed(
                title="❌ Parsing error",
                description=f"Ошибка парсинга параметров команды.\n**Error:** ```{event.exception.original}```",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return
    raise


@misc.command
@lightbulb.command("about", "Вывести информацию о боте.")
@lightbulb.implements(lightbulb.SlashCommand)
async def about(ctx: ChenSlashContext) -> None:
    me = ctx.app.get_me()
    assert me is not None
    process = psutil.Process()

    await ctx.respond(
        embed=hikari.Embed(
            title=f"ℹ️ About {me.username}",
            description=f"""**• Made by:** `fenrir#5455`
**• Servers:** `{len(ctx.app.cache.get_guilds_view())}`
**• Invite:** [Invite me!](https://discord.com/oauth2/authorize?client_id={me.id}&permissions=1494984682710&scope=bot%20applications.commands)
**• Support:** [Click here!](https://discord.gg/qxy6WE9cke)""",
            color=const.EMBED_BLUE,
        )
        .set_thumbnail(me.avatar_url)
        .add_field(
            name="CPU utilization",
            value=f"`{round(psutil.cpu_percent(interval=None))}%`",
            inline=True,
        )
        .add_field(
            name="Memory utilization",
            value=f"`{round(process.memory_info().vms / 1048576)}MB`",
            inline=True,
        )
        .add_field(
            name="Latency",
            value=f"`{round(ctx.app.heartbeat_latency * 1000)}ms`",
            inline=True,
        )
    )


@misc.command
@lightbulb.command("invite", "Пригласить бота на свой сервер!")
@lightbulb.implements(lightbulb.SlashCommand)
async def invite(ctx: ChenSlashContext) -> None:

    if not ctx.app.dev_mode:
        invite_url = f"https://discord.com/oauth2/authorize?client_id={ctx.app.user_id}&permissions=1494984682710&scope=applications.commands%20bot"
        await ctx.respond(
            embed=hikari.Embed(
                title="🌟 Yay!",
                description=f"[Клинки]({invite_url}) чтобы пригласить бота на сервер!",
                color=const.MISC_COLOR,
            )
        )
    else:
        await ctx.respond(
            embed=hikari.Embed(
                title="🌟 Oops!",
                description=f"Похоже бот не предназначен для приглашения!",
                color=const.MISC_COLOR,
            )
        )


@misc.command
@lightbulb.add_cooldown(10.0, 1, lightbulb.GuildBucket)
@lightbulb.add_checks(
    has_permissions(hikari.Permissions.MANAGE_NICKNAMES),
    bot_has_permissions(hikari.Permissions.CHANGE_NICKNAME),
)
@lightbulb.option("nickname", "Сменить никнейм бота. None для сброса к стандартному значению")
@lightbulb.command("setnick", "Установить никнейм бота!", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def setnick(ctx: ChenSlashContext, nickname: t.Optional[str] = None) -> None:
    assert ctx.guild_id is not None

    nickname = nickname[:32] if nickname and not nickname.casefold() == "none" else None

    await ctx.app.rest.edit_my_member(
        ctx.guild_id, nickname=nickname, reason=f"Никнейм изменен через /setnick от {ctx.author}"
    )
    await ctx.respond(
        embed=hikari.Embed(title="✅ Никнейм изменен!", color=const.EMBED_GREEN), flags=hikari.MessageFlag.EPHEMERAL
    )


@misc.command
@lightbulb.command("support", "Задать вопросы относительно бота")
@lightbulb.implements(lightbulb.SlashCommand)
async def support(ctx: ChenSlashContext) -> None:
    await ctx.respond("https://discord.gg/qxy6WE9cke", flags=hikari.MessageFlag.EPHEMERAL)


@misc.command
@lightbulb.command("serverinfo", "Вывести информацию о текущем сервере")
@lightbulb.implements(lightbulb.SlashCommand)
async def serverinfo(ctx: ChenSlashContext) -> None:
    assert ctx.guild_id is not None
    guild = ctx.app.cache.get_available_guild(ctx.guild_id)
    assert guild is not None

    embed = (
        hikari.Embed(
            title=f"ℹ️ Server Information",
            description=f"""**• Name:** `{guild.name}`
**• ID:** `{guild.id}`
**• Создатель:** `{ctx.app.cache.get_member(guild.id, guild.owner_id)}` (`{guild.owner_id}`)
**• Создан:** {helpers.format_dt(guild.created_at)} ({helpers.format_dt(guild.created_at, style="R")})
**• Пользователей:** `{guild.member_count}`
**• Ролей:** `{len(guild.get_roles())}`
**• Каналов:** `{len(guild.get_channels())}`
**• Уровень Nitro:** `{guild.premium_tier}`
**• Nitro Boost подписчики:** `{guild.premium_subscription_count or '*Not found*'}`
**• Язык:** `{guild.preferred_locale}`
**• Сообщество:** `{"Yes" if "COMMUNITY" in guild.features else "No"}`
**• Discord партнер:** `{"Yes" if "PARTNERED" in guild.features else "No"}`
**• Верификация:** `{"Yes" if "VERIFIED" in guild.features else "No"}`
**• Публичный:** `{"Yes" if "DISCOVERABLE" in guild.features else "No"}`
**• Монетизируемый:** `{"Yes" if "MONETIZATION_ENABLED" in guild.features else "No"}`
{f"**• URL:** {guild.vanity_url_code}" if guild.vanity_url_code else ""}
""",
            color=const.EMBED_BLUE,
        )
        .set_thumbnail(guild.icon_url)
        .set_image(guild.banner_url)
    )

    await ctx.respond(embed=embed)


@misc.command
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.SEND_MESSAGES, hikari.Permissions.VIEW_CHANNEL),
    has_permissions(hikari.Permissions.MANAGE_MESSAGES),
)
@lightbulb.option(
    "channel",
    "Канал для отправки сообщения. По-умолчанию текущий канал",
    required=False,
    type=hikari.TextableGuildChannel,
    channel_types=[hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS],
)
@lightbulb.option("text", "Текст")
@lightbulb.command("echo", "Повторить текст от имени бота.", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def echo(ctx: ChenSlashContext, text: str, channel: t.Optional[hikari.InteractionChannel] = None) -> None:
    # InteractionChannel has no overrides data
    send_to = (ctx.app.cache.get_guild_channel(channel.id) or ctx.get_channel()) if channel else ctx.get_channel()

    assert ctx.guild_id is not None

    if not send_to:
        await ctx.respond(
            embed=hikari.Embed(title="❌ Невозможно отправить сообщение в треде!", color=const.ERROR_COLOR),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    me = ctx.app.cache.get_member(ctx.guild_id, ctx.app.user_id)
    assert isinstance(send_to, hikari.TextableGuildChannel) and me is not None

    perms = lightbulb.utils.permissions_in(send_to, me)
    if not helpers.includes_permissions(perms, hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL):
        raise lightbulb.BotMissingRequiredPermission(
            perms=hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL
        )

    await send_to.send(text[:2000])

    await ctx.respond(
        embed=hikari.Embed(title="✅ Сообщение отправлено!", color=const.EMBED_GREEN), flags=hikari.MessageFlag.EPHEMERAL
    )


@misc.command
@lightbulb.add_checks(
    bot_has_permissions(
        hikari.Permissions.SEND_MESSAGES, hikari.Permissions.READ_MESSAGE_HISTORY, hikari.Permissions.VIEW_CHANNEL
    ),
    has_permissions(hikari.Permissions.MANAGE_MESSAGES),
)
@lightbulb.option("message_link", "Ссылка на сообщение", type=str)
@lightbulb.command("edit", "Отредактировать сообщение отправленное ботом", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def edit(ctx: ChenSlashContext, message_link: str) -> None:

    message = await helpers.parse_message_link(ctx, message_link)
    if not message:
        return

    assert ctx.guild_id is not None

    channel = ctx.app.cache.get_guild_channel(message.channel_id) or await ctx.app.rest.fetch_channel(
        message.channel_id
    )

    me = ctx.app.cache.get_member(ctx.guild_id, ctx.app.user_id)

    overwrites_channel = (
        channel
        if not isinstance(channel, hikari.GuildThreadChannel)
        else ctx.app.cache.get_guild_channel(channel.parent_id)
    )
    assert (
        isinstance(channel, (hikari.TextableGuildChannel))
        and me is not None
        and isinstance(overwrites_channel, hikari.GuildChannel)
    )

    perms = lightbulb.utils.permissions_in(overwrites_channel, me)
    if not helpers.includes_permissions(
        perms,
        hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY,
    ):
        raise lightbulb.BotMissingRequiredPermission(
            perms=hikari.Permissions.SEND_MESSAGES
            | hikari.Permissions.VIEW_CHANNEL
            | hikari.Permissions.READ_MESSAGE_HISTORY
        )

    if message.author.id != ctx.app.user_id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Не автор",
                description="Бот не автор этого сообщения, поэтому не может его отредактировать.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    modal = miru.Modal(f"Редактирование сообщения")
    modal.add_item(
        miru.TextInput(
            label="Контент",
            style=hikari.TextInputStyle.PARAGRAPH,
            placeholder="Введите новый текст...",
            value=message.content,
            required=True,
            max_length=2000,
        )
    )
    await modal.send(ctx.interaction)
    await modal.wait()
    if not modal.values:
        return

    content = list(modal.values.values())[0]
    await message.edit(content=content)

    await modal.get_response_context().respond(
        embed=hikari.Embed(title="✅ Сообщение отредактировано!", color=const.EMBED_GREEN), flags=hikari.MessageFlag.EPHEMERAL
    )


@misc.command
@lightbulb.add_checks(
    bot_has_permissions(
        hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY
    )
)
@lightbulb.command("Raw Content", "Показать RAW данного сообщение", pass_options=True)
@lightbulb.implements(lightbulb.MessageCommand)
async def raw(ctx: ChenMessageContext, target: hikari.Message) -> None:
    if target.content:
        await ctx.respond(f"```{target.content[:1990]}```", flags=hikari.MessageFlag.EPHEMERAL)
    else:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Отсутствует контент",
                description="Похоже это сообщение не имеет содержимого для отображения!",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )


@misc.command
@lightbulb.option("zero", "Включая ноль?", type=bool, default=False)
@lightbulb.option("count", "До какого числа нумерация", type=int, required=True)
@lightbulb.option("message_link", "Ссылка на сообщение", type=str, required=True)
@lightbulb.command("emoji", "Добавить нумерованные эмодзи", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def emoji(ctx: ChenSlashContext, message_link: str, count: int, zero: bool) -> None:

    message = await helpers.parse_message_link(ctx, message_link)
    if not message:
        return

    assert ctx.guild_id is not None

    channel = ctx.app.cache.get_guild_channel(message.channel_id) or await ctx.app.rest.fetch_channel(
        message.channel_id
    )

    assert isinstance(channel, hikari.TextableGuildChannel) is not None

    perms = lightbulb.utils.permissions_in(channel, ctx.member)
    if not helpers.includes_permissions(perms, hikari.Permissions.SEND_MESSAGES):
        raise lightbulb.MissingRequiredPermission(
            perms=hikari.Permissions.SEND_MESSAGES
        )
    else:
        raw_numbers = ['0️⃣', '1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']

        if zero:
            numbers = raw_numbers[:count]
        else:
            numbers = raw_numbers[1:count+1]

        task = asyncio.create_task(utils.helpers.add_emoji(message, numbers))

        await ctx.respond(
            embed=hikari.Embed(
                title="✅ Эмоции добавлены!",
                color=const.EMBED_GREEN),
            flags=hikari.MessageFlag.EPHEMERAL,
        )

        await task


@misc.command
@lightbulb.option("timezone", "Часовой пояс, который будет установлен по-умолчанию. Example: 'Europe/Kiev'", autocomplete=True)
@lightbulb.command(
    "timezone", "Устанавливает часовой пояс для других команд, связанных со временем.", pass_options=True
)
@lightbulb.implements(lightbulb.SlashCommand)
async def set_timezone(ctx: ChenSlashContext, timezone: str) -> None:
    if timezone.title() not in pytz.common_timezones:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Некорректный часовой пояс",
                description="Невалидный часовой пояс. Посмотреть Ваш часовой пояс можно [тут](https://24timezones.com/)",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await ctx.app.db.execute(
        """
    INSERT INTO preferences (user_id, timezone) 
    VALUES ($1, $2) 
    ON CONFLICT (user_id) DO 
    UPDATE SET timezone = $2""",
        ctx.user.id,
        timezone.title(),
    )
    await ctx.app.db_cache.refresh(table="preferences", user_id=ctx.user.id, timezone=timezone.title())

    await ctx.respond(
        embed=hikari.Embed(
            title="✅ Часовой пояс установлен!",
            description=f"Часовой пояс изменен на `{timezone.title()}`",
            color=const.EMBED_GREEN,
        ),
        flags=hikari.MessageFlag.EPHEMERAL,
    )


@set_timezone.autocomplete("timezone")
async def tz_opts(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value:
        assert isinstance(option.value, str)
        return get_close_matches(option.value.title(), pytz.common_timezones, 25)
    return []


@misc.command
@lightbulb.option(
    "style",
    "Timestamp style.",
    choices=[
        "t - Время кратко",
        "T - Время целиком",
        "d - Дата кратко",
        "D - Дата целиком",
        "f - Дата и время кратко",
        "F - Дата и время целиком",
        "R - Относительно",
    ],
    required=False,
)
@lightbulb.option("time", "Создание временной метки. Пример: 'через 20 минут', '2022-04-03', '21:43'")
@lightbulb.command(
    "timestamp", "Создание временной метки в Discord формате", pass_options=True
)
@lightbulb.implements(lightbulb.SlashCommand)
async def timestamp_gen(ctx: ChenSlashContext, time: str, style: t.Optional[str] = None) -> None:
    try:
        converted_time = await ctx.app.scheduler.convert_time(
            time, conversion_mode=ConversionMode.ABSOLUTE, user=ctx.user
        )
    except ValueError as error:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Error: введена некорректная дата",
                description=f"**Error:** {error}",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return
    style = style.split(" -")[0] if style else "f"

    await ctx.respond(
        f"`{helpers.format_dt(converted_time, style=style)}` --> {helpers.format_dt(converted_time, style=style)}"
    )


def load(bot: ChenBot) -> None:
    bot.add_plugin(misc)


def unload(bot: ChenBot) -> None:
    bot.remove_plugin(misc)


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
