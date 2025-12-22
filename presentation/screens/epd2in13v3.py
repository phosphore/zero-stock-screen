from presentation.screens.epd2in13v2 import Epd2in13v2
from presentation.screens.screen_utils import parse_screen_payload

try:
    from waveshare_epd import epd2in13_V3
except ImportError:
    pass


class Epd2in13v3(Epd2in13v2):
    @staticmethod
    def _init_display():
        epd = epd2in13_V3.EPD()
        epd.init()
        epd.Clear(0xFF)
        return epd

    def update(self, data):
        prices, market_closed = parse_screen_payload(data)
        self.form_image(prices, self.screen_draw, market_closed)
        screen_image_rotated = self.screen_image.rotate(180)
        self.epd.display(self.epd.getbuffer(screen_image_rotated))

    def close(self):
        epd2in13_V3.epdconfig.module_exit()
