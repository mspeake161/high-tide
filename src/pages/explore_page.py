from gi.repository import Adw
from gi.repository import Gtk
from gi.repository import GLib
from gi.repository import Gio
from gi.repository import Gdk

import tidalapi
from tidalapi.page import PageItem, PageLink
from tidalapi.mix import Mix, MixType
from tidalapi.artist import Artist
from tidalapi.album import Album
from tidalapi.media import Track
from tidalapi.playlist import Playlist

from ..lib import utils

import threading
import requests
import random

from .page import Page

class explorePage(Page):
    __gtype_name__ = 'explorePage'

    def _load_page(self):
        builder = Gtk.Builder.new_from_resource("/io/github/nokse22/high-tide/ui/pages_ui/home_page_template.ui")

        page_content = builder.get_object("_main")
        explore_content = builder.get_object("_content")

        explore = self.window.session.explore()

        # print(explore.categories)

        for index, category in enumerate(explore.categories):
            items = []

            if isinstance(category.items[0], PageLink):
                carousel = Adw.Carousel()

                flow_box = Gtk.FlowBox(homogeneous=True, height_request=100)
                carousel.append(flow_box)
                explore_content.append(carousel)
            else:
                carousel, cards_box = self.get_carousel(category.title)
                explore_content.append(carousel)

            print(category.items)

            buttons_for_page = 0

            for index, item in enumerate(category.items):
                if isinstance(item, PageItem): # Featured
                    button = self.get_page_item_card(item)
                    cards_box.append(button)
                elif isinstance(item, PageLink): # Generes and moods
                    if buttons_for_page == 4:
                        flow_box = Gtk.FlowBox(homogeneous=True, height_request=100)
                        carousel.append(flow_box)
                        buttons_for_page = 0
                    button = self.get_page_link_card(item)
                    flow_box.append(button)
                    buttons_for_page += 1
                elif isinstance(item, Mix): # Mixes and for you
                    button = self.get_mix_card(item)
                    cards_box.append(button)
                elif isinstance(item, Album):
                    album_card = self.get_album_card(item)
                    cards_box.append(album_card)
                elif isinstance(item, Artist):
                    button = self.get_artist_card(item)
                    cards_box.append(button)
                elif isinstance(item, Playlist):
                    button = self.get_playlist_card(item)
                    cards_box.append(button)

        self.content.remove(self.spinner)
        self.content.append(page_content)
