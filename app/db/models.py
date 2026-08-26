from __future__ import annotations

import enum
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PreferenceType(str, enum.Enum):
    HARD = "hard"
    SOFT = "soft"


class RecipeStatus(str, enum.Enum):
    APPROVED = "approved"
    CANDIDATE = "candidate"
    INACTIVE = "inactive"


class SessionState(str, enum.Enum):
    DRAFT_GENERATED = "DRAFT_GENERATED"
    AWAITING_ADMIN_FEEDBACK = "AWAITING_ADMIN_FEEDBACK"
    REVISION_IN_PROGRESS = "REVISION_IN_PROGRESS"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"


class Ingredient(Base, TimestampMixin):
    __tablename__ = "ingredients"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    category: Mapped[str | None] = mapped_column(String, nullable=True)

    recipe_ingredients: Mapped[list["RecipeIngredient"]] = relationship(back_populates="ingredient")


class Recipe(Base, TimestampMixin):
    __tablename__ = "recipes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    cuisine: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str] = mapped_column(String, default="main")
    meal_type: Mapped[str] = mapped_column(String, default="dinner")
    servings: Mapped[int] = mapped_column(Integer, default=4)
    prep_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cook_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    protein_type: Mapped[str | None] = mapped_column(String, nullable=True)
    vegetarian: Mapped[bool] = mapped_column(Boolean, default=False)
    seasonal: Mapped[list[str]] = mapped_column(JSON, default=list)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[RecipeStatus] = mapped_column(Enum(RecipeStatus), default=RecipeStatus.APPROVED, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", order_by="RecipeIngredient.position"
    )


class RecipeIngredient(Base, TimestampMixin):
    __tablename__ = "recipe_ingredients"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.id"), nullable=False)
    ingredient_id: Mapped[str] = mapped_column(ForeignKey("ingredients.id"), nullable=False)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")
    ingredient: Mapped[Ingredient] = relationship(back_populates="recipe_ingredients")


class Preference(Base, TimestampMixin):
    __tablename__ = "preferences"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    type: Mapped[PreferenceType] = mapped_column(Enum(PreferenceType), nullable=False)
    rule: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str | None] = mapped_column(String, nullable=True)


class WeeklyPlanningSession(Base, TimestampMixin):
    __tablename__ = "weekly_planning_sessions"
    __table_args__ = (UniqueConstraint("week_start", name="uq_weekly_session_week_start"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    week_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    state: Mapped[SessionState] = mapped_column(Enum(SessionState), default=SessionState.DRAFT_GENERATED, nullable=False)
    draft_version: Mapped[int] = mapped_column(Integer, default=1)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    admin_chat_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context: Mapped[dict] = mapped_column(JSON, default=dict)

    meal_plan: Mapped["MealPlan | None"] = relationship(back_populates="session", cascade="all, delete-orphan")
    feedback: Mapped[list["Feedback"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class MealPlan(Base, TimestampMixin):
    __tablename__ = "meal_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("weekly_planning_sessions.id"), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String, default="draft")

    session: Mapped[WeeklyPlanningSession] = relationship(back_populates="meal_plan")
    items: Mapped[list["MealPlanItem"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class MealPlanItem(Base, TimestampMixin):
    __tablename__ = "meal_plan_items"
    __table_args__ = (UniqueConstraint("plan_id", "date", "meal_slot", name="uq_plan_date_slot"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    plan_id: Mapped[str] = mapped_column(ForeignKey("meal_plans.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    meal_slot: Mapped[str] = mapped_column(String, nullable=False)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.id"), nullable=False)
    servings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    admin_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    original_recipe_id: Mapped[str | None] = mapped_column(String, nullable=True)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    plan: Mapped[MealPlan] = relationship(back_populates="items")
    recipe: Mapped[Recipe] = relationship()


class Feedback(Base, TimestampMixin):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("weekly_planning_sessions.id"), nullable=True)
    original_recipe_id: Mapped[str | None] = mapped_column(String, nullable=True)
    replacement_recipe_id: Mapped[str | None] = mapped_column(String, nullable=True)
    admin_text: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    permanent: Mapped[bool] = mapped_column(Boolean, default=False)

    session: Mapped[WeeklyPlanningSession | None] = relationship(back_populates="feedback")


class PantryItem(Base, TimestampMixin):
    __tablename__ = "pantry_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    ingredient_name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    permanent: Mapped[bool] = mapped_column(Boolean, default=True)


class TelegramRecipient(Base, TimestampMixin):
    __tablename__ = "telegram_recipients"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    chat_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

