from enum import Enum as PyEnum

from sqlalchemy import Enum


def str_enum(enum_cls: type[PyEnum], name: str) -> Enum:
    """Stores the enum's values as varchar + a CHECK constraint, not a native
    Postgres ENUM, so adding a value later is a plain constraint swap."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda e: [m.value for m in e],
    )
