MARKET_STATUS_LABEL = "MARKET CLOSED"


def parse_screen_payload(data):
    if isinstance(data, dict):
        prices = data.get("prices") or []
        market_closed = bool(data.get("market_closed"))
        return prices, market_closed
    return data or [], False


def _text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _stroke_fill_from_fill(fill):
    if isinstance(fill, tuple):
        return tuple(255 for _ in fill)
    return 255


def draw_market_status(
    draw,
    font,
    screen_width,
    screen_height,
    fill,
    position="top",
    stroke_width=1,
    stroke_fill=None,
):
    text_width, text_height = _text_size(draw, MARKET_STATUS_LABEL, font)
    padding = 2
    if position == "bottom":
        x = screen_width - text_width - padding
        y = screen_height - text_height - padding
    else:
        x = screen_width - text_width - padding
        y = padding
    if stroke_width and stroke_fill is None:
        stroke_fill = _stroke_fill_from_fill(fill)
        
    draw.text(
        (x, y),
        MARKET_STATUS_LABEL,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )
