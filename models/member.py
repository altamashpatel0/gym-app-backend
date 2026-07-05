import enum
from sqlalchemy import Column, Integer, String, Date, Enum as SAEnum
from database import Base          # adjust import path to match your project


class ShiftEnum(str, enum.Enum):
    """Allowed shift values — keep in sync with frontend SHIFT_VALUES constant."""
    DAY   = "Day"
    NIGHT = "Night"


class Member(Base):
    __tablename__ = "members"

    id                  = Column(Integer, primary_key=True, index=True)
    name                = Column(String,  nullable=False)
    phone               = Column(String,  nullable=False, index=True)
    email               = Column(String,  nullable=True)
    address             = Column(String,  nullable=True)
    dob                 = Column(Date,    nullable=True)
    age                 = Column(Integer, nullable=True)
    gender              = Column(String,  nullable=True)
    status              = Column(String,  default="active")
    plan_id             = Column(Integer, nullable=True)          # FK in full model
    join_date           = Column(Date,    nullable=True)
    renewal_date        = Column(Date,    nullable=True)
    assigned_trainer_id = Column(Integer, nullable=True)
    photo_url           = Column(String,  nullable=True)

    # server_default ensures existing DB rows silently become "Day" with no
    # data-loss migration. The Python-level default handles ORM-created objects.
    shift = Column(
        String,
        nullable=False,
        default=ShiftEnum.DAY.value,
        server_default=ShiftEnum.DAY.value,
    )
