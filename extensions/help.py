from __future__ import annotations

import typing as t

import hikari
import lightbulb

import etc.constants as const
from models.context import ChenSlashContext
from models.plugin import ChenPlugin

if t.TYPE_CHECKING:
    from models import ChenBot


help = ChenPlugin("Help")


help_embeds = {
    # Default no topic help
    None: hikari.Embed(
        title="ℹ️ __Help__",
        description=f"""**Привет, это помощь по использованию бота Chen!**
            
Чтобы начать использовать бота, набери `/` чтобы увидеть все доступные команды! Чтобы посмотреть справку по нескольким особенностям можно рабрать `/help topic_name`.

Если нужна помощь или вы обнаружили баг, можно написать на [Samuro_dev сервер]({const.HELP_LINK})!

Thank you for using Chen!""",
        color=const.EMBED_BLUE,
    ),
    # Default no topic help for people with manage guild perms
    "admin_home": hikari.Embed(
        title="ℹ️ __Help__",
        description=f"""**Это хелп по использованию команд бота Chen**
            
Чтобы начать использовать бота набери `/` чтобы увидеть все доступные команды! Несколько дополнительных настроек можно изучить командами `/help topic_name`.

Для настройки бота на сервере необходимо набрать `/settings`.

Проверить, что бот корректно настроен можно командой `/troubleshoot`.

Если нужна помощь или вы обнаружили баг, можно написать на [Samuro_dev сервер]({const.HELP_LINK})!

""",
        color=const.EMBED_BLUE,
    ),
    "time-formatting": hikari.Embed(
        title="ℹ️ __Help: Формат времени__",
        description="""Бот поддерживает ввод времени в различных форматах:

**Даты:**
`2022-03-04 23:43`
`04/03/2022 23:43`
`2022/04/03 11:43PM`
`...`

**Относительный ввод:**
`через 10 минут`
`через 2 дня`
`...`

**ℹ️ Заметка:**
Абсолютное время требует, чтобы бот знал ваш часовой пояс. Его можно установить командой `/timezone`.
""",
        color=const.EMBED_BLUE,
    ),
    "permissions": hikari.Embed(
        title="ℹ️ __Help: Разрешения__",
        description="""Разрешения редактируются через настройки сервера:
```Настройки сервера > Интеграция > Chen```
Здесь можно настроить разрешения для каждой команды, как вы считаете нужным или оставить по-умолчанию""",
        color=const.EMBED_BLUE,
    ).set_image("https://cdn.discordapp.com/attachments/836300326172229672/949047433038544896/unknown.png"),
    "configuration": hikari.Embed(
        title="ℹ️ ___Help: Конфигурация__",
        description="""Для настройки бота используйте команду `/settings`. Это откроет интерактивное меню, в котором можно изменить различные настройки бота под ваш сервер.""",
        color=const.EMBED_BLUE,
    ),
}


@help.command
@lightbulb.option(
    "topic",
    "Особенности настройки бота",
    required=False,
    choices=["time-formatting", "configuration", "permissions"],
)
@lightbulb.command("help", "Получить помощь по различным функциям бота", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def help_cmd(ctx: ChenSlashContext, topic: t.Optional[str] = None) -> None:
    if ctx.member:
        topic = (
            topic or "admin_home"
            if (lightbulb.utils.permissions_for(ctx.member) & hikari.Permissions.MANAGE_GUILD)
            else topic
        )
    await ctx.respond(embed=help_embeds[topic])


def load(bot: ChenBot) -> None:
    bot.add_plugin(help)


def unload(bot: ChenBot) -> None:
    bot.remove_plugin(help)


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
