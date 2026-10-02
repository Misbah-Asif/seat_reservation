from enum import Enum


class SeatStatusEnum(str, Enum):
    AVAILABLE = "available"
    HELD = "held"
    CONFIRMED = "confirmed"


class SeatTypeEnum(str, Enum):
    REGULAR = "regular"
    SPECIAL = "special"
    VIP = "vip"


class ReservationStatusEnum(str, Enum):
    HELD = "held"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
