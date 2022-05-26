import enum
import logging
import typing as t

import hikari
import lightbulb
import miru

import models
from etc import constants as const
from etc.text import role_buttons as txt
from models import ChenBot
from models import ChenSlashContext
from models.checks import has_permissions
from models.plugin import ChenPlugin
from models.rolebutton import RoleButton
from models.rolebutton import RoleButtonMode
from utils import helpers
from utils.ratelimiter import BucketType
from utils.ratelimiter import RateLimiter

logger = logging.getLogger(__name__)

role_buttons = ChenPlugin("Rolebuttons")

BUTTON_STYLES = {
    "Blurple": hikari.ButtonStyle.PRIMARY,
    "Grey": hikari.ButtonStyle.SECONDARY,
    "Green": hikari.ButtonStyle.SUCCESS,
    "Red": hikari.ButtonStyle.DANGER,
}
BUTTON_MODES = {
    "Toggle": RoleButtonMode.TOGGLE,
    "Add": RoleButtonMode.ADD_ONLY,
    "Remove": RoleButtonMode.REMOVE_ONLY,
}

role_button_ratelimiter = RateLimiter(2, 1, BucketType.MEMBER, wait=False)


class RoleButtonConfirmType(enum.Enum):
    """Types of confirmation prompts for rolebuttons."""

    ADD = "add"
    REMOVE = "remove"


class RoleButtonConfirmModal(miru.Modal):
    """A modal to handle editing of confirmation prompts for rolebuttons."""

    def __init__(self, role_button: RoleButton, type: RoleButtonConfirmType) -> None:
        super().__init__(f"Сообщение для кнопки #{role_button.id}", timeout=600, autodefer=False)
        self.add_item(
            miru.TextInput(
                label="Title",
                placeholder="Заголовок кнопки, оставить пустым для сброса...",
                min_length=1,
                max_length=100,
                value=role_button.add_title if type == RoleButtonConfirmType.ADD else role_button.remove_title,
            )
        )
        self.add_item(
            miru.TextInput(
                label="Description",
                placeholder="Описание кнопки, оставить пустым для сброса...",
                min_length=1,
                max_length=3000,
                style=hikari.TextInputStyle.PARAGRAPH,
                value=role_button.add_description
                if type == RoleButtonConfirmType.ADD
                else role_button.remove_description,
            )
        )
        self.role_button = role_button
        self.type = type

    async def callback(self, context: miru.ModalContext) -> None:
        values = list(context.values.values())

        if self.type == RoleButtonConfirmType.ADD:
            self.role_button.add_title = values[0].strip()
            self.role_button.add_description = values[1].strip()
        elif self.type == RoleButtonConfirmType.REMOVE:
            self.role_button.remove_title = values[0].strip()
            self.role_button.remove_description = values[1].strip()

        await self.role_button.update(context.author)

        await context.respond(
            embed=hikari.Embed(
                title=f"✅ Описание кнопки обновлено!",
                description=f"Описание обновлено для кнопки ID: **#{self.role_button.id}**.",
                color=0x77B255,
            )
        )


@role_buttons.listener(miru.ComponentInteractionCreateEvent, bind=True)
async def rolebutton_listener(plugin: ChenPlugin, event: miru.ComponentInteractionCreateEvent) -> None:
    """Statelessly listen for rolebutton interactions"""

    if not event.interaction.custom_id.startswith("RB:"):
        return

    entry_id = int(event.interaction.custom_id.split(":")[1])
    role_id = int(event.interaction.custom_id.split(":")[2])

    if not event.context.guild_id:
        return

    role = plugin.app.cache.get_role(role_id)

    if not role:
        await event.context.respond(
            embed=hikari.Embed(
                title="❌ Связь нарушена",
                description="Роль, на которую указывала эта кнопка была удалена. Сообщите об этом администратору сообщества!",
                color=0xFF0000,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    me = plugin.app.cache.get_member(event.context.guild_id, plugin.app.user_id)
    assert me is not None

    if not helpers.includes_permissions(lightbulb.utils.permissions_for(me), hikari.Permissions.MANAGE_ROLES):
        await event.context.respond(
            embed=hikari.Embed(
                title="❌ Недостаточно прав",
                description="Бот должен иметь права `Manage Roles`. Сообщите об этом администрации сообщества!",
                color=0xFF0000,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await role_button_ratelimiter.acquire(event.context)
    if role_button_ratelimiter.is_rate_limited(event.context):
        await event.context.respond(
            embed=hikari.Embed(
                title="❌ Тише!",
                description="Ты кликаешь слишком быстро!",
                color=0xFF0000,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await event.context.defer(hikari.ResponseType.DEFERRED_MESSAGE_CREATE, flags=hikari.MessageFlag.EPHEMERAL)

    try:
        assert event.context.member is not None
        role_button = await RoleButton.fetch(entry_id)

        if not role_button:  # This should theoretically never happen, but I do not trust myself
            await event.context.respond(
                embed=hikari.Embed(
                    title="❌ Потеряна информация",
                    description="В кнопке отсутствует информация или она была неправильно удалена! Сообщите об этом администратору!",
                    color=0xFF0000,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        if role.id in event.context.member.role_ids:

            if role_button.mode in [RoleButtonMode.TOGGLE, RoleButtonMode.REMOVE_ONLY]:
                await event.context.member.remove_role(role, reason=f"Удалена по кнопке (ID: {entry_id})")
                embed = hikari.Embed(
                    title=f"✅ {role_button.remove_title or 'Роль удалена'}",
                    description=f"{role_button.remove_description or f'Удаленная роль: {role.mention}'}",
                    color=0x77B255,
                )
            else:
                embed = hikari.Embed(
                    title="❌ Роль уже добавлена",
                    description=f"У тебя уже есть роль {role.mention}!",
                    color=0xFF0000,
                ).set_footer("Эта кнопка предназначена только для добавления ролей, но не для их удаления")

        else:

            if role_button.mode in [RoleButtonMode.TOGGLE, RoleButtonMode.ADD_ONLY]:
                await event.context.member.add_role(role, reason=f"Добавлена по кнопке (ID: {entry_id})")
                embed = hikari.Embed(
                    title=f"✅ {role_button.add_title or 'Роль добавлена'}",
                    description=f"{role_button.add_description or f'Добавленная роль: {role.mention}'}",
                    color=0x77B255,
                )
                if not role_button.add_description and role_button.mode == RoleButtonMode.TOGGLE:
                    embed.set_footer("Для удаления роли снова кликните по кнопке")
            else:
                embed = hikari.Embed(
                    title="❌ Роль уже удалена",
                    description=f"У вас нет роли {role.mention}!",
                    color=0xFF0000,
                ).set_footer("Эта кнопка предназначена только для удаления ролей, но не для добавления")

        await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    except (hikari.ForbiddenError, hikari.HTTPError):
        await event.context.respond(
            embed=hikari.Embed(
                title="❌ Недостаточно прав",
                description="Не удалось изменить роль из-за проблем с иерархией ролей. Сообщите об этом администрации!",
                color=0xFF0000,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )


@role_buttons.command
@lightbulb.command("rolebutton", "Commands relating to rolebuttons.")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def rolebutton(ctx: ChenSlashContext) -> None:
    pass


@rolebutton.child
@lightbulb.add_checks(has_permissions(hikari.Permissions.MANAGE_ROLES))
@lightbulb.command("list", "Список всех созданных кнопок ролей на этом сервере")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def rolebutton_list(ctx: ChenSlashContext) -> None:

    assert ctx.guild_id is not None

    buttons = await RoleButton.fetch_all(ctx.guild_id)

    if not buttons:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Error: Нет кнопок-ролей",
                description="На сервере не создавались кнопки. Попробуйте команду '/rolebutton add'",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    paginator = lightbulb.utils.StringPaginator(max_chars=500)
    for button in buttons:
        role = ctx.app.cache.get_role(button.role_id)
        channel = ctx.app.cache.get_guild_channel(button.channel_id)

        if role and channel:
            paginator.add_line(f"**#{button.id}** - {channel.mention} - {role.mention}")

        else:
            paginator.add_line(f"**#{button.id}** - C: `{button.channel_id}` - R: `{button.role_id}`")

    embeds = [
        hikari.Embed(
            title="Кнопки ролей на сервере:",
            description=page,
            color=const.EMBED_BLUE,
        )
        for page in paginator.build_pages()
    ]

    navigator = models.AuthorOnlyNavigator(ctx, pages=embeds)  # type: ignore
    await navigator.send(ctx.interaction)


@rolebutton.child
@lightbulb.add_checks(has_permissions(hikari.Permissions.MANAGE_ROLES))
@lightbulb.option(
    "button_id",
    "ID кнопки, которую необходимо удалить. Посмотреть ID можно командой /rolebutton list",
    type=int,
    min_value=0,
)
@lightbulb.command("delete", "Удалить кнопку роли", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def rolebutton_del(ctx: ChenSlashContext, button_id: int) -> None:
    assert ctx.guild_id is not None

    button = await RoleButton.fetch(button_id)

    if not button or button.guild_id != ctx.guild_id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Не найдена",
                description="Нет кнопки с таким ID. Посмотреть ID можно командой `/rolebutton list`",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    try:
        await button.delete(ctx.member)
    except hikari.ForbiddenError:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Недостаточно прав",
                description=f"Бот не может видеть и/или читать сообщения на канале, где должна быть кнопка (<#{button.channel_id}>).",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await ctx.respond(
        embed=hikari.Embed(
            title="✅ Успех",
            description=f"Кнопка **#{button.id}** успешно удалена!",
            color=const.EMBED_GREEN,
        )
    )


@rolebutton.child
@lightbulb.add_checks(has_permissions(hikari.Permissions.MANAGE_ROLES))
@lightbulb.option(
    "mode",
    "Режим работы кнопки",
    choices=["Toggle - Добавление и удаление ролей (default)", "Add - Только добавление ролей", "Remove - Только удаление ролей"],
    required=False,
)
@lightbulb.option(
    "style", "Изменить цвет кнопки", choices=["Blurple", "Grey", "Red", "Green"], required=False
)
@lightbulb.option(
    "label", "Измените текст кнопки. Для кнопки без текста наберите 'removelabel'", required=False
)
@lightbulb.option("emoji", "Изменить emoji на кнопке", type=hikari.Emoji, required=False)
@lightbulb.option("role", "Изменить выдаваемую роль", type=hikari.Role, required=False)
@lightbulb.option(
    "button_id", "ID кнопки. Посмотреть можно командой /rolebutton list", type=int, min_value=0
)
@lightbulb.command(
    "edit",
    "Изменить существующую кнопку",
    pass_options=True,
)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def rolebutton_edit(ctx: ChenSlashContext, **kwargs) -> None:
    assert ctx.guild_id is not None and ctx.member is not None
    params = {opt: value for opt, value in kwargs.items() if value is not None}

    button = await RoleButton.fetch(params.pop("button_id"))

    if not button or button.guild_id != ctx.guild_id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Не найдена",
                description="Нет кнопки с таким ID. Посмотреть ID можно командой `/rolebutton list`",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    if label := params.get("label"):
        params["label"] = label if label.casefold() != "removelabel" else None

    if style := params.pop("style", None):
        params["style"] = BUTTON_STYLES[style]

    if mode := params.pop("mode", None):
        params["mode"] = BUTTON_MODES[mode.split(" -")[0]]

    if emoji := params.get("emoji"):
        params["emoji"] = hikari.Emoji.parse(emoji)

    if role := params.pop("role", None):
        if role.is_managed or role.is_premium_subscriber_role:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Роль управляется",
                    description="Роль управляется другой интеграцией и не может быть изменена",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        top_role = ctx.member.get_top_role()
        guild = ctx.get_guild()
        if not guild or not top_role:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Ошибка кэшироания",
                    description="Пожалуйста напишите администрации о получении данной ошибки",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        if role.position >= top_role.position and not guild.owner_id == ctx.member.id:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Ошибка иерархии ролей",
                    description="Вы не можете создать роль, которая выше вашей самой высокой роли",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        params["role_id"] = role.id

    for param, value in params.items():
        setattr(button, param, value)

    try:
        await button.update(ctx.member)
    except hikari.ForbiddenError:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Недостаточно прав",
                description=f"Бот не может отредактировать сообщение.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    embed = hikari.Embed(
        title="✅ Сделано",
        description=f"Кнопка роли **#{button.id}** обновлена",
        color=const.EMBED_GREEN,
    )
    await ctx.respond(embed=embed)


@rolebutton.child
@lightbulb.add_checks(has_permissions(hikari.Permissions.MANAGE_ROLES))
@lightbulb.option(
    "mode",
    "Режим работы кнопки",
    choices=["Toggle - Добавление и удаление ролей (default)", "Add - Только добавление ролей", "Remove - Только удаление ролей"],
    required=False,
)
@lightbulb.option("label", "Текст кнопки", required=False)
@lightbulb.option("style", "Цвет кнопки.", choices=["Blurple", "Grey", "Red", "Green"], required=False)
@lightbulb.option("emoji", "emoji на кнопке", type=str)
@lightbulb.option("role", "Роль, которую должна выдавать кнопка", type=hikari.Role)
@lightbulb.option(
    "message_link",
    "Ссылка на сообщение, созданное этим ботом",
)
@lightbulb.command(
    "add",
    "Новая кнопка с ролью",
    pass_options=True,
)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def rolebutton_add(
    ctx: ChenSlashContext,
    message_link: str,
    role: hikari.Role,
    emoji: str,
    style: t.Optional[str] = None,
    label: t.Optional[str] = None,
    mode: t.Optional[str] = None,
) -> None:

    assert ctx.guild_id is not None and ctx.member is not None

    style = style or "Grey"
    mode = mode or "Toggle - Добавление и удаление ролей"

    message = await helpers.parse_message_link(ctx, message_link)
    if not message:
        return

    if message.author.id != ctx.app.user_id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Сообщение создано не этим ботом",
                description="Это сообщение нельзя отредактировать\n\nИспользуйте команды `/echo` или `/embed` для создания сообщения",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    if role.is_managed or role.is_premium_subscriber_role:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Роль управляется",
                description="Роль управляется другой интеграцией и не может быть изменена",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    top_role = ctx.member.get_top_role()
    guild = ctx.get_guild()

    if not guild or not top_role:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Ошибка кэширования",
                description="Пожалуйста напишите администрации о получении данной ошибки",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    if role.position >= top_role.position and not guild.owner_id == ctx.member.id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Ошибка иерархии ролей",
                description="Вы не можете создать роль, которая выше вашей самой высокой роли",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    parsed_emoji = hikari.Emoji.parse(emoji)
    buttonstyle = BUTTON_STYLES[style.capitalize()]

    try:
        button = await RoleButton.create(
            ctx.guild_id, message, role, parsed_emoji, buttonstyle, BUTTON_MODES[mode.split(" -")[0]], label, ctx.member
        )
    except ValueError:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Слишком много кнопок",
                description="Прикреплено максимальное количество кнопок. Создайте новое сообщение",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return
    except hikari.ForbiddenError:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Недостаточно прав",
                description=f"Бот не может отредактировать сообщение",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await ctx.respond(
        embed=hikari.Embed(
            title="✅ Сделано",
            description=f"Новая кнопка с ролью {ctx.options.role.mention} в канале <#{message.channel_id}> создана",
            color=const.EMBED_GREEN,
        ).set_footer(f"ID кнопки: {button.id}")
    )


@rolebutton.child
@lightbulb.add_checks(has_permissions(hikari.Permissions.MANAGE_ROLES))
@lightbulb.option(
    "prompt_type",
    "'add' отображается при добавлении роли, 'remove' когда удаляется",
    choices=["add", "remove"],
)
@lightbulb.option(
    "button_id",
    "ID кнопки. Посмотреть ID командой /rolebutton list",
    type=int,
    min_value=0,
)
@lightbulb.command(
    "setprompt", "Пользовательское сообщение при добавлении или удалении роли", pass_options=True
)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def rolebutton_setprompt(ctx: ChenSlashContext, button_id: int, prompt_type: str) -> None:

    button = await RoleButton.fetch(button_id)
    if not button or button.guild_id != ctx.guild_id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Кнопка не найдена",
                description="Нет кнопки с указанным ID. Посмотреть ID можно командой `/rolebutton list`",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    modal = RoleButtonConfirmModal(button, RoleButtonConfirmType(prompt_type))
    await modal.send(ctx.interaction)


def load(bot: ChenBot) -> None:
    bot.add_plugin(role_buttons)


def unload(bot: ChenBot) -> None:
    bot.remove_plugin(role_buttons)


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
