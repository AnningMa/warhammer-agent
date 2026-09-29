"""PDF coordinate conversion."""


def top_left_bbox(bbox: dict, height: float) -> list[float]:
    if bbox["coord_origin"] == "BOTTOMLEFT":
        return [bbox["l"], height - bbox["t"], bbox["r"], height - bbox["b"]]
    if bbox["coord_origin"] == "TOPLEFT":
        return [bbox["l"], bbox["t"], bbox["r"], bbox["b"]]
    raise ValueError("Unknown coordinate origin")
