import datetime
import json
import logging
import typing as t

import hikari
import lightbulb
import miru

from etc import constants as const
from models import ChenBot
from models import ChenSlashContext
from models import Timer
from models import events
from models.plugin import ChenPlugin
from models.timer import TimerEvent
from models.views import AuthorOnlyNavigator
from utils import helpers

reminders = ChenPlugin(name="Reminders")

logger = logging.getLogger(__name__)


class SnoozeSelect(miru.Select):
    def __init__(self) -> None:
        super().__init__(
            options=[
                miru.SelectOption(label="5 минут", value="5"),
                miru.SelectOption(label="15 минут", value="15"),
                miru.SelectOption(label="30 минут", value="30"),
                miru.SelectOption(label="1 час", value="60"),
                miru.SelectOption(label="2 часа", value="120"),
                miru.SelectOption(label="3 часа", value="180"),
                miru.SelectOption(label="6 часов", value="360"),
                miru.SelectOption(label="12 часов", value="720"),
                miru.SelectOption(label="1 день", value="1440"),
            ],
            placeholder="Отложить напоминание",
        )

    async def callback(self, ctx: miru.ViewContext) -> None:
        assert isinstance(self.view, SnoozeView)

        expiry = helpers.utcnow() + datetime.timedelta(minutes=int(self.values[0]))
        assert (
            self.view.reminder_message.embeds[0].description
            and isinstance(ctx.app, ChenBot)
            and ctx.guild_id
            and isinstance(self.view, SnoozeView)
        )
        message = self.view.reminder_message.embeds[0].description.split("\n\n[Перейти к оригинальному сообщению!](")[0]

        reminder_data = {
            "message": message,
            "jump_url": ctx.message.make_link(ctx.guild_id),
            "additional_recipients": [],
            "is_snoozed": True,
        }

        timer = await ctx.app.scheduler.create_timer(
            expiry,
            TimerEvent.REMINDER,
            ctx.guild_id,
            ctx.user,
            ctx.channel_id,
            notes=json.dumps(reminder_data),
        )

        await ctx.edit_response(
            embed=hikari.Embed(
                title="✅ Напоминание отложено",
                description=f"Напоминание отложено до: {helpers.format_dt(expiry)} ({helpers.format_dt(expiry, style='R')})\n\n**Message:**\n{message}",
                color=const.EMBED_GREEN,
            ).set_footer(f"ID: {timer.id}"),
            components=miru.View()
            .add_item(miru.Select(placeholder="Напоминание отложено!", options=[miru.SelectOption("foo")], disabled=True))
            .build(),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        self.view.stop()


class SnoozeView(miru.View):
    def __init__(
        self, reminder_message: hikari.Message, *, timeout: t.Optional[float] = 600, autodefer: bool = True
    ) -> None:
        super().__init__(timeout=timeout, autodefer=autodefer)
        self.reminder_message = reminder_message
        self.add_item(SnoozeSelect())

    async def on_timeout(self) -> None:
        return await super().on_timeout()


@reminders.listener(miru.ComponentInteractionCreateEvent, bind=True)
async def reminder_component_handler(plugin: ChenPlugin, event: miru.ComponentInteractionCreateEvent) -> None:

    if not event.context.custom_id.startswith(("RMSS:", "RMAR:")):
        return

    assert event.context.guild_id is not None

    if event.context.custom_id.startswith("RMSS:"):  # Snoozes
        author_id = hikari.Snowflake(event.context.custom_id.split(":")[1])

        if author_id != event.context.user.id:
            await event.context.respond(
                embed=hikari.Embed(
                    title="❌ Недопустимое взаимодействие",
                    description="Вы не можете отложить чужое напоминание!",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        if not event.context.message.embeds:
            return

        view = miru.View.from_message(event.context.message)
        view.children[0].disabled = True  # type: ignore
        await event.context.edit_response(components=view.build())

        view = SnoozeView(event.context.message)  # I literally added InteractionResponse just for this
        resp = await event.context.respond(
            embed=hikari.Embed(
                title="🕔 Выберите продолжительность",
                description="Выберите продолжительность на которую нужно отложить напоминание",
                color=const.EMBED_BLUE,
            ),
            components=view.build(),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        view.start(await resp.retrieve_message())

    else:  # Reminder additional recipients
        timer_id = int(event.context.custom_id.split(":")[1])
        try:
            timer: Timer = await plugin.app.scheduler.get_timer(timer_id, event.context.guild_id)
            if timer.channel_id != event.context.channel_id or timer.event != TimerEvent.REMINDER:
                raise ValueError

        except ValueError:
            await event.context.respond(
                embed=hikari.Embed(
                    title="❌ Недопустимое взаимодействие",
                    description="Похоже это напоминание больше не действует",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            view = miru.View.from_message(event.context.message)

            for item in view.children:
                if isinstance(item, miru.Button):
                    item.disabled = True
            await event.context.message.edit(components=view.build())
            return

        if timer.user_id == event.context.user.id:
            await event.context.respond(
                embed=hikari.Embed(
                    title="❌ Некорректное взаимодействие",
                    description="Вы не можете это сделать в собственном напоминании",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        assert timer.notes is not None
        notes: t.Dict[str, t.Any] = json.loads(timer.notes)

        if event.context.user.id not in notes["additional_recipients"]:

            if len(notes["additional_recipients"]) > 50:
                await event.context.respond(
                    embed=hikari.Embed(
                        title="❌ Некорректное взаимодействие",
                        description="Слишком много людей подписались на это напоминание. Попробуйте создать новое напоминание",
                        color=const.ERROR_COLOR,
                    ),
                    flags=hikari.MessageFlag.EPHEMERAL,
                )
                return

            notes["additional_recipients"].append(event.context.user.id)
            timer.notes = json.dumps(notes)
            await plugin.app.scheduler.update_timer(timer)
            await event.context.respond(
                embed=hikari.Embed(
                    title="✅ Подписался на напоминание",
                    description="В заданное время вам придет уведомление",
                    color=const.EMBED_GREEN,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        else:
            notes["additional_recipients"].remove(event.context.user.id)
            timer.notes = json.dumps(notes)
            await plugin.app.scheduler.update_timer(timer)
            await event.context.respond(
                embed=hikari.Embed(
                    title="✅ Удален из напоминания",
                    description="Удален из списка получателей сообщения",
                    color=const.EMBED_GREEN,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )


@reminders.command
@lightbulb.command("reminder", "Управление напоминаниями")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def reminder(ctx: ChenSlashContext) -> None:
    pass


@reminder.child
@lightbulb.option("message", "Сообщение, которое будет отправлено в заданное время")
@lightbulb.option(
    "when", "Когда должно быть получено напоминание. Пример: 'через 10 минут', '2022-03-01', 'завтра в 20:00'"
)
@lightbulb.command("create", "Создать новое напоминание", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def reminder_create(ctx: ChenSlashContext, when: str, message: t.Optional[str] = None) -> None:

    assert ctx.guild_id is not None

    if message and len(message) >= 1000:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Слишком длинное напоминание",
                description="Сообщение не может превышать по длине **1000** символов!",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    try:
        time = await ctx.app.scheduler.convert_time(when, user=ctx.user, future_time=True)

    except ValueError as error:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Некорректная дата",
                description=f"**Error:** {error}",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    if (time - helpers.utcnow()).total_seconds() >= 31536000 * 5:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Некорректная дата",
                description="Попытка отправить сообщение в слишком далекое будущее",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    if (time - helpers.utcnow()).total_seconds() < 10:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Некорректная дата",
                description="Время напоминания должно быть хотя бы на 1 минуту позднее создания напоминания",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    reminder_data = {
        "message": message,
        "jump_url": None,
        "additional_recipients": [],
    }

    timer = await ctx.app.scheduler.create_timer(
        expires=time,
        event=TimerEvent.REMINDER,
        guild=ctx.guild_id,
        user=ctx.author,
        channel=ctx.channel_id,
        notes=json.dumps(reminder_data),
    )

    proxy = await ctx.respond(
        embed=hikari.Embed(
            title="✅ Напоминания",
            description=f"Напоминания для: {helpers.format_dt(time)} ({helpers.format_dt(time, style='R')})\n\n**Сообщение:**\n{message}",
            color=const.EMBED_GREEN,
        ).set_footer(f"Reminder ID: {timer.id}"),
        components=miru.View()
        .add_item(miru.Button(label="Напомни и мне!", emoji="✉️", custom_id=f"RMAR:{timer.id}"))
        .build(),
    )
    reminder_data["jump_url"] = (await proxy.message()).make_link(ctx.guild_id)
    timer.notes = json.dumps(reminder_data)

    await ctx.app.scheduler.update_timer(timer)


@reminder.child
@lightbulb.option("id", "ID таймера, который необходимо удалить. Посмотреть можно через /reminder list", type=int)
@lightbulb.command("delete", "Удалить напоминание", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def reminder_del(ctx: ChenSlashContext, id: int) -> None:

    assert ctx.guild_id is not None

    try:
        await ctx.app.scheduler.cancel_timer(id, ctx.guild_id)
    except ValueError:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Напоминание не найдено",
                description=f"Не найдено напоминание с ID **{id}**.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await ctx.respond(
        embed=hikari.Embed(
            title="✅ Напоминание удалено",
            description=f"Напоминание **{id}** успешно удалено",
            color=const.EMBED_GREEN,
        )
    )


@reminder.child
@lightbulb.command("list", "Список текущих напоминаний")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def reminder_list(ctx: ChenSlashContext) -> None:
    records = await ctx.app.db.fetch(
        """SELECT * FROM timers WHERE guild_id = $1 AND user_id = $2 AND event = 'reminder' ORDER BY expires""",
        ctx.guild_id,
        ctx.author.id,
    )

    if not records:
        await ctx.respond(
            embed=hikari.Embed(
                title="✉️ Нет напоминаний",
                description="Вы можете создать напоминания командой `/reminder create`!",
                color=const.WARN_COLOR,
            )
        )
        return

    reminders = []

    for record in records:
        time = datetime.datetime.fromtimestamp(record.get("expires"))
        notes = json.loads(record["notes"])["message"].replace("\n", " ")
        if len(notes) > 50:
            notes = notes[:47] + "..."

        reminders.append(
            f"**ID: {record.get('id')}** - {helpers.format_dt(time)} ({helpers.format_dt(time, style='R')})\n{notes}\n"
        )

    reminders = [reminders[i * 10 : (i + 1) * 10] for i in range((len(reminders) + 10 - 1) // 10)]

    pages = [
        hikari.Embed(title="✉️ Ваши напоминания:", description="\n".join(content), color=const.EMBED_BLUE)
        for content in reminders
    ]
    # TODO: wtf
    navigator = AuthorOnlyNavigator(ctx, pages=pages)  # type: ignore
    await navigator.send(ctx.interaction)


@reminders.listener(events.TimerCompleteEvent, bind=True)
async def on_reminder(plugin: ChenPlugin, event: events.TimerCompleteEvent):
    """
    Listener for expired reminders
    """
    if event.timer.event != TimerEvent.REMINDER:
        return

    guild = event.get_guild()

    if not guild:
        return

    assert event.timer.channel_id is not None

    user = guild.get_member(event.timer.user_id)

    if not user:
        return

    if not guild:
        return

    assert event.timer.notes is not None
    notes = json.loads(event.timer.notes)
    embed = hikari.Embed(
        title=f"✉️ {user.display_name}, {'отложенное ' if notes.get('is_snoozed') else ''}напоминание:",
        description=f"{notes['message']}\n\n[Перейти к оригинальному сообщению!]({notes['jump_url']})",
        color=const.EMBED_BLUE,
    )

    pings = [user.mention]

    if len(notes["additional_recipients"]) > 0:
        for user_id in notes["additional_recipients"]:
            member = guild.get_member(user_id)
            if member:
                pings.append(member.mention)

    try:
        await plugin.app.rest.create_message(
            event.timer.channel_id,
            content=" ".join(pings),
            embed=embed,
            components=miru.View()
            .add_item(miru.Button(emoji="🕔", label="Отложить", custom_id=f"RMSS:{event.timer.user_id}"))
            .build(),
            user_mentions=True,
        )
    except (
        hikari.ForbiddenError,
        hikari.NotFoundError,
        hikari.HTTPError,
    ):
        try:
            await user.send(
                content="Потерян доступ к каналу, с которорого было отправлено сообщение",
                embed=embed,
            )

        except hikari.ForbiddenError:
            logger.info(f"Не удалось доставить напоминание пользователю {user}.")


def load(bot: ChenBot) -> None:
    bot.add_plugin(reminders)


def unload(bot: ChenBot) -> None:
    bot.remove_plugin(reminders)


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
