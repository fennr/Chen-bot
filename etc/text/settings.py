from dataclasses import dataclass

@dataclass(frozen=True)
class Buttons:
    Main: str
    Back: str
    Moderation: str
    Logging: str
    Reports: str
    Role: str
    Channel: str
    Exit: str
    ColorLogs: str

@dataclass(frozen=True)
class Titles:
    ModSettings: str
    LogSettings: str
    ChannelNotFound: str

@dataclass(frozen=True)
class Descriptions:
    ChannelNotFound: str


button = Buttons(
    Main="Главная",
    Back="Назад",
    Moderation="Модерация",
    Logging="Логгирование",
    Reports="Репорты",
    Role="Роль",
    Channel="Канал",
    Exit="Выход",
    ColorLogs="Выводить логи",
)

title = Titles(
    ModSettings="Настройки модерации",
    LogSettings="Настройки логгирования",
    ChannelNotFound="❌ Канал не найден"
)

desc = Descriptions(
    ChannelNotFound="Не удалось найти канал. Введите ID канала"
)