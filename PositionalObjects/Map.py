import json
from pathlib import Path

from PIL import Image


class Map:
    def __init__(
        self,
        x_multiplier: float,
        y_multiplier: float,
        x_scalar_add: float,
        y_scalar_add: float,
        image_width: int,
        image_height: int,
        img_path: str,
    ):
        self.x_multiplier = x_multiplier
        self.y_multiplier = y_multiplier
        self.x_scalar_add = x_scalar_add
        self.y_scalar_add = y_scalar_add
        self.image_width = image_width
        self.image_height = image_height
        self.img_path = img_path

    def game_to_image(self, game_x: float, game_y: float) -> tuple[float, float]:
        x = game_y * self.x_multiplier + self.x_scalar_add
        y = game_x * self.y_multiplier + self.y_scalar_add
        return x * self.image_width, y * self.image_height

    @classmethod
    def from_map_json(cls, map_json_path: str, image_path: str | None = None) -> "Map":
        with open(map_json_path, "r", encoding="utf-8") as file_handle:
            payload = json.load(file_handle)

        x_multiplier = float(payload.get("xMultiplier"))
        y_multiplier = float(payload.get("yMultiplier"))
        x_scalar_add = float(payload.get("xScalarToAdd"))
        y_scalar_add = float(payload.get("yScalarToAdd"))

        if image_path is None:
            map_dir = Path(map_json_path).parent
            map_name = map_dir.name
            image_candidates = sorted(map_dir.glob(f"{map_name}_*.png"))
            if not image_candidates:
                raise FileNotFoundError(f"No map image found in {map_dir}")
            image_path = str(image_candidates[0])

        with Image.open(image_path) as image:
            width, height = image.size

        return cls(
            x_multiplier=x_multiplier,
            y_multiplier=y_multiplier,
            x_scalar_add=x_scalar_add,
            y_scalar_add=y_scalar_add,
            image_width=width,
            image_height=height,
            img_path=image_path,
        )
