import logging
import typing as t
from difflib import get_close_matches
from itertools import chain

import hikari
import lightbulb
import miru

from etc import constants as const
from etc.text import tags as txt
from models import AuthorOnlyNavigator
from models import ChenSlashContext
from models import Tag
from models.bot import ChenBot
from models.plugin import ChenPlugin
from utils import helpers

logger = logging.getLogger(__name__)

tags = ChenPlugin("Tag", include_datastore=True)


class TagEditorModal(miru.Modal):
    """Modal for creation and editing of tags."""

    def __init__(self, name: t.Optional[str] = None, content: t.Optional[str] = None) -> None:
        title = "Создать метки"
        if content:
            title = f"Редактирование метки {name}"

        super().__init__(title, timeout=600, autodefer=False)

        if not content:
            self.add_item(
                miru.TextInput(
                    label=txt.title.TagName,
                    placeholder=txt.desc.TagName,
                    required=True,
                    min_length=3,
                    max_length=100,
                    value=name,
                )
            )
        self.add_item(
            miru.TextInput(
                label=txt.title.TagContent,
                style=hikari.TextInputStyle.PARAGRAPH,
                placeholder=txt.desc.TagContent,
                required=True,
                max_length=1500,
                value=content,
            )
        )

        self.tag_name = ""
        self.tag_content = ""

    async def callback(self, ctx: miru.ModalContext) -> None:
        if not ctx.values:
            return

        for item, value in ctx.values.items():
            assert isinstance(item, miru.TextInput)
            if item.label == txt.title.TagName:
                self.tag_name = value
            elif item.label == txt.title.TagContent:
                self.tag_content = value


@tags.command
@lightbulb.option("ephemeral", "Если True, отправляет так, что только вы видите", type=bool, default=False)
@lightbulb.option("name", "Имя метки, которую вы хотите вызвать", autocomplete=True)
@lightbulb.command("tag", "Вызвать метку и отобразить содержимое", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def tag_cmd(ctx: ChenSlashContext, name: str, ephemeral: bool = False) -> None:
    assert ctx.guild_id is not None

    tag = await Tag.fetch(name.casefold(), ctx.guild_id, add_use=True)

    if not tag:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Unknown tag",
                description="Cannot find tag by that name.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return
    flags = hikari.MessageFlag.EPHEMERAL if ephemeral else hikari.MessageFlag.NONE
    await ctx.respond(content=tag.parse_content(ctx), flags=flags)


@tag_cmd.autocomplete("name")
async def tag_name_ac(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value and interaction.guild_id:
        return (await Tag.fetch_closest_names(str(option.value), interaction.guild_id)) or []
    return []


@tags.command
@lightbulb.command("tags", "All commands for managing tags.")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def tag_group(ctx: ChenSlashContext) -> None:
    pass


@tag_group.child
@lightbulb.command("create", "Создать новую метку. Откроется модальное окно")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_create(ctx: ChenSlashContext) -> None:

    assert ctx.guild_id is not None and ctx.member is not None

    modal = TagEditorModal()
    await modal.send(ctx.interaction)
    await modal.wait()
    if not modal.values:
        return

    mctx = modal.get_response_context()

    tag = await Tag.fetch(modal.tag_name.casefold(), ctx.guild_id)
    if tag:
        await mctx.respond(
            embed=hikari.Embed(
                title="❌ Метка существует",
                description=f"Эта метка уже существует. Если ее автора уже нет на сервере используй команду `/tags claim {modal.tag_name.casefold()}`",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    tag = await Tag.create(
        guild=ctx.guild_id,
        name=modal.tag_name.casefold(),
        owner=ctx.author,
        creator=ctx.author,
        aliases=[],
        content=modal.tag_content,
    )

    await mctx.respond(
        embed=hikari.Embed(
            title="✅ Метка создана",
            description=f"Ее можно вызвать командой `/tag {tag.name}`",
            color=const.EMBED_GREEN,
        )
    )


@tag_group.child
@lightbulb.option("name", "Имя метки по которой нужно получить информацию", autocomplete=True)
@lightbulb.command("info", "Отобразить информацию о метке", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_info(ctx: ChenSlashContext, name: str) -> None:
    assert ctx.guild_id is not None
    tag = await Tag.fetch(name.casefold(), ctx.guild_id)

    if not tag:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Неизвестная метка",
                description="Не получается найти метку по имени",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    owner = ctx.app.cache.get_member(ctx.guild_id, tag.owner_id) or tag.owner_id
    creator = (
        (ctx.app.cache.get_member(ctx.guild_id, tag.creator_id) or tag.creator_id) if tag.creator_id else "Unknown"
    )
    aliases = ", ".join(tag.aliases) if tag.aliases else None

    embed = hikari.Embed(
        title=f"💬 Метка: {tag.name}",
        description=f"**Псевдонимы:** `{aliases}`\n**Владелец:** `{owner}`\n**Создатель:** `{creator}`\n**Использований:** `{tag.uses}`",
        color=const.EMBED_BLUE,
    )
    if isinstance(owner, hikari.Member):
        embed.set_author(name=str(owner), icon=owner.display_avatar_url)

    await ctx.respond(embed=embed)


@tag_info.autocomplete("name")
async def tag_info_name_ac(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value and interaction.guild_id:
        return (await Tag.fetch_closest_names(str(option.value), interaction.guild_id)) or []
    return []


@tag_group.child
@lightbulb.option("alias", "Добавить псевдоним к метке")
@lightbulb.option("name", "Метка к которой добавляется псевдоним", autocomplete=True)
@lightbulb.command("alias", "Добавить псевдоним к вашей метке", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_alias(ctx: ChenSlashContext, name: str, alias: str) -> None:
    assert ctx.guild_id is not None

    alias_tag = await Tag.fetch(alias.casefold(), ctx.guild_id)
    if alias_tag:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Псевдоним занят",
                description=f"Метка или псевдоним уже заняты, смените имя",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    tag = await Tag.fetch(name.casefold(), ctx.guild_id)

    if tag and tag.owner_id == ctx.author.id:
        tag.aliases = tag.aliases if tag.aliases else []

        if alias.casefold() not in tag.aliases and len(tag.aliases) <= 5:
            tag.aliases.append(alias.casefold())

        else:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Слишком много псевдонимов",
                    description=f"Метка `{tag.name}` может иметь до **5** псевдонимов",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        await tag.update()

        await ctx.respond(
            embed=hikari.Embed(
                title="✅ Метка создана",
                description=f"Псевдоним создан для метки`{tag.name}`!\nТеперь ее можно вызвать так же командой `/tag {alias.casefold()}`",
                color=const.EMBED_GREEN,
            )
        )

    else:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Неверная метка",
                description="Вы либо не являетесь владельцем метки, либо она не существует",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return


@tag_alias.autocomplete("name")
async def tag_alias_name_ac(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value and interaction.guild_id:
        return (await Tag.fetch_closest_owned_names(str(option.value), interaction.guild_id, interaction.user)) or []
    return []


@tag_group.child
@lightbulb.option("alias", "Имя псевдонима для удаления")
@lightbulb.option("name", "Метка из которой нужно удалить псевдоним", autocomplete=True)
@lightbulb.command("delalias", "Удалить псевдоним из метки", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_delalias(ctx: ChenSlashContext, name: str, alias: str) -> None:
    assert ctx.guild_id is not None

    tag = await Tag.fetch(name.casefold(), ctx.guild_id)
    if tag and tag.owner_id == ctx.author.id:

        if tag.aliases and alias.casefold() in tag.aliases:
            tag.aliases.remove(alias.casefold())

        else:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Неизвестный псевдоним",
                    description=f"Метка `{tag.name}` не имеет псевдонима `{alias.casefold()}`",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        await tag.update()

        await ctx.respond(
            embed=hikari.Embed(
                title="✅ Псевидоним удален",
                description=f"Псевдоним `{alias.casefold()}` метки `{tag.name}` был удален",
                color=const.EMBED_GREEN,
            )
        )

    else:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Неверная метка",
                description="Вы либо не являетесь владельцем метки, либо она не существует",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return


@tag_delalias.autocomplete("name")
async def tag_delalias_name_ac(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value and interaction.guild_id:
        return (await Tag.fetch_closest_owned_names(str(option.value), interaction.guild_id, interaction.user)) or []
    return []


@tag_group.child
@lightbulb.option("receiver", "Пользователь, который получит метку", type=hikari.Member)
@lightbulb.option("name", "Имя метки", autocomplete=True)
@lightbulb.command(
    "transfer",
    "Передать право на метку другому пользователю",
    pass_options=True,
)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_transfer(ctx: ChenSlashContext, name: str, receiver: hikari.Member) -> None:
    helpers.is_member(receiver)
    assert ctx.guild_id is not None

    tag = await Tag.fetch(name.casefold(), ctx.guild_id)

    if tag and tag.owner_id == ctx.author.id:

        tag.owner_id = receiver.id
        await tag.update()

        await ctx.respond(
            embed=hikari.Embed(
                title="✅ Метка передана",
                description=f"Метка `{tag.name}` успешно передана {receiver.mention}",
                color=const.EMBED_GREEN,
            )
        )

    else:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Неверная метка",
                description="Вы либо не являетесь владельцем метки, либо она не существует",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return


@tag_transfer.autocomplete("name")
async def tag_transfer_name_ac(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value and interaction.guild_id:
        return (await Tag.fetch_closest_owned_names(str(option.value), interaction.guild_id, interaction.user)) or []
    return []


@tag_group.child
@lightbulb.option("name", "Имя метки для присвоения", autocomplete=True)
@lightbulb.command(
    "claim",
    "Получить права на метку, которая была создана пользователем покинувшим сервер",
    pass_options=True,
)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_claim(ctx: ChenSlashContext, name: str) -> None:

    assert ctx.guild_id is not None and ctx.member is not None

    tag = await Tag.fetch(name.casefold(), ctx.guild_id)

    if tag:
        members = ctx.app.cache.get_members_view_for_guild(ctx.guild_id)
        if tag.owner_id not in members.keys() or (
            helpers.includes_permissions(
                lightbulb.utils.permissions_for(ctx.member), hikari.Permissions.MANAGE_MESSAGES
            )
            and tag.owner_id != ctx.member.id
        ):
            tag.owner_id = ctx.author.id
            await tag.update()

            await ctx.respond(
                embed=hikari.Embed(
                    title="✅ Метка переприсвоена",
                    description=f"Метка `{tag.name}` теперь переназначена на тебя",
                    color=const.EMBED_GREEN,
                )
            )

        else:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Присутствует владелец",
                    description="Заявить права можно только на метки, создатели которых покинули сервер",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

    else:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Неизвестная метка",
                description="Не получается найти метку по имени",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return


@tag_claim.autocomplete("name")
async def tag_claim_name_ac(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value and interaction.guild_id:
        return (await Tag.fetch_closest_owned_names(str(option.value), interaction.guild_id, interaction.user)) or []
    return []


@tag_group.child
@lightbulb.option("name", "Имя изменяемой метки", autocomplete=True)
@lightbulb.command("edit", "Изменить содержимое пренадлежащей вам метки", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_edit(ctx: ChenSlashContext, name: str) -> None:

    assert ctx.member is not None and ctx.guild_id is not None

    tag = await Tag.fetch(name.casefold(), ctx.guild_id)

    if not tag or tag.owner_id != ctx.author.id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Неверная метка",
                description="Вы либо не являетесь владельцем метки, либо она не существует",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    modal = TagEditorModal(name=tag.name, content=tag.content)
    await modal.send(ctx.interaction)
    await modal.wait()
    if not modal.values:
        return

    mctx = modal.get_response_context()

    tag.content = modal.tag_content

    await tag.update()

    await mctx.respond(
        embed=hikari.Embed(
            title="✅ Метка изменена",
            description=f"Метка `{tag.name}` была успешно изменена",
            color=const.EMBED_GREEN,
        )
    )


@tag_edit.autocomplete("name")
async def tag_edit_name_ac(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value and interaction.guild_id:
        return (await Tag.fetch_closest_owned_names(str(option.value), interaction.guild_id, interaction.user)) or []
    return []


@tag_group.child
@lightbulb.option("name", "Имя метки для удаления", autocomplete=True)
@lightbulb.command("delete", "Удалить метку", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_delete(ctx: ChenSlashContext, name: str) -> None:

    assert ctx.member is not None and ctx.guild_id is not None

    tag = await Tag.fetch(name.casefold(), ctx.guild_id)

    if tag and (
        (tag.owner_id == ctx.author.id)
        or helpers.includes_permissions(lightbulb.utils.permissions_for(ctx.member), hikari.Permissions.MANAGE_MESSAGES)
    ):

        await tag.delete()

        await ctx.respond(
            embed=hikari.Embed(
                title="✅ Метка удалена",
                description=f"Метка `{tag.name}` была успешно удалена",
                color=const.EMBED_GREEN,
            )
        )

    else:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Неверная метка",
                description="Вы либо не являетесь владельцем метки, либо она не существует",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return


@tag_delete.autocomplete("name")
async def tag_delete_name_ac(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value and interaction.guild_id:
        return (await Tag.fetch_closest_owned_names(str(option.value), interaction.guild_id, interaction.user)) or []
    return []


@tag_group.child
@lightbulb.option("owner", "Показать только метки определенного пользователя", type=hikari.User, required=False)
@lightbulb.command("list", "Список всех меток на сервере", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_list(ctx: ChenSlashContext, owner: t.Optional[hikari.User] = None) -> None:
    assert ctx.member is not None and ctx.guild_id is not None

    tags = await Tag.fetch_all(ctx.guild_id, owner)

    if tags:
        tags_fmt = [f"**#{i+1}** - `{tag.uses}` использует: `{tag.name}`" for i, tag in enumerate(tags)]
        # Only show 8 tags per page
        tags_fmt = [tags_fmt[i * 8 : (i + 1) * 8] for i in range((len(tags_fmt) + 8 - 1) // 8)]

        embeds = [
            hikari.Embed(
                title=f"💬 Доступные метки{f' пользователя {owner.username}' if owner else ''}:",
                description="\n".join(contents),
                color=const.EMBED_BLUE,
            )
            for contents in tags_fmt
        ]

        navigator = AuthorOnlyNavigator(ctx, pages=embeds)  # type: ignore
        await navigator.send(ctx.interaction)

    else:
        await ctx.respond(
            embed=hikari.Embed(
                title=f"💬 Доступные метки{f' пользователя {owner.username}' if owner else ''}:",
                description="Метки не найдены. Вы можете их создать командой`/tags create`",
                color=const.EMBED_BLUE,
            )
        )


@tag_group.child
@lightbulb.option("query", "Имя метки или псевдонима")
@lightbulb.command("search", "Поиск меток по имени или псевдониму", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_search(ctx: ChenSlashContext, query: str) -> None:

    assert ctx.member is not None and ctx.guild_id is not None

    tags = await Tag.fetch_all(ctx.guild_id)

    if tags:
        names = [tag.name for tag in tags]
        aliases = [tag.aliases for tag in tags if tag.aliases]
        aliases = list(chain(*aliases))

        response = [name for name in get_close_matches(query.casefold(), names)]
        response += [f"*{alias}*" for alias in get_close_matches(query.casefold(), aliases)]

        if response:
            await ctx.respond(
                embed=hikari.Embed(title=f"🔎 Результат поиска для '{query}':", description="\n".join(response[:10]))
            )

        else:
            await ctx.respond(
                embed=hikari.Embed(
                    title="Не найдены",
                    description="Не удалось найти метки с таким именем",
                    color=const.WARN_COLOR,
                )
            )

    else:
        await ctx.respond(
            embed=hikari.Embed(
                title="🔎 Ошибка поиска",
                description="На этом сервере пока нет меток. Их можно создать командой `/tags create`",
                color=const.WARN_COLOR,
            )
        )


def load(bot: ChenBot) -> None:
    bot.add_plugin(tags)


def unload(bot: ChenBot) -> None:
    bot.remove_plugin(tags)


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
