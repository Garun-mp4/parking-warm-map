from typing import Literal
import cv2
import numpy as np
from pydantic import BaseModel, Field, model_validator


class Slot(BaseModel):
    id: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=50)
    points: list[tuple[float, float]] = Field(min_length=3, max_length=16)

    @model_validator(mode="after")
    def polygon(self):
        if not all(0 <= x <= 1 and 0 <= y <= 1 for x, y in self.points):
            raise ValueError("Координаты должны находиться внутри изображения")
        contour = np.array(self.points, dtype=np.float32)
        if cv2.contourArea(contour) < 0.00005 or not cv2.isContourConvex(contour):
            raise ValueError(
                "Нужен выпуклый полигон без пересечений и с ненулевой площадью"
            )
        return self


class Layout(BaseModel):
    slots: list[Slot] = Field(max_length=200)

    @model_validator(mode="after")
    def unique(self):
        if len({slot.id for slot in self.slots}) != len(self.slots):
            raise ValueError("Номера мест должны быть уникальными")
        return self


class Settings(BaseModel):
    model: Literal["yolo11n", "yolo11s", "malexnet"] = "malexnet"
    confidence: float = Field(default=0.70, ge=0.2, le=0.99)
    sample_seconds: float = Field(default=1.0, ge=0.25, le=120)
    confirm_seconds: float = Field(default=2.0, ge=0, le=30)
    time_scale: float = Field(default=1.0, ge=1, le=10000)

    @model_validator(mode="after")
    def classifier_threshold(self):
        if self.model == "malexnet" and self.confidence < 0.5:
            raise ValueError("Для mAlexNet порог должен быть не ниже 0.5")
        return self
