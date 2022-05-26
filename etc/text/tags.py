from dataclasses import dataclass

@dataclass(frozen=True)
class Titles:
    TagName: str
    TagContent: str
    UnknownTag: str

@dataclass(frozen=True)
class Descriptions:
    TagName: str
    TagContent: str


title = Titles(
    TagName="Имя метки",
    TagContent="Содержимое",
    UnknownTag="❌ Неизвестная метка"

)

desc = Descriptions(
    TagName="Введите имя метки...",
    TagContent="Введите содержимое, поддерживается markdown разметка..."
)