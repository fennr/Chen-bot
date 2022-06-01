from __future__ import annotations

import datetime
import enum
import logging
import typing as t

import attr
import hikari
import lightbulb
import miru
#from miru.abc import ViewItem

from etc import constants as const
from models.db_user import DatabaseUser
from models.db_user import DatabaseUserFlag
from models.errors import DMFailedError
from models.errors import RoleHierarchyError
from models.events import TimerCompleteEvent
from models.events import WarnCreateEvent
from models.events import WarnRemoveEvent
from models.events import WarnsClearEvent
from models.timer import TimerEvent
from models.views import AuthorOnlyNavigator
from utils import helpers

if t.TYPE_CHECKING:
    from models.bot import ChenBot

logger = logging.getLogger(__name__)


class ActionType(enum.Enum):
    """Enum containing all possible moderation actions."""

    BAN = "Ban"
    SOFTBAN = "Softban"
    TEMPBAN = "Tempban"
    KICK = "Kick"
    TIMEOUT = "Timeout"
    WARN = "Warn"


class ModerationFlags(enum.Flag):
    """A set of flags governing behaviour of moderation actions."""

    NONE = 0
    """An empty set of moderation setting flags."""

    DM_USERS_ON_PUNISH = 1 << 0

    """DM users when punishing them via a moderation action."""

    IS_EPHEMERAL = 1 << 1
    """Responses to moderation actions should be done ephemerally."""


@attr.define()
class ModerationSettings:
    """Settings for moderation actions."""

    flags: ModerationFlags = ModerationFlags.DM_USERS_ON_PUNISH
    """Flags governing behaviour of moderation actions."""


MAX_TIMEOUT_SECONDS = 2246400  # Duration of segments to break timeouts up to


class ModActions:
    """Class containing all moderation actions that can be performed by the bot.
    It also handles miscallaneous moderation tasks such as tempban timers, timeout chunks & more."""

    def __init__(self, bot: ChenBot) -> None:
        self.app = bot
        self.app.subscribe(TimerCompleteEvent, self.timeout_extend)
        self.app.subscribe(hikari.MemberCreateEvent, self.reapply_timeout_extensions)
        self.app.subscribe(hikari.MemberUpdateEvent, self.remove_timeout_extensions)
        self.app.subscribe(TimerCompleteEvent, self.tempban_expire)
        self.app.subscribe(miru.ComponentInteractionCreateEvent, self.handle_mod_buttons)

    async def get_settings(self, guild: hikari.SnowflakeishOr[hikari.PartialGuild]) -> ModerationSettings:
        """Get moderation settings for a guild.

        Parameters
        ----------
        guild : hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild to get moderation settings for.

        Returns
        -------
        t.Dict[str, bool]
            The guild's moderation settings.
        """
        records = await self.app.db_cache.get(table="mod_config", guild_id=hikari.Snowflake(guild))
        if records:
            return ModerationSettings(flags=ModerationFlags(records[0].get("flags")))

        return ModerationSettings()

    async def pre_mod_actions(
        self,
        guild: hikari.SnowflakeishOr[hikari.Guild],
        target: t.Union[hikari.Member, hikari.User],
        action_type: ActionType,
        reason: t.Optional[str] = None,
    ) -> None:
        """
        Actions that need to be executed before a moderation action takes place.
        """
        helpers.format_reason(reason, max_length=1500)
        guild_id = hikari.Snowflake(guild)
        settings = await self.get_settings(guild_id)
        types_conj = {
            ActionType.WARN: "Предупреждение на",
            ActionType.TIMEOUT: "Тайм-аут на",
            ActionType.KICK: "Кик на",
            ActionType.BAN: "Бан на",
            ActionType.SOFTBAN: "Софт бан на",
            ActionType.TEMPBAN: "Временный бан на",
        }

        if settings.flags & ModerationFlags.DM_USERS_ON_PUNISH and isinstance(target, hikari.Member):
            gateway_guild = self.app.cache.get_guild(guild_id)
            assert isinstance(gateway_guild, hikari.GatewayGuild)
            guild_name = gateway_guild.name if gateway_guild else "Сервер не определен"
            try:
                await target.send(
                    embed=hikari.Embed(
                        title=f"❗ **Внимание**",
                        description=f"{types_conj[action_type]} **{guild_name}**.\n**Причина:** ```{reason}```",
                        color=const.ERROR_COLOR,
                    )
                )
            except (hikari.ForbiddenError, hikari.HTTPError):
                raise DMFailedError("Failed delivering direct message to user.")

    async def post_mod_actions(
        self,
        guild: hikari.SnowflakeishOr[hikari.Guild],
        target: t.Union[hikari.Member, hikari.User],
        action_type: ActionType,
        reason: t.Optional[str] = None,
    ) -> None:
        """
        Actions that need to be executed after a moderation action took place.
        """
        pass

    async def handle_mod_buttons(self, event: miru.ComponentInteractionCreateEvent) -> None:
        """Handle buttons related to moderation quick-actions."""

        # Format: ACTION:<user_id>:<moderator_id>
        if not event.custom_id.startswith(("UNBAN:", "JOURNAL:")):
            return

        moderator_id = hikari.Snowflake(event.custom_id.split(":")[2])

        if moderator_id != event.user.id:
            await event.context.respond(
                embed=hikari.Embed(
                    title="❌ Действие запрещено",
                    description="Это действие доступно только модератору, выполнившему команду",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        action = event.custom_id.split(":")[0]
        user_id = hikari.Snowflake(event.custom_id.split(":")[1])

        assert event.member and event.guild_id

        if action == "UNBAN":
            perms = lightbulb.utils.permissions_for(event.member)
            if not helpers.includes_permissions(perms, hikari.Permissions.BAN_MEMBERS):
                await event.context.respond(
                    embed=hikari.Embed(
                        title="❌ Отсутствуют разрешения",
                        description="У вас нет необходимых разрешений для разблокировки пользователей",
                        color=const.ERROR_COLOR,
                    ),
                    flags=hikari.MessageFlag.EPHEMERAL,
                )
                return

            user = await event.app.rest.fetch_user(user_id)
            embed = await self.unban(
                user,
                event.member,
                reason=helpers.format_reason("Разбан по кнопке быстрого действия", moderator=event.member),
            )
            await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

        if action == "JOURNAL":
            notes = await self.get_notes(user_id, event.guild_id)

            if notes:
                navigator = AuthorOnlyNavigator(event.context, pages=helpers.build_note_pages(notes))  # type: ignore
                await navigator.send(event.interaction, ephemeral=True)

            else:
                await event.context.respond(
                    embed=hikari.Embed(
                        title="📒 Записи журнала для этого пользователя",
                        description=f"Для этого пользователя нет записей в журнале. Модерационные действия оставят тут запись или ее можно внести командой `/journal add {event.user}`",
                        color=const.EMBED_BLUE,
                    ),
                    flags=hikari.MessageFlag.EPHEMERAL,
                )

        if not event.message:
            return

        view = miru.View.from_message(event.message)

        '''for item in view.children:
            assert isinstance(item, ViewItem)
            if item.custom_id == event.custom_id:
                item.disabled = True'''

        try:
            await event.message.edit(components=view)
        except:
            logging.error("Ошибка в mod_action из-за эфемерного сообщения")

    async def timeout_extend(self, event: TimerCompleteEvent) -> None:
        """
        Extends timeouts longer than 28 days by breaking them into multiple chunks.
        """
        timer = event.timer

        if timer.event != TimerEvent.TIMEOUT_EXTEND:
            return

        if not event.get_guild():
            return

        member = event.app.cache.get_member(timer.guild_id, timer.user_id)
        assert timer.notes is not None
        expiry = int(timer.notes)

        if member:
            me = self.app.cache.get_member(timer.guild_id, event.app.user_id)
            assert me is not None

            if not helpers.can_harm(me, member, hikari.Permissions.MODERATE_MEMBERS):
                return

            if expiry - helpers.utcnow().timestamp() > MAX_TIMEOUT_SECONDS:

                await event.app.scheduler.create_timer(
                    helpers.utcnow() + datetime.timedelta(seconds=MAX_TIMEOUT_SECONDS),
                    TimerEvent.TIMEOUT_EXTEND,
                    timer.guild_id,
                    member,
                    notes=timer.notes,
                )
                await member.edit(
                    communication_disabled_until=helpers.utcnow() + datetime.timedelta(seconds=MAX_TIMEOUT_SECONDS),
                    reason="Применено автоматическое продление времени",
                )

            else:
                timeout_for = helpers.utcnow() + datetime.timedelta(
                    seconds=expiry - round(helpers.utcnow().timestamp())
                )
                await member.edit(
                    communication_disabled_until=timeout_for, reason="Применено автоматическое продление времени"
                )

        else:
            db_user = await DatabaseUser.fetch(timer.user_id, timer.guild_id)

            if DatabaseUserFlag.TIMEOUT_ON_JOIN ^ db_user.flags:
                db_user.flags = db_user.flags | DatabaseUserFlag.TIMEOUT_ON_JOIN
                db_user.data["timeout_expiry"] = expiry
                await db_user.update()

    async def reapply_timeout_extensions(self, event: hikari.MemberCreateEvent):
        """
        Reapply timeout if a member left between two timeout extension cycles.
        """
        me = self.app.cache.get_member(event.guild_id, self.app.user_id)
        assert me is not None

        if not helpers.can_harm(me, event.member, hikari.Permissions.MODERATE_MEMBERS):
            return

        db_user = await DatabaseUser.fetch(event.member.id, event.guild_id)

        if db_user.flags ^ DatabaseUserFlag.TIMEOUT_ON_JOIN:
            return

        expiry = db_user.data.pop("timeout_expiry", 0)
        db_user.flags = db_user.flags ^ DatabaseUserFlag.TIMEOUT_ON_JOIN
        await db_user.update()

        if expiry - helpers.utcnow().timestamp() < 0:
            # If this is in the past already
            return

        if expiry - helpers.utcnow().timestamp() > MAX_TIMEOUT_SECONDS:
            await self.app.scheduler.create_timer(
                helpers.utcnow() + datetime.timedelta(seconds=MAX_TIMEOUT_SECONDS),
                TimerEvent.TIMEOUT_EXTEND,
                event.member.guild_id,
                event.member,
                notes=str(expiry),
            )
            await event.member.edit(
                communication_disabled_until=helpers.utcnow() + datetime.timedelta(seconds=MAX_TIMEOUT_SECONDS),
                reason="Применено автоматическое продление времени",
            )

        else:
            await event.member.edit(
                communication_disabled_until=expiry,
                reason="Применено автоматическое продление времени",
            )

    async def remove_timeout_extensions(self, event: hikari.MemberUpdateEvent):
        """
        Remove all timeout extensions if a user's timeout was removed.
        """
        if not event.old_member:
            return

        if event.old_member.communication_disabled_until() == event.member.communication_disabled_until():
            return

        if event.member.communication_disabled_until() is None:
            records = await self.app.db.fetch(
                """SELECT id FROM timers WHERE guild_id = $1 AND user_id = $2 AND event = $3""",
                event.guild_id,
                event.member.id,
                TimerEvent.TIMEOUT_EXTEND.value,
            )

            if not records:
                return

            for record in records:
                await self.app.scheduler.cancel_timer(record.get("id"), event.guild_id)

    async def tempban_expire(self, event: TimerCompleteEvent) -> None:
        """Handle tempban timer expiry and unban user."""

        if event.timer.event != TimerEvent.TEMPBAN:
            return

        # Ensure the guild still exists
        guild = event.get_guild()

        if not guild:
            return

        try:
            await guild.unban(event.timer.user_id, reason="Пользователь разблокирован: срок временного бана истек")
        except Exception as e:
            logger.info(f"Ошибка разбана {event.timer.user_id} от {event.timer.guild_id}: {e.__class__}: {e}")

    async def get_notes(
        self, user: hikari.SnowflakeishOr[hikari.PartialUser], guild: hikari.SnowflakeishOr[hikari.Guild]
    ) -> t.Optional[t.List[str]]:
        """Returns a list of strings corresponding to a user's journal.

        Parameters
        ----------
        user : hikari.SnowflakeishOr[hikari.PartialUser]
            The user whose journal should be retrieved.
        guild : hikari.SnowflakeishOr[hikari.Guild]
            The guild the user belongs to.

        Returns
        -------
        t.Optional[t.List[str]]
            A list of strings corresponding to the user's journal, if found.
        """

        db_user = await DatabaseUser.fetch(hikari.Snowflake(user), hikari.Snowflake(guild))
        return db_user.notes

    async def add_note(
        self, user: hikari.SnowflakeishOr[hikari.PartialUser], guild: hikari.SnowflakeishOr[hikari.Guild], note: str
    ) -> None:
        """Add a new journal entry to this user.

        Parameters
        ----------
        user : hikari.SnowflakeishOr[hikari.PartialUser]
            The user whose journal should be updated.
        guild : hikari.SnowflakeishOr[hikari.Guild]
            The guild the user belongs to.
        note : str
            The contents of the new journal entry.
        """

        note = helpers.format_reason(note, max_length=256)

        db_user = await DatabaseUser.fetch(hikari.Snowflake(user), hikari.Snowflake(guild))

        notes = db_user.notes if db_user.notes else []
        notes.append(f"{helpers.format_dt(helpers.utcnow(), style='d')}: {note}")
        db_user.notes = notes

        await db_user.update()

    async def clear_notes(
        self, user: hikari.SnowflakeishOr[hikari.PartialUser], guild: hikari.SnowflakeishOr[hikari.Guild]
    ) -> None:
        """Clear all journal entries a user has.

        Parameters
        ----------
        user : hikari.SnowflakeishOr[hikari.PartialUser]
            The user whose journal should be cleared.
        guild : hikari.SnowflakeishOr[hikari.Guild]
            The guild the user belongs to.
        """

        db_user = await DatabaseUser.fetch(hikari.Snowflake(user), hikari.Snowflake(guild))
        db_user.notes = []
        await db_user.update()

    async def warn(
        self, member: hikari.Member, moderator: hikari.Member, reason: t.Optional[str] = None
    ) -> hikari.Embed:
        """Warn a user, incrementing their warn counter, and logging the event if it is set up.

        Parameters
        ----------
        member : hikari.Member
            The member to be warned.
        moderator : hikari.Member
            The moderator who warned the member.
        reason : t.Optional[str], optional
            The reason for this action, by default None

        Returns
        -------
        hikari.Embed
            The response to show to the invoker.
        """
        db_user = await DatabaseUser.fetch(member.id, member.guild_id)
        db_user.warns += 1
        await db_user.update()

        reason = helpers.format_reason(reason, max_length=1000)

        embed = hikari.Embed(
            title="⚠️ Выдано предупреждение",
            description=f"**{member}** предупрежден **{moderator}**.\n**Причина:** ```{reason}```",
            color=const.WARN_COLOR,
        )
        try:
            await self.pre_mod_actions(member.guild_id, member, ActionType.WARN, reason)
        except DMFailedError:
            embed.set_footer("Невозможно отправить сообщение пользователю")

        userlog = self.app.get_plugin("Logging")
        assert userlog is not None

        await self.app.dispatch(WarnCreateEvent(self.app, member.guild_id, member, moderator, db_user.warns, reason))
        await self.post_mod_actions(member.guild_id, member, ActionType.WARN, reason)
        return embed

    async def clear_warns(
        self, member: hikari.Member, moderator: hikari.Member, reason: t.Optional[str] = None
    ) -> hikari.Embed:
        """Clear a user's warns, dispatches a WarnsClearEvent.

        Parameters
        ----------
        member : hikari.Member
            The member to clear warnings for.
        moderator : hikari.Member
            The moderator responsible for clearing the warnings.
        reason : t.Optional[str], optional
            The reason for clearing the warnings, by default None

        Returns
        -------
        hikari.Embed
            The response to show to the invoker.
        """
        db_user = await DatabaseUser.fetch(member, member.guild_id)
        db_user.warns = 0
        await db_user.update()

        reason = helpers.format_reason(reason)

        await self.app.dispatch(WarnsClearEvent(self.app, member.guild_id, member, moderator, db_user.warns, reason))

        return hikari.Embed(
            title="✅ Предупреждения сняты",
            description=f"**{member}** предупреждения были сняты.\n**Причина:** ```{reason}```",
            color=const.EMBED_GREEN,
        )

    async def remove_warn(
        self, member: hikari.Member, moderator: hikari.Member, reason: t.Optional[str] = None
    ) -> hikari.Embed:
        """Removes a warning from the user, dispatches a WarnRemoveEvent.

        Parameters
        ----------
        member : hikari.Member
            The member to remove a warning from.
        moderator : hikari.Member
            The moderator responsible for removing the warning.
        reason : t.Optional[str], optional
            The reason for removing the warning, by default None

        Returns
        -------
        hikari.Embed
            The response to show to the invoker.
        """
        db_user = await DatabaseUser.fetch(member, member.guild_id)

        if db_user.warns <= 0:
            return hikari.Embed(
                title="❌ Нет предупреждений",
                description=f"У этого пользователя нет предупреждений",
                color=const.ERROR_COLOR,
            )

        db_user.warns -= 1
        await db_user.update()

        reason = helpers.format_reason(reason)

        await self.app.dispatch(WarnRemoveEvent(self.app, member.guild_id, member, moderator, db_user.warns, reason))

        return hikari.Embed(
            title="✅ Предупреждение снято",
            description=f"Предупреждение снято с **{member}**.\n**Текущее количество:** `{db_user.warns}`\n**Причина:** ```{reason}```",
            color=const.EMBED_GREEN,
        )

    async def timeout(
        self,
        member: hikari.Member,
        moderator: hikari.Member,
        duration: datetime.datetime,
        reason: t.Optional[str] = None,
    ) -> hikari.Embed:
        """Time out the member for the specified duration.

        Parameters
        ----------
        member : hikari.Member
            The member to time out.
        moderator : hikari.Member
            The moderator to log the timeout under.
        duration : datetime.datetime
            The duration of the timeout.
        reason : t.Optional[str], optional
            The reason for the timeout, by default None

        Returns
        -------
        hikari.Embed
            The response to display to the user.
        """
        raw_reason = helpers.format_reason(reason, max_length=1500)
        reason = helpers.format_reason(reason, moderator, max_length=512)

        me = self.app.cache.get_member(member.guild_id, self.app.user_id)
        assert me is not None
        # Raise error if cannot harm user
        helpers.can_harm(me, member, hikari.Permissions.MODERATE_MEMBERS, raise_error=True)

        embed = hikari.Embed(
            title="🔇 " + "Пользователь отправлен в тайм-аут",
            description=f"**{member}** в таймауте до {helpers.format_dt(duration)}.\n**Причина:** ```{raw_reason}```",
            color=const.ERROR_COLOR,
        )

        try:
            await self.pre_mod_actions(member.guild_id, member, ActionType.TIMEOUT, reason=raw_reason)
        except DMFailedError:
            embed.set_footer("Ошибка отправки сообщения пользователю")

        if duration > helpers.utcnow() + datetime.timedelta(seconds=MAX_TIMEOUT_SECONDS):
            await self.app.scheduler.create_timer(
                helpers.utcnow() + datetime.timedelta(seconds=MAX_TIMEOUT_SECONDS),
                TimerEvent.TIMEOUT_EXTEND,
                member.guild_id,
                member,
                notes=str(round(duration.timestamp())),
            )
            await member.edit(
                communication_disabled_until=helpers.utcnow() + datetime.timedelta(seconds=MAX_TIMEOUT_SECONDS),
                reason=reason,
            )

        else:
            await member.edit(communication_disabled_until=duration, reason=reason)

        await self.post_mod_actions(member.guild_id, member, ActionType.TIMEOUT, reason=raw_reason)
        return embed

    async def remove_timeout(
        self, member: hikari.Member, moderator: hikari.Member, reason: t.Optional[str] = None
    ) -> None:
        """Removes a timeout from a user with the specified reason.

        Parameters
        ----------
        member : hikari.Member
            The member to remove timeout from.
        moderator : hikari.Member
            The moderator to log the timeout removal under.
        reason : t.Optional[str], optional
            The reason for the timeout removal, by default None
        """

        reason = helpers.format_reason(reason, moderator)

        await member.edit(communication_disabled_until=None, reason=reason)

    async def ban(
        self,
        user: t.Union[hikari.User, hikari.Member],
        moderator: hikari.Member,
        duration: t.Optional[datetime.datetime] = None,
        *,
        soft: bool = False,
        days_to_delete: int = 0,
        reason: t.Optional[str] = None,
    ) -> hikari.Embed:
        """Ban a user from a guild.

        Parameters
        ----------
        user : Union[hikari.User, hikari.Member]
            The user that needs to be banned.
        guild_id : Snowflake
            The guild this ban is taking place in.
        moderator : hikari.Member
            The moderator to log the ban under.
        duration : Optional[str], optional
            If specified, the duration of the ban, by default None
        soft : bool, optional
            If True, the ban is a softban, by default False
        days_to_delete : int, optional
            The days of message history to delete, by default 1
        reason : Optional[str], optional
            The reason for the ban, by default hikari.UNDEFINED

        Returns
        -------
        hikari.Embed
            The response embed to display to the user.

        Raises
        ------
        RuntimeError
            Both soft & tempban were specified.
        """
        reason = reason or "Причина не указана"

        if duration and soft:
            raise RuntimeError("Ban type cannot be soft when a duration is specified.")

        me = self.app.cache.get_member(moderator.guild_id, self.app.user_id)
        assert me is not None

        perms = lightbulb.utils.permissions_for(me)

        if not helpers.includes_permissions(perms, hikari.Permissions.BAN_MEMBERS):
            raise lightbulb.BotMissingRequiredPermission(perms=hikari.Permissions.BAN_MEMBERS)

        if isinstance(user, hikari.Member) and not helpers.is_above(me, user):
            raise RoleHierarchyError

        if duration:
            reason = f"[TEMPBAN] Забанен до: {duration} (UTC)  |  {reason}"

        elif soft:
            reason = f"[SOFTBAN] {reason}"

        raw_reason = reason
        reason = helpers.format_reason(reason, moderator, max_length=512)

        embed = hikari.Embed(
            title="🔨 Пользователь забанен",
            description=f"**{user}** был забанен.\n**Причина:** ```{raw_reason}```",
            color=const.ERROR_COLOR,
        )

        try:
            try:
                await self.pre_mod_actions(moderator.guild_id, user, ActionType.BAN, reason=raw_reason)
            except DMFailedError:
                embed.set_footer("Ошибка отправки сообщения пользователю")

            await self.app.rest.ban_user(moderator.guild_id, user.id, delete_message_days=days_to_delete, reason=reason)

            record = await self.app.db.fetchrow(
                """SELECT * FROM timers WHERE guild_id = $1 AND user_id = $2 AND event = $3""",
                moderator.guild_id,
                user.id,
                "tempban",
            )
            if record:
                await self.app.scheduler.cancel_timer(record.get("id"), moderator.guild_id)

            if soft:
                await self.app.rest.unban_user(moderator.guild_id, user.id, reason="Автоматическая разблокировка после софтбана")

            elif duration:
                await self.app.scheduler.create_timer(
                    expires=duration, event=TimerEvent.TEMPBAN, guild=moderator.guild_id, user=user
                )

            await self.post_mod_actions(moderator.guild_id, user, ActionType.BAN, reason=raw_reason)
            return embed

        except (hikari.ForbiddenError, hikari.HTTPError):
            return hikari.Embed(
                title="❌ Ошибка",
                description="Это может быть связано с ошибкой сети. Повторите попытку позднее",
                color=const.ERROR_COLOR,
            )

    async def unban(self, user: hikari.User, moderator: hikari.Member, reason: t.Optional[str] = None) -> hikari.Embed:
        """Unban a user from a guild.

        Parameters
        ----------
        user : hikari.User
            The user to be unbanned.
        moderator : hikari.Member
            The moderator who is unbanning this user.
        reason : t.Optional[str], optional
            The reason for the unban, by default None

        Returns
        -------
        hikari.Embed
            The response to show to the invoker.

        Raises
        ------
        lightbulb.BotMissingRequiredPermission
            Application is missing permissions to BAN_MEMBERS.
        """
        me = self.app.cache.get_member(moderator.guild_id, self.app.user_id)
        assert me is not None

        perms = lightbulb.utils.permissions_for(me)

        raw_reason = reason
        reason = helpers.format_reason(reason, moderator, max_length=512)

        if not helpers.includes_permissions(perms, hikari.Permissions.BAN_MEMBERS):
            raise lightbulb.BotMissingRequiredPermission(perms=hikari.Permissions.BAN_MEMBERS)

        try:
            await self.app.rest.unban_user(moderator.guild_id, user.id, reason=reason)
            return hikari.Embed(
                title="🔨 Пользователь разбанен",
                description=f"**{user}** был разбанен.\n**Причина:** ```{raw_reason}```",
                color=const.EMBED_GREEN,
            )
        except (hikari.HTTPError, hikari.ForbiddenError, hikari.NotFoundError) as e:
            if isinstance(e, hikari.NotFoundError):
                return hikari.Embed(
                    title="❌ Ошибка",
                    description="Этот пользователь не забанен",
                    color=const.ERROR_COLOR,
                )

            return hikari.Embed(
                title="❌ Ошибка",
                description="Это может быть связано с проблемами с сетью. Повторите попытку позднее",
                color=const.ERROR_COLOR,
            )

    async def kick(
        self,
        member: hikari.Member,
        moderator: hikari.Member,
        *,
        reason: t.Optional[str] = None,
    ) -> hikari.Embed:
        """Kick a member from the specified guild.

        Parameters
        ----------
        member : hikari.Member
            The member that needs to be kicked.
        moderator : hikari.Member
            The moderator to log the kick under.
        reason : Optional[str], optional
            The reason for the kick, by default None

        Returns
        -------
        hikari.Embed
            The response embed to display to the user. May include any
            potential input errors.
        """
        raw_reason = reason or "Причина не указана"
        reason = helpers.format_reason(reason, moderator, max_length=512)

        me = self.app.cache.get_member(member.guild_id, self.app.user_id)
        assert me is not None
        # Raise error if cannot harm user
        helpers.can_harm(me, member, hikari.Permissions.MODERATE_MEMBERS, raise_error=True)

        embed = hikari.Embed(
            title="🚪👈 Пользователь кикнут",
            description=f"**{member}** был кикнут.\n**Причина:** ```{raw_reason}```",
            color=const.ERROR_COLOR,
        )

        try:
            try:
                await self.pre_mod_actions(member.guild_id, member, ActionType.KICK, reason=raw_reason)
            except DMFailedError:
                embed.set_footer("Ошибка отправки сообщения пользователю")

            await self.app.rest.kick_user(member.guild_id, member, reason=reason)
            await self.post_mod_actions(member.guild_id, member, ActionType.KICK, reason=raw_reason)
            return embed

        except (hikari.ForbiddenError, hikari.HTTPError):
            return hikari.Embed(
                title="❌ Ошибка",
                description="Это может быть связано с проблемами с сетью. Повторите попытку позднее",
                color=const.ERROR_COLOR,
            )


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
