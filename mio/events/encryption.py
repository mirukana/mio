from datetime import timedelta

from . import RoomEvent, Sources


class EncryptionOn(RoomEvent):
    type = "m.room.encryption"
    make = Sources(
        sessions_max_duration = ("content", "rotation_period_ms"),
        sessions_max_messages = ("content", "rotation_period_msgs"),
        algorithm             = ("content", "algorithm"),
    )

    sessions_max_duration: timedelta = timedelta(weeks=1)
    sessions_max_messages: int       = 100
    algorithm:             str       = "m.megolm.v1.aes-sha2"
