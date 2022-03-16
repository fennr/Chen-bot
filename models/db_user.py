from typing import List
from typing import Optional

import attr


@attr.define()
class DatabaseUser:
    """
    Represents a user stored inside the database.
    """

    user_id: int
    guild_id: int
    flags: Optional[dict]
    notes: Optional[List[str]]
    warns: int = 0
