import aiohttp
import hikari
import lightbulb

from config import Config
from etc import constants as const
from models.bot import ChenBot
from models.context import ChenSlashContext
from models.plugin import ChenPlugin

fandom = ChenPlugin("Fandom")


async def search_fandom(site: str, query: str) -> str:
    """Search a Fandom wiki with the specified query.

    Parameters
    ----------
    site : str
        The subdomain of the fandom wiki.
    query : str
        The query to search for.

    Returns
    -------
    str
        A formatted string ready to display to the enduser.

    Raises
    ------
    ValueError
        No results were found.
    """
    link = "https://{site}.fandom.com/ru/api.php?action=opensearch&search={query}&limit=5"

    query = query.replace(" ", "+")

    async with fandom.app.session.get(link.format(query=query, site=site)) as response:
        if response.status == 200:
            results = await response.json()
        else:
            raise RuntimeError(f"Failed to communicate with server. Response code: {response.status}")

    desc = ""
    if results[1]:  # 1 is text, 3 is links
        for result in results[1]:
            desc = f"{desc}[{result}]({results[3][results[1].index(result)]})\n"
        return desc
    else:
        raise ValueError("No results found for query.")


@fandom.command
@lightbulb.option("query", "Что вы ищите?")
@lightbulb.option("wiki", "Выберите вики. Это 'xxxx.fandom.com' часть ссылки.")
@lightbulb.command("fandom", "Найти статью на xxx.fandom.com", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def fandom_cmd(ctx: ChenSlashContext, wiki: str, query: str) -> None:
    await ctx.respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    try:
        results = await search_fandom(wiki, query)
        embed = hikari.Embed(
            title=f"{wiki} Wiki: {query}",
            description=results,
            color=const.EMBED_BLUE,
        )
    except ValueError:
        embed = hikari.Embed(
            title="❌ Не найдено",
            description=f"Ничего не найдено по запросу `{query}`",
            color=const.ERROR_COLOR,
        )
    except RuntimeError as e:
        embed = hikari.Embed(title="❌ Сетевая ошибка", description=f"```{e}```", color=const.ERROR_COLOR)
    await ctx.respond(embed=embed)


@fandom.command
@lightbulb.option("query", "Что вы ищите?")
@lightbulb.command(
    "hotswiki",
    "Поиск по статьям hots вики",
    pass_options=True,
    guilds=Config().DEBUG_GUILDS or (642852514865217578, 124864790110797824),
)
@lightbulb.implements(lightbulb.SlashCommand)
async def hotswiki(ctx: ChenSlashContext, query: str, wiki: str = "heroesofthestorm") -> None:
    await ctx.respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    try:
        results = await search_fandom(f"{wiki}", query)
        embed = hikari.Embed(
            title=f"HotS Wiki: {query}",
            description=results,
            color=(36, 211, 252),
        )
    except ValueError:
        embed = hikari.Embed(
            title="❌ Не найдено",
            description=f"Ничего не найдено по запросу `{query}`",
            color=const.ERROR_COLOR,
        )
    except RuntimeError as e:
        embed = hikari.Embed(title="❌ Сетевая ошибка", description=f"```{e}```", color=const.ERROR_COLOR)
    await ctx.respond(embed=embed)


@fandom.command
@lightbulb.option("query", "Что вы ищите?")
@lightbulb.command(
    "hkwiki",
    "Поиск по статьям полого рыцаря",
    pass_options=True,
    guilds=Config().DEBUG_GUILDS or (642852514865217578, 124864790110797824),
)
@lightbulb.implements(lightbulb.SlashCommand)
async def hkwiki(ctx: ChenSlashContext, query: str) -> None:
    await ctx.respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    try:
        results = await search_fandom("hollowknight", query)
        embed = hikari.Embed(
            title=f"Hollow Knight Wiki: {query}",
            description=results,
            color=(250, 251, 246),
        )
    except ValueError:
        embed = hikari.Embed(
            title="❌ Не найдено",
            description=f"Ничего не найдено по запросу `{query}`",
            color=const.ERROR_COLOR,
        )
    except RuntimeError as e:
        embed = hikari.Embed(title="❌ Сетевая ошибка", description=f"```{e}```", color=const.ERROR_COLOR)
    await ctx.respond(embed=embed)


@fandom.command
@lightbulb.option("query", "Что вы ищите?")
@lightbulb.command(
    "stswiki",
    "Поиск по статьям шпиля",
    pass_options=True,
    guilds=Config().DEBUG_GUILDS or (642852514865217578, 124864790110797824),
)
@lightbulb.implements(lightbulb.SlashCommand)
async def stswiki(ctx: ChenSlashContext, query: str) -> None:
    await ctx.respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    try:
        results = await search_fandom("slay-the-spire", query)
        embed = hikari.Embed(
            title=f"Slay the Spire Wiki: {query}",
            description=results,
            color=(255, 201, 29),
        )
    except ValueError:
        embed = hikari.Embed(
            title="❌ Не найдено",
            description=f"Ничего не найдено по запросу `{query}`",
            color=const.ERROR_COLOR,
        )
    except RuntimeError as e:
        embed = hikari.Embed(title="❌ Сетевая ошибка", description=f"```{e}```", color=const.ERROR_COLOR)
    await ctx.respond(embed=embed)

def load(bot: ChenBot) -> None:
    bot.add_plugin(fandom)


def unload(bot: ChenBot) -> None:
    bot.remove_plugin(fandom)


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
